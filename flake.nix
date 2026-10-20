# Entry point for Mashu's deployment configuration and local build tools.
# flake.lock fixes the exact input revisions used to reproduce builds.
{
  description = "Mashu's Ubuntu systemd services, built and deployed with Nix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    system-manager = {
      url = "github:numtide/system-manager";
      # Use the same package set for services and deployment tools.
      inputs.nixpkgs.follows = "nixpkgs";
    };
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  # @ keeps the whole inputs set while also naming the two inputs used below.
  outputs =
    inputs@{ nixpkgs, system-manager, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      # Partially apply genAttrs: the callback below supplies each platform's value.
      forSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      systemConfigs.mashu = system-manager.lib.makeSystemConfig {
        # Pass inputs to our modules; `inherit inputs` is shorthand for inputs = inputs.
        specialArgs = { inherit inputs; };
        modules = [ ./hosts/mashu.nix ];
      };

      formatter = forSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);

      packages = forSystems (
        system:
        # ${system} selects an attribute by platform name rather than a literal key.
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          pingvin-share = pkgs.callPackage ./pkgs/pingvin-share.nix { };
        }
      );
    };
}
