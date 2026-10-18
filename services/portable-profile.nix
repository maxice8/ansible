# Keep hardening in each image unit; expose only DNS, machine identity and logging.
''
  [Service]
  MountAPIVFS=yes
  BindLogSockets=yes
  BindReadOnlyPaths=/etc/machine-id
  BindReadOnlyPaths=/etc/resolv.conf
''
