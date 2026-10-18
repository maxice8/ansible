# Configure Mashu's services on ARM64 Ubuntu.
# Run Pingvin and CI jobs with separate rootless identities.
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
    ../services/rootless-containers.nix
  ];
  nixpkgs.hostPlatform = "aarch64-linux";
}
