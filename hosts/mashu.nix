# Configure Mashu's services on ARM64 Ubuntu.
# Keep application and CI identities separate.
{ ... }: {
  imports = [
    ../services/base.nix
    ../services/unbound
    ../services/app-users.nix
  ];
  nixpkgs.hostPlatform = "aarch64-linux";
}
