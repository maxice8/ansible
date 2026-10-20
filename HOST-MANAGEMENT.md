# Mashu configuration ownership

Keep the Ubuntu/Oracle image and cloud-init as the host foundation. System
Manager owns application services and explicit local policy. Do not copy native
default files into Nix merely to reproduce their existing contents.

## Ownership summary

| Owner | Configuration and runtime |
| --- | --- |
| Oracle cloud-init | Instance metadata, base Netplan networking, hostname handling, localhost hosts entry, initial administrator/SSH setup, root disk initialization and configured launch scripts |
| Ubuntu and Oracle image defaults | Kernel, bootloader, initramfs, systemd, PAM, SSH/sudo binaries, networkd/resolved/timesyncd, base APT sources and Pro integration, locale, image sysctls and provider agents |
| System Manager | Applications, service accounts, secrets, backups, application DNS, Tailscale, firewall, custom SSH restrictions, retention, resource limits, service masks, IPv6 overlay, update policy, Nix settings include and the existing CIS audit job |

Cloud-init's program is installed through Ubuntu. Oracle supplies image
configuration and instance metadata. Oracle Cloud Agent and the unified logging
agent are separate services; keeping cloud-init does not replace those agents.

## Cloud-init on this instance

The inventory reads `/etc/cloud/cloud.cfg`, provider drop-ins, module frequency
metadata and `/var/lib/cloud/instance/sem`. It does not read SSH private keys,
instance user-data or credentials.

| Responsibility | Native location or behavior | When configured to run |
| --- | --- | --- |
| Base networking | `/etc/netplan/50-cloud-init.yaml`; primary NIC match/name, DHCPv4 and MTU | Network stage; datasource/event dependent |
| Hostname | `/etc/hostname`; `preserve_hostname: false` in the image config | Initial hostname once per instance; update handler each boot, respecting manual hostname changes |
| Local hosts entry | `/etc/hosts`; Oracle's `99-oracle-compute-infra-datasource.cfg` selects `manage_etc_hosts: localhost` | Each boot; updates the local hostname entry rather than rewriting the whole file |
| Default account and SSH | Initial `ubuntu` account/groups, sudo access, authorized keys and SSH host-key setup | Once per instance |
| Storage | Partition growth, root filesystem resizing, configured disks and mounts | Growth/resize handlers each boot; disk/mount setup once per instance |
| APT and Pro | Initial source generation and optional package/update/Pro settings | Once per instance, when applicable |
| Locale, keyboard, time | Initial locale and configured keyboard/NTP/timezone settings | Once per instance, when applicable |
| Initialization scripts | Vendor/user scripts, per-instance scripts, boot commands and per-boot scripts | Depends on module; see the full inventory below |

The completion cache records handlers for initial APT, locale, mounts, hostname,
users/groups, passwords, SSH, SSH import/fingerprints, GRUB settings and vendor,
user and per-instance scripts. A completion marker proves the handler ran; it
does not prove that every optional feature made a change. For example, having
`chef`, `puppet` or `ansible` in the module list does not mean those tools are
installed or managing our applications.

Do not run `cloud-init clean` or replay initialization to apply this ownership
change. Native files were restored from System Manager's original backups. Normal
future cloud-init operation remains enabled. The pinned engine did not restore
backed-up files merely because their declarations were removed, so the eight
verified backups were restored explicitly after releasing ownership.

## Avoiding overlapping owners

System Manager does not declare these native files:

- `/etc/cloud/cloud.cfg` or Oracle's `99-oracle-*.cfg` drop-ins.
- `/etc/netplan/50-cloud-init.yaml`.
- `/etc/hostname`, `/etc/hosts` or `/etc/locale.conf`.
- `/etc/apt/sources.list.d/ubuntu.sources` or Ubuntu Pro repositories/authentication.
- `/etc/sysctl.d/99-cloudimg-ipv6.conf` or `/etc/sysctl.d/scsi-log-level.conf`.
- The base `/etc/nix/nix.conf`; bootstrap adds the include for our local settings.

The temporary Nix-owned `90-homelab.cfg` cloud-init override is removed. Its
`manage_etc_hosts: false` setting also had lower precedence than Oracle's `99-`
file, which was another reason to return the hosts file to native ownership.

Keep custom policy in separate files:

| Custom policy | System Manager file |
| --- | --- |
| IPv6 RA and DHCPv6 supplement | `/etc/netplan/60-public-ipv6.yaml`; the base cloud-init file stays untouched |
| SSH authentication restrictions | `/etc/ssh/sshd_config.d/10-homelab.conf`; Ubuntu keeps the daemon, base config and cloud-init snippet |
| Periodic APT policy | `/etc/apt/apt.conf.d/52homelab-periodic`; native defaults remain in their own files |
| APT cleanup/no automatic reboot | `/etc/apt/apt.conf.d/52unattended-upgrades-local` |
| Custom sysctls | `/etc/sysctl.d/90-homelab.conf`; separate keys from image sysctls |
| Journal/core retention | `/etc/systemd/journald.conf.d/10-retention.conf` and `/etc/systemd/coredump.conf.d/10-retention.conf` |
| Nix daemon settings | `/etc/nix/homelab.conf`, included by the native Nix config |
| Service identity policy | Reserved service IDs and sub-ID ranges; explicit custom adduser/login policy |

