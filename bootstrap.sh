#!/bin/sh
set -eu

ssh -- "$1" 'sudo -n sh -se' <<'REMOTE'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates nix-bin nix-setup-systemd uidmap unattended-upgrades \
  apparmor python3 curl
usermod -aG nix-users "$SUDO_USER"
if [ ! -L /etc/nix/homelab.conf ]; then
  printf 'extra-experimental-features = nix-command flakes\nextra-trusted-users = %s\n' \
    "$SUDO_USER" > /etc/nix/homelab.conf
  chmod 0644 /etc/nix/homelab.conf
fi
grep -qxF '!include /etc/nix/homelab.conf' /etc/nix/nix.conf || \
  printf '%s\n' '!include /etc/nix/homelab.conf' >> /etc/nix/nix.conf
systemctl enable nix-daemon.service
systemctl restart nix-daemon.service
REMOTE
