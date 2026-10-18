# Configure Mashu's services on ARM64 Ubuntu.
# Run Pingvin and CI jobs with separate rootless identities.
{ ... }: {
  imports = [
    ../services/base.nix
    ../services/unbound
    ../services/app-users.nix
  ];
  nixpkgs.hostPlatform = "aarch64-linux";
}
