# Package the official Traefik release at Mashu's existing security patch level.
# These archive hashes come from the upstream v3.7.15 checksum manifest.
{
  lib,
  stdenvNoCC,
  fetchurl,
}:
let
  releases = {
    aarch64-linux = {
      arch = "arm64";
      sha256 = "1866d8e831b95d14b599bb59eb20d2033b979c0cb1e347b48a0866a9b810454e";
    };
    x86_64-linux = {
      arch = "amd64";
      sha256 = "5b9f51199fcb7a3b5f7ae0f9dae8dcf01efadafd92c5fca96ea2822eca81f8e6";
    };
  };
  # Select the binary for the machine that will run it, not the evaluation host.
  release = releases.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation rec {
  pname = "traefik";
  version = "3.7.15";
  src = fetchurl {
    url = "https://github.com/traefik/traefik/releases/download/v${version}/traefik_v${version}_linux_${release.arch}.tar.gz";
    inherit (release) sha256;
  };
  sourceRoot = ".";
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 traefik "$out/bin/traefik"
    runHook postInstall
  '';
  meta = {
    description = "Traefik reverse proxy from the verified upstream release";
    homepage = "https://traefik.io/traefik/";
    license = lib.licenses.mit;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    platforms = builtins.attrNames releases;
    mainProgram = "traefik";
  };
}
