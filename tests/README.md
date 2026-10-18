The managed guest is a **minimal ARM64 NixOS VM**, declared in `builder.nix` and
run by `vm.py`. Production remains Ubuntu. This deliberately does not validate
Ubuntu bootstrap, APT, AppArmor packaging or Ubuntu's complete filesystem layout.
Guest-only `/usr/bin` compatibility links and a writable unit directory let the
real service definitions and probes execute under NixOS. The directory is seeded
with NixOS's unit symlinks, then retained for System Manager's units across reboots.
Host/kernel acceptance remains separate.

Run from the repository development environment:

```sh
python3 -m tests.test_vm  # offline lifecycle/cache-planning checks
make build          # only boots for uncached ARM build jobs
make test           # boots, runs the existing shared-base suite, powers off
make deploy         # runs/reuses matching base acceptance before production activation
```

The runner is x86-native QEMU; guest programs and native Nix build jobs are ARM.
It allocates four virtual CPUs, 4 GiB RAM while running, and a sparse 24 GiB disk
per image generation. TCG emulation makes uncached compilation slower than ARM hardware.
Temporary boot images and runtime sockets are removed after guest shutdown.
No workstation binfmt registration, production builder or private host-store
share is used. `make test` never deploys the production host configuration.

`deploy.py` snapshots public code and encrypted inputs. The suite runs from that
immutable snapshot and uses generated synthetic Age/SOPS credentials. The VM
provides Nix declaratively, so the old Ubuntu/Pyinfra bootstrap checks are omitted.
The base fixture imports `services/base.nix`, not the full production host module.

Successful base-suite results are cached against the profile and all snapshot
inputs, including test code and VM configuration. A missing/changed record runs
the suite again; `make test` always forces execution. This is not an upstream
application test result, a passkey test or a complete CI workflow. The helper
checks required production units and local health separately after activation.

VM disks/cache are persistent beneath `~/.cache/mashu-nix/vm`, configurable with
`vm_dir=/path`. Image generations have separate disks. The `image` symlink is a
GC root. An initial image requires one-time ARM building/cache restoration;
`make vm-image builders='<specification>'` provisions it. Once present, it can
build its own updates. Do not remove that root before preparing its replacement.

Operations acquire one session lock and stop guests they started even after a
build/test failure. A borrowed running guest stays running. Shutdown uses normal
guest poweroff and refuses unexpected inhibitors. There are no autonomous OS
upgrades in the test image; image maintenance is explicit.

Suite logs, synthetic fixtures and `evidence.json` remain in a private
`/tmp/mashu-vm-test-*` directory printed by the helper. Guest console output and
`running.json` live beside its disk. For an acceptance failure, inspect the suite
log; its last `PASS` identifies the last completed stage. Retain failure evidence
before removing a disposable test directory.

Checks cover repeated activation, account preservation, state modes,
cross-service reads, filesystem/capability/network restrictions, resource limits,
configuration and secret changes, failed activation/start, previous generations,
reboot recovery, closure roots, removed units, and base deactivation/reinstallation.
Network controls independently
prove all denied destinations are reachable outside the sandbox.
The fixture's nftables unit owns only `inet homelab_probe_test` and restricts
UID 62000's loopback traffic to TCP 18081; cgroup-BPF handles non-loopback
denials. Both layers are checked in child processes and again after reboot.

VM acceptance does not prove enforcement on Mashu's Oracle kernel or reproduce
Ubuntu host integration. Configuration rollback cannot undo database migrations.
System Manager can return zero when a unit fails; actual readiness must be checked.
Before removing a unit, stop it while its old unit file still exists so its old
`ExecStop` can run. Retained-generation rollback must register and activate the
previous profile to restore the boot pointer as well as the running state.

Native ingress checks use `traefik-profile.nix` with a synthetic SOPS token and
runtime-generated certificate/key under `/var/lib/data/traefik`. The fixture
imports the real host module, disables external ACME issuance, and inherits
TLS settings from the entrypoint just like production. Do not use production
secrets or DNS credentials in this VM.

Copy `test_traefik.py` into the VM and run it as root after activating that
fixture. It refuses other hostnames. Checks cover both IP families, all final
routes, HTTPS redirects, unknown hosts, forwarding/header-alias spoofing,
bidirectional WebSocket frames, actual cgroup bind/metadata filtering, and
UID-scoped egress. Controls prove denied network destinations are listening.
Port-zero binds are deliberately permitted for Go's IPv6 support probe;
unapproved named listening ports are denied. Host firewall policy must also
restrict inbound ports.

The base lifecycle fixture imports `services/base.nix` directly so it never
enables production applications or requires their real decryption keys.

Native authentication checks use `pomerium-profile.nix`, which composes the
Traefik fixture with the real Pomerium module. Encrypt a synthetic fixture with
`cloudflare_dns_api_token`, `pomerium_cookie_secret`, `pomerium_shared_secret`,
`pomerium_idp_client_id` and `pomerium_idp_client_secret` for the VM's age identity.
The two key values are base64-encoded 32-byte test keys; client ID/secret are
`fixture-client` and `fixture-client-secret`. Keep the existing synthetic TLS
certificate/key from the ingress fixture. Never copy production credentials into
the VM.

Copy `test_pomerium.py` into the VM and run it as root after activating the fixture.
It refuses other hostnames, starts a synthetic issuer/backends, and adds VM-only
hostname/metadata-address controls. It verifies the complete OIDC code exchange,
five authenticated upstreams, forged identity/cookie rejection, invalid callbacks,
authenticated Argus WebSockets and actual service-cgroup network/bind isolation.
The script's `session` mode reuses its synthetic cookies without following redirects;
use it after a restart or a coherent database restore to prove session persistence.
Stop the native writer before copying/restoring `/var/lib/data/pomerium`.

Pomerium allocates internal loopback ports dynamically. Its unit verifies the
standard Linux ephemeral range (32768–60999), and its network/bind policy permits
that range. Other host loopback services in that range are therefore reachable;
SSH, metadata and unrelated named ports remain denied. Public listeners must stay
restricted by the host firewall. The persistent Pebble database lives one level
below the service directory so syncing its parent needs no listing permission on
`/var/lib/data`.

For the smaller Syncthing acceptance check, copy `test_syncthing.py` to the
explicitly selected deployment target and run it as root after activation.
It checks health, private state ownership, process capabilities, and actual
service-cgroup DNS/GUI access with SSH, metadata and unapproved binds denied.
It reads application state and adds only a short-lived probe process to the
service cgroup; it does not change Syncthing configuration or synchronized files.
Peer identities, folder paths/counts and backup recovery are separate operator
checks. This focused check requires the standard image's reachable SSH/metadata
controls; it does not create a VM fixture or exercise transfers/reboot.
