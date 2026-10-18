# Mashu's final host configuration: compose native services on ARM64 Ubuntu.
# The remaining OCI fork and CI engine use separate rootless identities.
{ ... }: {
  imports = [
    ../services/base.nix
    ../services/tailscale.nix
    ../services/host-policy.nix
    ../services/traefik.nix
    ../services/pomerium.nix
    ../services/syncthing.nix
    ../services/pocket-id.nix
    ../services/app-users.nix
    ../services/rootless-containers.nix
    ../services/forgejo.nix
    ../services/argus.nix
    ../services/pingvin-share.nix
    ../services/archisteamfarm.nix
    ../services/netdata.nix
    ../services/forgejo-runner.nix
    ../services/backrest.nix
  ];
  nixpkgs.hostPlatform = "aarch64-linux";
}
