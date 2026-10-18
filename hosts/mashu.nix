# Mashu's final host configuration: compose native services on ARM64 Ubuntu.
# The remaining OCI fork and CI engine use separate rootless identities.
{ ... }: {
  imports = [
    ../services/base.nix
    ../services/tailscale
    ../services/host-policy.nix
    ../services/unbound
    ../services/application-dns.nix
    ../services/traefik
    ../services/pomerium
    ../services/syncthing
    ../services/pocket-id
    ../services/app-users.nix
    ../services/rootless-containers.nix
    ../services/forgejo
  ];
  nixpkgs.hostPlatform = "aarch64-linux";
}
