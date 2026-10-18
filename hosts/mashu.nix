# Mashu's final host configuration: compose native services on ARM64 Ubuntu.
# The remaining OCI fork and CI engine use separate rootless identities.
{ ... }: {
  imports = [
    ../services/base.nix
    ../services/unbound
    ../services/app-users.nix
  ];
  nixpkgs.hostPlatform = "aarch64-linux";
}
