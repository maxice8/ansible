# Keep the existing node's daemon version while moving executable ownership to Nix.
# Checksums are published beside the official static archives, with a .sha256 suffix.
{ lib, stdenvNoCC, fetchurl }:
let
  releases = {
    aarch64-linux = { arch = "arm64"; sha256 = "f60294374967f3dfd8cf57bbbd474d6cfce32d123e3a8ddeab82a87940daa806"; };
    x86_64-linux = { arch = "amd64"; sha256 = "108d1d96ecf410d305571e173516f27038f870919a9b89c914a167c6d33a4528"; };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in stdenvNoCC.mkDerivation rec {
  pname = "tailscale";
  version = "1.104.1";
  src = fetchurl {
    url = "https://pkgs.tailscale.com/stable/tailscale_${version}_${release.arch}.tgz";
    inherit (release) sha256;
  };
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 tailscale "$out/bin/tailscale"
    install -Dm755 tailscaled "$out/bin/tailscaled"
    runHook postInstall
  '';
  meta = {
    description = "Tailscale encrypted overlay networking and SSH";
    homepage = "https://tailscale.com/";
    license = lib.licenses.bsd3;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    platforms = builtins.attrNames releases;
  };
}
