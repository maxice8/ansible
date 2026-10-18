# Preserve Mashu's Pomerium/embedded Envoy version using verified upstream binaries.
# The checksum manifest belongs to the official v0.33.4 release.
{ lib, stdenvNoCC, fetchurl }:
let
  releases = {
    aarch64-linux = { arch = "arm64"; sha256 = "bfd59855cc1878ce4e90e66143d6f13997679c115eb4d63df751ddffd50d95a7"; };
    x86_64-linux = { arch = "amd64"; sha256 = "bb792f52bc07226497c5be67a1373476d3fdbd40064e3a2d47ca65b05dfdd0df"; };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in stdenvNoCC.mkDerivation rec {
  pname = "pomerium";
  version = "0.33.4";
  src = fetchurl {
    url = "https://github.com/pomerium/pomerium/releases/download/v${version}/pomerium-linux-${release.arch}.tar.gz";
    inherit (release) sha256;
  };
  sourceRoot = ".";
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 pomerium "$out/bin/pomerium"
    runHook postInstall
  '';
  meta = {
    description = "Pomerium authentication proxy with its matching embedded Envoy";
    homepage = "https://www.pomerium.com/";
    license = lib.licenses.asl20;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    platforms = builtins.attrNames releases;
    mainProgram = "pomerium";
  };
}
