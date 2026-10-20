# Mashu: Ubuntu + Nix

This repository configures Mashu with Nix and System Manager. Ubuntu supplies
the kernel, networking, OpenSSH, Nix daemon and OS updates. `bootstrap.sh`
installs the Nix prerequisites over SSH. Nix manages host policy, service
accounts, credentials and systemd services.

Application state lives under **`/var/lib/data/<service>`**. CI jobs use a
separate rootless Podman runtime. Applications run directly under systemd. Caches,
container images and CI workspaces under `/var/cache` are disposable.
Argus, Pocket ID, Traefik, Syncthing, ArchiSteamFarm, Pomerium and Forgejo run
from Nix-built portable images.
System Manager installs their systemd units. Each unit uses `RootImage=` to
run the image. Systemd starts the units at boot and restarts changed units
on deployment.

Applications use the host-local Unbound resolver, including MagicDNS forwarding
to Tailscale. The host retains systemd-resolved and Tailscale's DNS configuration;
Unbound sends tailnet queries to Tailscale at `100.100.100.100`.
Public queries use the configured public resolvers with DNSSEC validation.

## Development environment

Install Nix and [devenv](https://devenv.sh/), then run:

```sh
devenv shell
```

`devenv.nix` installs Python, pre-commit and the workstation tools from Nix.
With direnv, run `direnv allow` once. Keep local commands, including Nix deployment helpers and pre-commit, inside this environment.

Format Nix files with the pinned official formatter:

```sh
nix fmt -- $(git ls-files '*.nix')
```

## Access and external infrastructure

Configure both Tailscale access and an independent public SSH22 alias. For example:

```sshconfig
Host mashu
  HostName 100.91.248.66
  User ubuntu

Host mashu-admin
  HostName 2603:c025:4005:8f7e:0:b837:618:268c
  Port 22
  User ubuntu
```

Add your administrator identity, agent and strict host-key settings to both
entries. Verify the host key independently before accepting it. Both connections
must work without a password prompt. Public SSH remains key-only; Tailscale SSH
is the normal interactive path. Port **23 is Forgejo Git SSH**, not an admin shell.

Create an Ubuntu 26.04 ARM64 VPS with the existing `ubuntu` administrator and
passwordless sudo. The modules target Mashu's `enp0s6` interface and systemd 259+
with cgroup v2; edit the explicit host configuration before using another image.

In OCI ingress, use stateful rules and source port range All. Permit these
required destination ports for both IPv4 and IPv6:

| Protocol | Ports | Purpose |
| --- | --- | --- |
| TCP | 22, 23 | Recovery administration and Forgejo Git SSH |
| TCP | 80, 443 | Public web ingress |
| TCP and UDP | 22000 | Syncthing transfers |
| UDP | 41641 | Tailscale direct connections |

Point the maintained names at Mashu's public A/AAAA addresses: `git.maxice8.com`,
`id.maxice8.com`, `pomerium.maxice8.com` and the application names under
`*.mashu.maxice8.com`. Traefik obtains certificates through Cloudflare DNS-01.

## Bootstrap a fresh host

Use the independent administrator SSH alias and run:

```sh
./bootstrap.sh mashu-admin
```

Bootstrap assumes a fresh Oracle Ubuntu 26.04 ARM64 image with the `ubuntu`
administrator, your SSH key and passwordless sudo already configured. It installs
Nix, UID mapping helpers, AppArmor, Python, curl, CA certificates and unattended
updates. It enables flakes, trusts the connecting administrator and starts the
Nix daemon. It does not validate the image, run health checks, change SSH access
or modify cloud-init defaults. Keep public SSH22 available.

On a fresh host, install the SOPS age identity before activation:

```sh
ssh mashu-admin 'sudo install -d -m 0700 /var/lib/sops-nix &&
  sudo sh -c "set -C; umask 077; cat > /var/lib/sops-nix/key.txt"' < .age-key.txt
```

This command refuses to overwrite an existing identity. Keep the identity in
the password manager. The target decrypts credentials; normal deployments do
not need the private identity on the workstation.

## Build and deploy

Run Make from the direnv development environment:

```sh
make update         # update and commit only flake.lock
make build          # build without updating or committing
make diff           # compare the latest successful build with Mashu
make deploy         # activate and check Mashu over recovery SSH
make push           # push Git commits
```

`make update inputs=nixpkgs` updates only Nixpkgs. If `flake.lock` already has changes,
`make update` commits those changes without updating inputs again.
The lock-only commit uses `build(deps): update flake.lock` and leaves other staged
changes separate. If no lock changes remain, no commit is created.
A failed update leaves the lock file uncommitted. Run `make build` to check the
committed dependency versions before deploying. For other changes, stage the
intended files and run `git commit -m 'fix(service): describe the change'` inside
the development environment.
Keep unrelated tracked edits separate: builds include them too.

To review local changes before deployment:

```sh
make build && make diff
# Review the nvd output, then run make deploy when ready.
```

Successful profile builds retain a GC root at `./result`. `make diff host=<ssh-host>`
compares it with the host's registered System Manager profile using the `nvd`
installed by devenv; the default host is `mashu`. The command downloads missing
deployed store paths from the VPS into the workstation for comparison.
Local imports use passwordless sudo and accept unsigned paths only for this
copy over the authenticated SSH connection. Global signature checks stay enabled.
The SSH connection uses your normal identity and known-host checks, then closes
after comparison or failure. The command does not activate anything. The comparison shows package
versions and store paths, not application data or every configuration setting.
Packages inside portable images appear as image changes. A failed activation
can leave running services different from the registered profile.
A failed build leaves the previous `./result` intact.
Nix maintains both the profile and VM image links through `nix build --out-link`.

The root flake pins Nixpkgs. System Manager and sops-nix use that same package set.
Backrest, Pocket ID, Pomerium and Tailscale come from Nixpkgs. The packages under
`pkgs/` retain newer required releases or applications that Nixpkgs does not provide.
`hosts/mashu.nix` composes the host configuration. Each service lives under
`services/<name>/`, with `default.nix` as its module and its configuration, network
policy and helpers alongside it. Shared modules such as `base.nix`, `hardening.nix`,
`firewall.nix`, host policy, application accounts and rootless-container support stay
directly under `services/`. Service-local settings use `settings.nix`, and nftables
policies use `firewall.nft`; these firewalls also restrict outbound connectivity.

Service UIDs/GIDs are reserved in **5000–5999**. Ubuntu's `adduser`/`addgroup` and
`useradd`/`groupadd` automatically allocate ordinary accounts only in 1000–4999;
system accounts retain their normal range below 1000. Rootless container subordinate
IDs are separate and retain their explicit allocations.

```sh
make build
make deploy host=mashu-admin
```

`deploy.py` uses Nix's Git fetcher to freeze the tracked source files in the store.
Stage new files with `git add` before building. Ignored files stay outside the
snapshot. Nix downloads cached ARM outputs and builds uncached jobs locally with
host binfmt emulation. Deployment first requires fresh public recovery and
target SSH connections, before building or activation. Tailscale can be absent on
a new host.
After activation, deployment checks Tailscale and public SSH, then service, DNS
and public HTTPS health. These
checks run against Ubuntu on Mashu; synthetic VM acceptance is no longer required.
Post-deployment SSH checks allow up to twelve connection attempts, two seconds
apart, while services restart. Each connection still uses the ten-second SSH
connect timeout and verifies the machine identity. Application health checks
run even when an access check fails. Activation errors remain visible if a
later check also fails.

Build and upload progress use `nix-output-monitor` (`nom`) from devenv. The helper
prints build, copy, activation and readiness stages. Missing paths are sent from
the workstation's completed build to the VPS. The VPS does not redownload them
from public caches during this copy.

Normal deployments use public recovery SSH so Tailscale restarts cannot close
the activation connection. `--target-host` overrides this choice. Deployments use
`nom copy` to copy the built profile, then run its native System Manager
`bin/register-profile` and `bin/activate` entry points over SSH. There is no
separate workstation System Manager build. The Python wrapper manages builds
and access/health checks.

Deployment can interrupt applications on this single host. Changed Traefik and
Forgejo units restart, and a slow shutdown can delay the activation transaction.
The readiness wait confirms recovery; it does not provide zero-downtime rollout.

```sh
make build                       # build locally with ARM emulation
make deploy                     # deploy through public recovery SSH
make build builders='<SSH builder specification>' # use an explicit remote builder
make test                        # check VPS access and health
```

Make provides the command interface. Run it from the direnv shell; outside
that shell, use `direnv exec . make <target>`.
Build and deployment targets call `deploy.py`. Run `make help` for commands.

On an x86 NixOS workstation, enable ARM user-mode emulation in the host
configuration and switch to it before building:

```nix
boot.binfmt.emulatedSystems = [ "aarch64-linux" ];
boot.binfmt.preferStaticEmulators = true;
```

Natsume enables these settings in `oss/nixos`. NixOS registers the emulator and
adds `aarch64-linux` to Nix's supported build platforms. The native host kernel
runs ARM build processes through QEMU user-mode emulation. No VM is used.
An ARM workstation can build directly. Other workstations need equivalent
binfmt support or an explicit remote builder. Emulation does not provide an ARM
kernel for boot or kernel-specific tests. See [the ARM emulation benchmark](benchmarks/README.md)
for repeatable build-tool measurements and explicit emulator comparisons.

Local Nix commands use `sudo -n` so the daemon honors temporary builder settings;
the workstation needs passwordless sudo for these Nix operations. Deployment SSH
uses your normal account. Production is never selected as an automatic builder.

**Do not run `nix build path:.` in this checkout.** Ignored identities must not
enter the Nix store. Use Git-backed flake references such as `.#systemConfigs.mashu`.
Keep private identities and plaintext credentials untracked. Tracked source files,
including `services/login.defs`, enter the frozen snapshot. Live continuity checks
are read-only; application passkeys,
synchronization and complete CI pipelines need separate acceptance.

For a custom SSH configuration:

```sh
python deploy.py deploy --target-host mashu-admin \
  --ssh-option=-F --ssh-option=/absolute/path/to/ssh_config
```

To recover an older configuration, check out its Git revision and run the normal
deployment. Nix rebuilds missing store paths. There is no separate rollback profile
or activation path. Keep uncommitted work separate before changing revisions.
Registration controls the boot profile. Inspect units after activation: System
Manager can report success when a unit fails, so the helper checks readiness.
Deploying older code does not undo database migrations. Never restart an old
writer against incompatible new data.

If removing a unit, explicitly stop it while its old unit file still exists:
System Manager otherwise removes the file before it can run its old `ExecStop`.
Daily GC prunes System Manager generations older than one day and collects unused
store paths. Nix also retains the last generation before that cutoff. The
registered profile remains rooted. Application data is outside the
Nix store. Store optimisation runs weekly with low CPU and I/O priority.
Ubuntu still supplies the Nix daemon; Nix declares its included settings.
Diagnostic tools are available in `/run/current-system/sw/bin`.

The runner and rootless engine share `ci.slice`: CPU weight 25, memory throttling
at 3 GiB and a 4 GiB hard limit. Their existing individual limits still apply.

## Versions and secrets

```sh
make help
make check-updates
make update forgejo <version> dry_run=1
make update forgejo <version>
make secret service=pomerium
```

`flake.lock` is the version pin for Nixpkgs, System Manager and sops-nix.
Their input URLs follow upstream updates; `make update` advances the lock file.

Use Nixpkgs when it provides the application. A newer upstream release is not a
reason to add a version override. Check the binary cache before an upgrade and
defer uncached source builds for applications provided by Nixpkgs. Local
packaging is for applications that Nixpkgs does not provide.

Keep existing pins across a major-version gap or when the Nixpkgs replacement
is not fully cached. Minor and patch downgrades to Nixpkgs are otherwise allowed
after runtime compatibility checks.

| Service | Selected version | Package source |
| --- | --- | --- |
| Forgejo | 17.0.0 | Local pin; Nixpkgs is still on major version 16 |
| Traefik | 3.7.14 | Nixpkgs |
| Syncthing | 2.1.3 | Nixpkgs |
| ArchiSteamFarm | 6.3.10.6 | Existing local pin; Nixpkgs web UI is not cached |
| Release Argus | 0.39.0 | Local package; Nixpkgs `argus` is a different application |
| Pingvin Share X | 1.22.4 | Local package; the old Pingvin Share package was removed |

When Nixpkgs reaches Forgejo 17 or newer, remove its remaining local pin after
checking runtime compatibility. ASF can move to Nixpkgs once its separate web UI
is cached. At this lock revision, that would select 6.3.10.3 and lose the crafted-message
crash fix and .NET compatibility fixes listed in the
[upstream release notes](https://github.com/JustArchiNET/ArchiSteamFarm/releases/tag/6.3.10.6).

The release updater downloads both architecture artifacts and updates their
checksums. For Pingvin, it updates the source, npm caches and Prisma engines. Dry runs
fetch and verify the proposed artifacts but write nothing. A real update refuses
dirty package files and creates a commit containing only that package. Inspect
its diff and build/test the result before deployment; an upstream download hash
is not a substitute for reviewing release provenance. The updater never pushes
or deploys. Argus derives configured release versions from those package pins.

Traefik, Syncthing, Backrest, Pocket ID, Pomerium, Tailscale, Netdata,
Forgejo Runner and runtime dependencies come from locked Nixpkgs. Update them with `make update inputs=nixpkgs`.
Netdata follows Nixpkgs; defer newer upstream releases until the Nixpkgs package
and its binary cache are available.
The component updater does not edit their package versions. Review the whole
package set, including System Manager compatibility, before deploying a pin update.

Secret prompts update `secrets/mashu.sops.yaml`; Backrest and Forgejo open the
SOPS editor for structured configuration and multiline credentials. Deploy the encrypted
change to install it. Preserve identity and database encryption keys on upgrades.
Verify each consumer after credential rotation.

## Backups and recovery

Backrest has one backup source: **`/var/lib/data`**. Keep the existing repository,
schedule, retention and encryption credentials. The controlled capture unit
briefly stops Forgejo, Pocket ID, Pingvin, Pomerium and Syncthing to capture
consistent database copies, then starts them again even if capture fails.
Caches and CI workspaces are excluded
by placing them outside this root. Normal deployments do not trigger a backup.

For restoration, stop the affected service and any cooperating writers first.
Restore its application directory, including repositories or uploads. Restore the
matching `backup-capture` directory from the same backup snapshot, then replace
the database with its captured copy:

| Captured path under `/var/lib/data` | Application path under `/var/lib/data` |
| --- | --- |
| `backup-capture/forgejo.sqlite` | `forgejo/data/gitea.db` |
| `backup-capture/pocket-id.sqlite` | `pocket-id/pocket-id.db` |
| `backup-capture/pingvin-share.sqlite` | `pingvin-share/data/pingvin-share.db` |
| `backup-capture/pomerium/` | `pomerium/databroker/` |
| `backup-capture/syncthing/` | `syncthing/config/` |

Captured SQLite files are self-contained. Remove the target database's restored
`-wal` and `-shm` sidecars before starting its service. Replace Pomerium and
Syncthing database directories with the captured directories; do not merge them.
Set restored files to the affected service's UID/GID and preserve private modes.
Start the service and verify its identity and application behavior. Do not apply
recursive blanket permissions across the shared root.

Keep the SOPS identity, administrator SSH key, backup encryption credentials and
application recovery information separately accessible. Restoring the Tailscale
directory restores a node identity; never run two copies of that identity.

## Verification and repository hygiene

```sh
ssh mashu-admin 'sudo systemctl --failed; sudo nft list table inet hostfilter'
ssh mashu 'sudo systemctl is-active tailscaled forgejo syncthing'
curl -4 --fail https://git.maxice8.com/api/healthz
curl -6 --fail https://git.maxice8.com/api/healthz
make check-updates
ruff check .
```

Use `make test` for the read-only checks in [tests/README.md](tests/README.md).
It opens fresh Tailscale and public SSH connections, verifies services and DNS,
and checks public HTTPS. The default recovery address is the public IPv6 address
above; `recovery_host=mashu-admin` selects your configured recovery alias.
Deployment checks detect access loss but do not provide automatic rollback if
both access paths are blocked. No check reboots the VPS.

Forgejo requires approval for PR workflows from users without write access.
Repository owners, writers, Actions team writers and instance administrators
run workflows automatically. There are no additional PR trust grants. Keep this
policy: approving an outside author also gives their code access to the shared
CI cache. Grant write access or permanent trust only to trusted developers.

Enable hooks after each clone and inspect changes before committing:

```sh
pre-commit install --install-hooks
pre-commit run --all-files
git diff --check
git diff --cached
```

Hooks check private keys, local identity files, formatting and secrets. They do
not replace credential review or a full-history scan. Do not bypass them with
`--no-verify`. Keep credentials and unrelated work out of commits.

## Pingvin Share

Pingvin uses a Nix-built NestJS backend on `127.0.0.1:3002` and a Next.js frontend
on `127.0.0.1:3001`. Traefik sends `/api/` requests to the backend. The frontend
uses its own account and can reach only the backend for server rendering.

The database and uploads stay in `/var/lib/data/pingvin-share/data`. Custom images
stay in `/var/lib/data/pingvin-share/images`. Startup applies database migrations,
runs the compiled seed and copies missing default images. The frontend mounts
images read-only through a shared group and cannot read the private database
directory or access the backend through a shared process identity.

The package pins the source, both npm dependency caches and matching Prisma
engines. Build it separately with `make build output=packages.aarch64-linux.pingvin-share`.
The component updater refreshes these pins together. Review and build the result
before deployment. Deploying older code does not restore application data.

See [host management](HOST-MANAGEMENT.md) for the Ubuntu cleanup, declared host
configuration and the remaining System Manager migration options.
