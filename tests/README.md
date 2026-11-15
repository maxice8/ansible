# VPS continuity checks

`make test` checks the real Ubuntu VPS without deploying, restarting services,
changing firewall rules or rebooting anything. It does not build or start a VM.
The runner DNS check creates one temporary container from a cached Alpine image
and removes it after the check. A failed probe still attempts cleanup; cleanup
failure fails the check. It does not pull an image, mount host data or change job
containers. A cached Alpine image is required.

The live test module is `test_vps.py`. It checks:

- Fresh SSH sessions over Tailscale and public recovery SSH, with connection
  multiplexing disabled. Both must reach the same Mashu machine. The recovery
  connection must use a non-Tailscale server address.
- A fresh connection to the deployment target, verified against that identity.
- Host SSH, Tailscale, resolved, the host firewall, Unbound and application units,
  with no failed systemd units.
- Tailscale's running/online status and the host's normal DNS resolution.
- Real Unbound DNS answers over UDP and TCP. Application resolution is tested in
  the Forgejo runner mount namespace with its service UID. Container resolution
  is tested through the existing rootless engine API.
- At least 1 GiB and 10000 free inodes on the Nix and application data filesystems.
  This is an activation reserve, not an estimate of the candidate closure size.
- Eleven local application health endpoints and public HTTPS access to Forgejo,
  Pocket ID and both Share routes from the workstation. The Share API must return
  its health response, not a frontend fallback page.
- Pomerium redirects to Pocket ID, and all five protected application routes
  redirect unauthenticated clients to Pomerium. Redirect destinations are checked
  without following them. Login query strings are not included in diagnostics.
- Repository refs over Git SSH on port 23. The workstation must have read access
  to `ssh://git@git.maxice8.com:23/max/ansible.git`.
- Three further readiness samples over at least 15 seconds. Host, DNS, application,
  HTTPS and login checks repeat. The container and Git probes run once. Managed
  service restart counters and main PIDs must stay unchanged during the window.

Deployments and continuity checks use a checklist with separate SSH, DNS,
application and public HTTPS results. Terminals show active checks in cyan,
passes in green, failures in red and armed rollback in amber. Set `NO_COLOR`
to disable colours. Redirected output has no terminal control sequences.
Successful build, copy and assertion logs are hidden; failures include diagnostics.

Each required unit must be active. Local HTTP checks run concurrently with a
shared 65-second deadline. The remote health command has a 240-second SSH
timeout to allow the DNS probes and container cleanup to finish. Runner API
requests have a 10-second network timeout and a 15-second process timeout.

Defaults are Tailscale hostname `mashu` and public recovery target
`ubuntu@2603:c025:4005:8f7e:0:b837:618:268c`. Override them when needed:

```sh
make test
make test host=mashu tailscale_host=mashu recovery_host=mashu-admin
python -m tests.test_vps --recovery-host mashu-admin
```

SSH uses existing identities and known-host verification; it never weakens host
key checking. Checks require noninteractive SSH and passwordless sudo. The
workstation must have Tailscale access and connectivity to the public recovery
address (IPv6 for the default address). A missing recovery alias or failed
connection fails the check visibly.

Deployment requires fresh public recovery and target SSH connections before
activation. It does not require Tailscale to exist yet. Before activation, the
candidate SSH configuration is tested in a private mount namespace. The check
requires public-key access for ubuntu, port 22 and public IPv4/IPv6 listeners.
The host firewall must pass `nft --check` and contain a direct port 22 allowance
before blocking rules. Candidate System Manager assertions must also pass.
These checks are conservative heuristics, not a full network or authentication simulation.

A host-side systemd timer is then armed for 30 minutes. It retains the previous
registered profile as a GC root. If deployment fails or the workstation disconnects,
the timer restores the previous managed SSH file and host firewall, reloads SSH,
and registers and activates the previous profile. A second guarded deployment
is refused while recovery state exists. After activation, all
access paths and service/DNS/HTTPS health are checked, including after a failed
activation. Post-deployment SSH transport failures get up to twelve attempts
with two-second intervals. Identity mismatches and remote script failures are
not retried. Standalone checks still make one attempt. Application health checks
run even if access fails. Only successful activation and all readiness checks
allow the timer to be disarmed. The stability window completes before disarming.
After arming, the timer must be active and waiting, with a future monotonic
trigger within 30 minutes. The previous profile GC root is verified. Disarming
must stop the timer before recovery state and its GC root are removed. Each
cleanup result is checked. Checks are never cached.

The timer runs independently of SSH, but does not survive a reboot and cannot
undo application data migrations. After rollback, inspect
`journalctl -u mashu-deploy-rollback.service` and the active profile. Recovery
state remains in `/run/mashu-deploy` and the GC root remains at
`/nix/var/nix/gcroots/mashu-deploy-rollback`. Remove them only after verifying
recovery and stopping `mashu-deploy-rollback.timer`. Normal deployments and checks
never reboot the VPS; boot recovery is not verified by this suite.
Passkey login, actual file synchronization, CI jobs and backup restores still need
separate acceptance when their behavior changes.

Run the local deployment and readiness regression tests with:

```sh
direnv exec . python3 -m unittest discover
```
