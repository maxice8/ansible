# Mashu: Ubuntu + Nix

This repository describes Mashu's bootstrap and final state. Ubuntu supplies the
kernel, networking, OpenSSH, Nix daemon and OS updates. `bootstrap.sh` installs the
Nix and portable-service prerequisites over SSH. Nix and System Manager manage host
policy, service accounts, credentials and hardened systemd services.

Application state lives under **`/var/lib/data/<service>`**. Pingvin Share X and
CI jobs use separate rootless Podman runtimes; other applications run directly
under systemd. Caches, images and CI workspaces under `/var/cache` are disposable.
Release Argus and Pocket ID run from Nix-built `argus.raw` and `pocket-id.raw`
portable images. Deployment uses `portablectl` to persistently attach their units
and host systemd starts them at boot. No attachment wrapper runs at boot.

## Development environment

Install Nix and [devenv](https://devenv.sh/), then run:

```sh
devenv shell
```

`devenv.nix` installs the workstation tools and the pinned Python requirements
into its managed environment. With direnv, run `direnv allow` once. Keep local
commands, including Nix deployment helpers and pre-commit, inside this environment.

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
# Or: make bootstrap host=mashu-admin
```

Bootstrap checks for Ubuntu 26.04, installs Ubuntu's multi-user Nix, UID mapping
helpers, unattended updates and `systemd-container` (including `portablectl` and
`systemd-portabled`), enables Nix features and trusts the connecting administrator.
It preserves Ubuntu's Nix configuration, enables/restarts the Nix daemon and starts
the D-Bus-activated portable-service daemon. It does
not deploy applications or provision SSH keys. Keep public SSH22 available.

Follow [SERVICES.md](SERVICES.md) to provision the SOPS age identity and verify
credentials before the first Nix activation. Normal redeployments do not need
the private age identity on the workstation; the target decrypts credentials.

## Build and deploy

Versions come from `flake.lock` and the verified releases under `pkgs/`.
`hosts/mashu.nix` composes the final configuration. Each service lives under
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

`deploy.py` creates a temporary allowlisted snapshot and asks Nix which jobs
remain after cache lookup. Cached ARM outputs need no VM. Uncached ARM jobs start
the local **minimal NixOS ARM VM** automatically as a builder. Deployment checks
fresh Tailscale and public recovery SSH connections before activation and again
afterward, followed by live service, DNS and public HTTPS health checks. These
checks run against Ubuntu on Mashu; synthetic VM acceptance is no longer required.

```sh
make build                         # build only; boot the VM only for ARM cache misses
make test                          # read-only access and health checks on Mashu
make deploy host=mashu              # build, check access, activate, check access/health
make build builders=none            # forbid remote/VM build jobs
make vm-image                      # refresh and root the managed guest image
```

The builder guest has Nix and SSH, no desktop, cloud-init, APT, automatic
upgrades or host Nix-store mount. Its only host share is a read-only public SSH
key. Builds use a guest-only identity. Production state and private
keys are never copied into it. Whole-system QEMU uses TCG; no workstation binfmt
handler or persistent Nix-daemon builder configuration is installed.

The VM is started lazily, shared by the operation and shut down on success or
failure. An already-running managed guest is reused and left running. A session
lock prevents simultaneous use of one disk. Unexpected shutdown inhibitors are
reported rather than bypassed. Temporary boot images are removed after shutdown.
Persistent disks and Nix caches live under
`$XDG_CACHE_HOME/mashu-nix/vm` (normally `~/.cache/mashu-nix/vm`); a new boot image
gets its own disk. Use `vm_dir=/absolute/path` to select a separate cache.

The first guest image needs an ARM builder once, because NixOS generates native
ARM activation/configuration derivations. This workstation's initial image was
bootstrapped with the retained emulated builder. Its `image` symlink is a Nix GC
root. Later image updates boot the retained NixOS image to build its replacement.
For a fresh workstation, restore a built image closure/cache or explicitly supply
a one-time ARM builder:

```sh
make vm-image builders='<SSH builder specification>'
```

Local Nix commands use `sudo -n` so the daemon honors temporary builder settings;
the workstation needs passwordless sudo for these Nix operations. Deployment SSH
uses your normal account. Production is never selected as an automatic builder.

**Do not run `nix build path:.` in this checkout.** Ignored identities must not
enter the Nix store. The helper snapshots public modules/tools/tests plus encrypted
service secrets. Live continuity checks are read-only; application passkeys,
synchronization and complete CI pipelines need separate acceptance.

For a custom SSH configuration or a retained profile (rollback skips building current sources but still checks access and health):

```sh
python deploy.py deploy --target-host mashu-admin \
  --ssh-option=-F --ssh-option=/absolute/path/to/ssh_config \
  --store-path /nix/store/<previous-or-built-profile>
```

Record and retain the current profile before deploying:

```sh
ssh mashu-admin 'sudo readlink -f /nix/var/nix/profiles/system-manager-profiles/system-manager'
```

Inspect units and application behavior after activation. System Manager can
report success even when a unit fails; the helper checks actual readiness.
Registration controls the boot profile. To roll back, redeploy the retained
previous profile with `--store-path`, which registers and activates it. Binary
rollback cannot undo application database migrations. Never restart an old
writer against incompatible new data.

If removing a unit, explicitly stop it while its old unit file still exists:
System Manager otherwise removes the file before it can run its old `ExecStop`.
Nix upgrades and garbage collection are manual; retain recovery profile roots.

## Versions and secrets

```sh
make help
make check-updates
make update service=pomerium version=<version> dry_run=1
make update service=pomerium version=<version>
make secret service=pomerium
```

The release updater downloads both architecture archives and updates their
checksums, or prefetched ARM64 image digest/archive pins for Pingvin. Dry runs
fetch and verify the proposed artifacts but write nothing. A real update refuses
dirty package files and creates a commit containing only that package. Inspect
its diff and build/test the result before deployment; an upstream download hash
is not a substitute for reviewing release provenance. The updater never pushes
or deploys. Argus derives configured release versions from those package pins.

Netdata, Forgejo Runner and runtime dependencies come from locked Nixpkgs. Their
updater targets explain that they require a deliberate shared-input update;
they do not silently change the lock or unrelated dependencies. Review the
whole resulting package set when updating System Manager/Nixpkgs.

Secret prompts update `secrets/mashu.sops.yaml`; Backrest and Forgejo open the
SOPS editor for structured configuration and multiline credentials. Deploy the encrypted
change to install it. See [SERVICES.md](SERVICES.md) before rotating identity,
passkey/database encryption keys or service credentials.

## Backups and recovery

Backrest has one backup source: **`/var/lib/data`**. Keep the existing repository,
schedule, retention and encryption credentials. The controlled capture unit
coordinates consistent database copies; caches and CI workspaces are excluded
by placing them outside this root. Normal deployments do not trigger a backup.

For restoration, stop the affected service and any cooperating writers first.
Restore its directory, preserve ownership/mode, then start it and verify its
identity and application behavior before proceeding to another service. Do not
apply recursive blanket permissions across the shared root.

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
