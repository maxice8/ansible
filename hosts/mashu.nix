# Configure Mashu's services on ARM64 Ubuntu.
# Keep application and CI identities separate.
{ ... }: {
  imports = [
    ../services/base.nix
    ../services/tailscale
    ../services/host-policy.nix
    ../services/unbound
    ../services/application-dns.nix
    ../services/traefik
    ../services/pocket-id
    ../services/app-users.nix
  ];
  nixpkgs.hostPlatform = "aarch64-linux";
}
