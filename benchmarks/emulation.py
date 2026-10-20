#!/usr/bin/env python3
"""Measure cached ARM build tools with fixed inputs and checked outputs."""

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
import platform
import signal
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inputs(directory):
    for module in range(8):
        (directory / f"module{module}.c").write_text(
            "\n".join(
                f"unsigned f{module}_{index}(unsigned x) {{ return x * {index + 1}u + {module}u; }}"
                for index in range(64)
            )
        )
    (directory / "main.c").write_text(
        "#include <stdio.h>\n"
        + "\n".join(f"unsigned f{i}_0(unsigned);" for i in range(8))
        + '\nint main(void) { printf("%u\\n", '
        + " + ".join(f"f{i}_0(123u)" for i in range(8))
        + "); return 0; }\n"
    )
    (directory / "node.js").write_text("""
const vm = require('node:vm');
const crypto = require('node:crypto');
let sum = 0;
for (let i = 0; i < 1200; i++) {
  const source = Array.from({length: 96}, (_, j) => `const v${j} = ${j};`).join('\\n') + 'v95';
  sum += new vm.Script(source).runInNewContext();
}
if (sum !== 114000) throw new Error('Unexpected script result');
console.log(crypto.createHash('sha256').update(String(sum)).digest('hex'));
""")
    (directory / "files.sh").write_text("""set -eu
mkdir tree
for i in $(seq 1 128); do printf '%s\n' "$i" > "tree/$i"; done
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf tree.tar tree
gzip -n tree.tar
gzip -dc tree.tar.gz | tar -tf - > listing
test "$(wc -l < listing)" -eq 129
printf 'files-ok\n'
""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emulator", nargs=argparse.REMAINDER, default=["/run/binfmt/aarch64-linux"]
    )
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.jobs, args.runs, args.timeout) < 1:
        parser.error("jobs, runs and timeout must be positive")
    if not args.emulator:
        parser.error("emulator command must not be empty")
    flake = "git+" + ROOT.as_uri()
    expression = f"""let
      f = builtins.getFlake {json.dumps(flake)};
      p = import f.inputs.nixpkgs {{ system = "aarch64-linux"; }};
    in builtins.mapAttrs (_: p: toString p) {{
      inherit (p) bash coreutils gnutar gzip gcc nodejs_24;
    }}"""
    tools = json.loads(
        subprocess.check_output(
            ["nix", "eval", "--impure", "--json", "--expr", expression], text=True
        )
    )
    # Realize output paths only; unavailable tools must not trigger source builds.
    subprocess.run(["nix", "build", "--no-link", *tools.values()], check=True)
    environment = os.environ | {
        "PATH": ":".join(path + "/bin" for path in tools.values()),
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    emulator = [arg.replace("{path}", environment["PATH"]) for arg in args.emulator]
    commands = {
        "files": [tools["bash"] + "/bin/bash", "files.sh"],
        "node": [tools["nodejs_24"] + "/bin/node", "node.js"],
        "compile": [
            tools["bash"] + "/bin/bash",
            "-ec",
            "gcc -O2 -c module*.c; gcc -O2 main.c module*.o -o program; ./program",
        ],
    }
    expected = {"files": "files-ok\n", "node": "", "compile": "1012\n"}
    expected["node"] = hashlib.sha256(b"114000").hexdigest() + "\n"
    report = {
        "host": platform.uname()._asdict(),
        "tools": tools,
        "logical_cpus": os.cpu_count(),
        "emulator": args.emulator,
        "jobs": args.jobs,
        "runs": args.runs,
        "qemu_environment": {
            k: v for k, v in environment.items() if k.startswith("QEMU_")
        },
        "results": {},
    }

    def trial(task):
        with tempfile.TemporaryDirectory(prefix="mashu-emulation-") as tmp:
            directory = Path(tmp)
            inputs(directory)
            with subprocess.Popen(
                emulator + commands[task],
                cwd=directory,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            ) as process:
                try:
                    stdout, stderr = process.communicate(timeout=args.timeout)
                except BaseException:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise
                if process.returncode or stdout != expected[task]:
                    raise RuntimeError(
                        f"{task} failed ({process.returncode}): {stdout}\n{stderr}"
                    )

            if (
                task == "compile"
                and (directory / "program").read_bytes()[18:20] != b"\xb7\x00"
            ):
                raise RuntimeError("Compiler output is not little-endian AArch64 ELF")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for task in commands:
            trial(task)
            samples = []
            for _ in range(args.runs):
                start = time.monotonic()
                list(pool.map(trial, [task] * args.jobs))
                samples.append(round(time.monotonic() - start, 4))
            median = statistics.median(samples)
            report["results"][task] = {
                "seconds": samples,
                "median_seconds": median,
                "jobs_per_second": round(args.jobs / median, 4),
            }
            print(f"{task}: {median:.3f}s median for {args.jobs} jobs", flush=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
