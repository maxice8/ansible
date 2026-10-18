# Entry point for Mashu's deployment configuration and local build tools.
# flake.lock fixes the exact input revisions used to reproduce builds.
{
  description = "Mashu's Ubuntu systemd services, built and deployed with Nix";

  inputs = {
    system-manager.url = "github:numtide/system-manager/c397860e511383fe554ccd2b8366ee34fc88cff4";
    # Share System Manager's Nixpkgs revision rather than resolving a second copy.
    nixpkgs.follows = "system-manager/nixpkgs";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  # @ keeps the whole inputs set while also naming the two inputs used below.
  outputs = inputs@{ nixpkgs, system-manager, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      # Partially apply genAttrs: the callback below supplies each platform's value.
      forSystems = nixpkgs.lib.genAttrs systems;
    in {
      # Guest packages are ARM-native for cache reuse; only the VM runner is x86.
      nixosConfigurations.builder = nixpkgs.lib.nixosSystem {
        system = "aarch64-linux";
        specialArgs.hostPkgs = nixpkgs.legacyPackages.x86_64-linux;
        modules = [ ./tests/builder.nix ];
      };

      systemConfigs.mashu = system-manager.lib.makeSystemConfig {
        # Pass inputs to our modules; `inherit inputs` is shorthand for inputs = inputs.
        specialArgs = { inherit inputs; };
        modules = [ ./hosts/mashu.nix ];
      };

      packages = forSystems (system:
        # ${system} selects an attribute by platform name rather than a literal key.
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          system-manager = system-manager.packages.${system}.default;
          argus-canary = import ./services/argus/canary.nix { inherit pkgs; };
        } // nixpkgs.lib.optionalAttrs (system == "x86_64-linux") {
          vm-image = inputs.self.nixosConfigurations.builder.config.system.build.vm;
        });
    };
}
