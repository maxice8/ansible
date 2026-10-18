# Mashu: Ubuntu + Nix

Ubuntu supplies the kernel, networking, OpenSSH and Nix daemon.
The pinned Nix flake describes Mashu using System Manager.
Service state lives under `/var/lib/data/<service>`; caches are disposable.

## Bootstrap

Use an independent, key-only SSH connection to an Ubuntu 26.04 ARM64 host:

```sh
./bootstrap.sh mashu-admin
```

The host must provide systemd 259+ and cgroup v2. Keep recovery SSH22 available.
Never copy local age identities into the Nix store.

## Configuration

`hosts/mashu.nix` composes these service modules:

- `unbound`

Each module declares its service configuration and credential requirements.
