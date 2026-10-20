# Natsume measurements, 2026-10-20

Host: 13th Gen Intel(R) Core(TM) i7-13650HX, x86_64, Linux 7.2.10. QEMU user 11.1.2 comes from the
Natsume NixOS binfmt registration. ARM tool versions are fixed by this repository's
flake.lock; the raw JSON files record their store paths and all timed samples.

Each timed comparison below has one warm-up and three measured batches. Comparisons ran
sequentially. The workloads check their results. Numbers are wall-clock seconds
per batch; the four-job row runs four independent copies per batch.

| Variant | Jobs per batch | Files | Node.js | Compile |
|---|---:|---:|---:|---:|
| qemu-baseline | 1 | 0.274 | 5.358 | 13.637 |
| qemu-tb256 | 1 | 0.274 | 5.014 | 13.436 |
| qemu-nosve | 1 | 0.272 | 4.975 | 13.004 |
| qemu-jobs4 | 4 | 0.339 | 5.589 | 18.130 |
| qemu-repeat | 1 | 0.290 | 5.903 | 14.970 |
| arm64chroot-env | 1 | 0.155 | 6.555 | 11.924 |

The default repeat changed by about 8-10% on CPU-heavy workloads. The small
QEMU tuning differences therefore do not establish a stable improvement.
Four-job batches improve throughput by about 3.0-3.8 times over the first
single-job baseline. This does not determine the best Nix max-jobs/cores settings
for large builds or memory-heavy packages.

arm64chroot is faster on file operations and this C compilation workload, but
slower on Node.js. It is not a universal QEMU replacement. These direct-process
checks do not establish Nix sandbox compatibility or complete package builds.
No global emulator or Nix concurrency settings were changed.

The two `final-check.json` reports are separate one-batch validations of the
final harness, including the compiled executable's AArch64 ELF identifier. Both
emulators passed. Timeout failure handling also passed an explicit negative test.

## Reproduction

Run the commands in [the benchmark instructions](README.md) from the devenv
shell, with output files outside the checkout. Variants use:

- Baseline and repeat: the default command.
- qemu-tb256: `QEMU_TB_SIZE=256`.
- qemu-nosve: `QEMU_CPU=max,sve=off,sme=off`.
- qemu-jobs4: `--jobs 4`.
- arm64chroot-env: the explicit `--emulator` command shown in the instructions.

The arm64chroot executable was built in a temporary directory from
[sylirre/arm64emu-user commit 90fe88ca71794d29eecddc4b8925d68b79a2c342](https://github.com/sylirre/arm64emu-user/tree/90fe88ca71794d29eecddc4b8925d68b79a2c342)
using `make -j2` with the existing host GCC 16.2.0 and upstream default flags.
It was not installed or registered with binfmt. The first attempt without an
explicit guest PATH failed before timing; the reported run passes the same
ARM tool PATH, locale and timezone as QEMU.

Raw reports are under [results/](results/). The default QEMU command relies on
host binfmt for child processes. arm64chroot handles its guest process tree.
