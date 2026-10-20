# Run a Nix-built service image with a systemd unit on the host.
# System Manager starts the unit and restarts it when its configuration changes.
{
  name,
  image,
  settings,
}:
{
  wantedBy = [ settings.Install.WantedBy ];
  unitConfig = settings.Unit // {
    After = settings.Unit.After ++ [ "unbound.service" ];
    Wants = (settings.Unit.Wants or [ ]) ++ [ "unbound.service" ];
  };
  serviceConfig = settings.Service // {
    RootImage = "${image}/${name}_${image.version}.raw";
    # Mount /proc, /sys and /dev inside the image.
    MountAPIVFS = true;
    # Connect the image to the host journal sockets.
    BindLogSockets = true;
    BindReadOnlyPaths = [
      "/etc/machine-id"
      "/etc/homelab/resolv.conf:/etc/resolv.conf"
    ];
  };
}