The adduser/login files are deliberate local policy exceptions: they reserve
service IDs and keep login restrictions. They are not copies of Ubuntu defaults.
Application DNS stays in service namespaces; the host resolver remains with
native systemd-resolved and Tailscale. Future instance launch scripts must not
write files assigned to System Manager.

## Cleanup retained

On 2026-10-20, removed duplicate APT Tailscale, bottom, DNS tools and tree,
ModemManager, UDisks, fwupd, legacy iptables persistence and the Tailscale keyring.
Removed 55 orphaned dependencies. Installed APT packages fell from 517 to 452.
System Manager masks the removed daemons and alternate firewall loaders. Native
jq, iptables and nftables remain for provider scripts outside APT's dependency
graph. Active Oracle agents and Ubuntu Pro integration remain.

Removed the disabled CIS repository that still selected Ubuntu 24.04. Archived
the inactive sources.list copy, old Tailscale helper and saved firewall copies.
The custom CIS audit service/timer remains Nix-managed, using native Ubuntu tools
and its original midnight UTC schedule. The audit is skipped when native USG is
not installed; the minimal bootstrap does not install USG or benchmarks. The old `/usr/local/sbin/usg-audit` helper
remains unused; the unit executes the generated Nix script.

Root-only backups and package-operation logs are under
`/root/host-cleanup-20261020-084612`. They can contain credentials; never put them
in this repository or the Nix store.

## Further migration boundary

System Manager supports arbitrary managed files, packages, systemd services,
sockets, timers, paths, mounts, automounts, slices and tmpfiles, plus selected
NixOS adapters. This capability does not mean that native defaults should move.

Its Nix, SSH, sudo, users, SSH-client, nginx, ACME and automatic-upgrade modules
are available. The SSH and sudo adapters retain Ubuntu binaries/PAM. Keep
cloud-init account/SSH provisioning separate from application service accounts.
Use additional Nix modules for new local requirements, with one owner per file
or service. Kernel, bootloader, initramfs, systemd PID 1 and PAM remain Ubuntu.

## Configured cloud-init modules

This is the configured module inventory, not a list of active external managers.
Frequencies come from the installed Ubuntu cloud-init modules. Optional handlers
can do nothing when the corresponding user/vendor configuration is absent.

### cloud_init_modules

| Module | Frequency |
| --- | --- |
| `seed_random` | once-per-instance |
| `bootcmd` | always |
| `write_files` | once-per-instance |
| `growpart` | always |
| `resizefs` | always |
| `disk_setup` | once-per-instance |
| `mounts` | once-per-instance |
| `set_hostname` | once-per-instance |
| `update_hostname` | always |
| `update_etc_hosts` | always |
| `ca_certs` | once-per-instance |
| `rsyslog` | once-per-instance |
| `users_groups` | once-per-instance |
| `ssh` | once-per-instance |
| `set_passwords` | once-per-instance |

### cloud_config_modules

| Module | Frequency |
| --- | --- |
| `wireguard` | once-per-instance |
| `snap` | once-per-instance |
| `ubuntu_autoinstall` | once |
| `ssh_import_id` | once-per-instance |
| `keyboard` | once-per-instance |
| `locale` | once-per-instance |
| `grub_dpkg` | once-per-instance |
| `apt_pipelining` | once-per-instance |
| `apt_configure` | once-per-instance |
| `ubuntu_pro` | once-per-instance |
| `ntp` | once-per-instance |
| `timezone` | once-per-instance |
| `disable_ec2_metadata` | always |
| `runcmd` | once-per-instance |
| `byobu` | once-per-instance |

### cloud_final_modules

| Module | Frequency |
| --- | --- |
| `package_update_upgrade_install` | once-per-instance |
| `fan` | once-per-instance |
| `landscape` | once-per-instance |
| `lxd` | once-per-instance |
| `ubuntu_drivers` | once-per-instance |
| `write_files_deferred` | once-per-instance |
| `puppet` | once-per-instance |
| `chef` | always |
| `ansible` | once-per-instance |
| `mcollective` | once-per-instance |
| `salt_minion` | once-per-instance |
| `reset_rmc` | once-per-instance |
| `scripts_vendor` | once-per-instance |
| `scripts_per_once` | once |
| `scripts_per_boot` | always |
| `scripts_per_instance` | once-per-instance |
| `scripts_user` | once-per-instance |
| `ssh_authkey_fingerprints` | once-per-instance |
| `keys_to_console` | once-per-instance |
| `install_hotplug` | once-per-instance |
| `phone_home` | once-per-instance |
| `final_message` | always |
| `power_state_change` | once-per-instance |

## Verification

The final deployed profile is
`/nix/store/d42g6s6s1jzrlr789456bhbfw0y9b3fw-system-manager`.
All eight native files match their original backup hashes and permissions and
are regular files outside Nix ownership. The cloud-init override is absent.
Effective cloud-init configuration restores Oracle's localhost handling and
native hostname, network and APT ownership. Custom overlays remain declared.
Nine local regression tests passed.

The package cleanup and preceding deployment passed public/Tailscale SSH, DNS,
eleven application endpoints and public Forgejo/Pocket ID HTTPS checks.
Application packages and units did not change. Reboot behavior and a full CIS
audit were not exercised. The ownership restoration is verified separately
against hashes of the original native backups and the built profile inventory.
