# VPS continuity checks

`make test` checks the real Ubuntu VPS without deploying, restarting services,
changing firewall rules or rebooting anything. It does not build or start a VM.

The live test module is `test_vps.py`. It checks:

- Fresh SSH sessions over Tailscale and public recovery SSH, with connection
  multiplexing disabled. Both must reach the same Mashu machine. The recovery
  connection must use a non-Tailscale server address.
- A fresh connection to the deployment target, verified against that identity.
- Host SSH, Tailscale, resolved, the host firewall, Unbound and application units,
  with no failed systemd units.
- Tailscale's running/online status and the host's normal DNS resolution.
- Real Unbound DNS answers over UDP and TCP.
- Eleven local application health endpoints and public HTTPS access to Forgejo and
  Pocket ID from the workstation.

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
allow the timer to be disarmed. Checks are never cached.

The timer runs independently of SSH, but does not survive a reboot and cannot
undo application data migrations. After rollback, inspect
`journalctl -u mashu-deploy-rollback.service` and the active profile. Recovery
state remains in `/run/mashu-deploy` and the GC root remains at
`/nix/var/nix/gcroots/mashu-deploy-rollback`. Remove them only after verifying
recovery and stopping `mashu-deploy-rollback.timer`. Normal deployments and checks
never reboot the VPS; boot recovery is not verified by this suite.
Passkey login, actual file synchronization, CI jobs and backup restores still need
separate acceptance when their behavior changes.

Run the focused deployment guard tests with:

```sh
direnv exec . python3 -m unittest tests.test_deploy_guard
```
