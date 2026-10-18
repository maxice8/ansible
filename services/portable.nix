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
  serviceConfig =
    settings.Service
    // import ./portable-profile.nix
    // {
      RootImage = "${image}/${name}_${image.version}.raw";
    };
}
