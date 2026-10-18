# Keep hardening in each image unit; expose only DNS, machine identity and logging.
''
  [Unit]
  Wants=unbound.service
  After=unbound.service

  [Service]
  MountAPIVFS=yes
  BindLogSockets=yes
  BindReadOnlyPaths=/etc/machine-id
  BindReadOnlyPaths=/etc/homelab/resolv.conf:/etc/resolv.conf
''
