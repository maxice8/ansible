# Share host DNS, machine identity and logging with each service image.
{
  # Mount /proc, /sys and /dev inside the image.
  MountAPIVFS = true;
  # Connect the image to the host journal sockets.
  BindLogSockets = true;
  BindReadOnlyPaths = [
    "/etc/machine-id"
    "/etc/homelab/resolv.conf:/etc/resolv.conf"
  ];
}
