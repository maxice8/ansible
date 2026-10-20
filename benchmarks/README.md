# ARM emulation benchmark

Run from the repository development environment:

```sh
direnv exec . python3 benchmarks/emulation.py --output /tmp/qemu-baseline.json
```

The benchmark uses the flake's ARM Bash, file tools, Node.js and GCC. It fetches
missing binary outputs before timing and does not build missing tool packages
from source. Workloads create fixed inputs in temporary directories and check
file processing, JavaScript parsing/execution and compiled program outputs.
The compiled executable must have the AArch64 ELF machine identifier.
Each workload gets one unmeasured warm-up followed by three measured batches.
Timings include input creation, process startup and temporary-directory cleanup.
Dependency downloads and warm-ups are excluded.

Use `--jobs 4` to measure four independent jobs per batch. Compare jobs per
second across concurrency settings, not batch duration alone. Run comparisons
sequentially with other builds stopped. This is a synthetic build-tool benchmark;
it does not establish full Pingvin build performance or Nix sandbox compatibility.

The default emulator is the host's registered QEMU. Alternate commands are
explicit and never change binfmt registration. Put `--emulator` last:

```sh
direnv exec . env QEMU_TB_SIZE=256 python3 benchmarks/emulation.py --output /tmp/qemu-tb256.json
direnv exec . python3 benchmarks/emulation.py --output /tmp/arm64chroot.json --emulator /absolute/path/arm64chroot --jit -E "PATH={path}" -E LC_ALL=C -E TZ=UTC /
```

`arm64chroot` resets the guest environment. The `{path}` placeholder passes
the same ARM tool search path used by QEMU. Locale and timezone are explicit.

Each JSON file records tools, emulator command, QEMU environment, host, samples
and median throughput. A failed command, timeout or wrong result fails the run;
no successful report is written. Keep results outside the tracked checkout.
