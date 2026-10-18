# Keep hardening in the image unit; expose only DNS, machine identity and logging.
''
  [Service]
  MountAPIVFS=yes
  BindLogSockets=yes
  BindReadOnlyPaths=/etc/machine-id
  BindReadOnlyPaths=/etc/resolv.conf
''
