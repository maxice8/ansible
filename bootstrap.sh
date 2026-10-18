#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 && -n $1 && $1 != -* ]] || {
  printf 'Usage: %s SSH_TARGET\n' "$0" >&2
  exit 2
}

ssh -- "$1" 'sudo -n bash -seuo pipefail' <<'REMOTE'
  . /etc/os-release
  [[ $ID:$VERSION_ID == ubuntu:26.04 && $SUDO_USER =~ ^[a-z_][a-z0-9_-]*$ ]]

  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates nix-bin nix-setup-systemd \
    uidmap unattended-upgrades

  usermod -aG nix-users "$SUDO_USER"
  printf 'extra-experimental-features = nix-command flakes\nextra-trusted-users = %s\n' \
    "$SUDO_USER" > /etc/nix/homelab.conf
  chmod 0644 /etc/nix/homelab.conf

  sed -i '\|^!include /etc/nix/homelab\.conf$|d' /etc/nix/nix.conf
  printf '%s\n' '!include /etc/nix/homelab.conf' >> /etc/nix/nix.conf

  systemctl enable nix-daemon.service
  systemctl restart nix-daemon.service
REMOTE
