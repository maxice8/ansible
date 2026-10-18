# Keep the existing device/database version using the official release archives.
# Hashes come from the upstream signed v2.1.6 checksum manifest.
{ lib, stdenvNoCC, fetchurl }:
let
  releases = {
    aarch64-linux = { arch = "arm64"; sha256 = "f054de02462d5d58bd126908f2f92b63aba74f162a5be85e50e96d656e7db47d"; };
    x86_64-linux = { arch = "amd64"; sha256 = "524ef4e1df1850b719e2378c8369956f4e5f2ab9a46fdf7f45f2b925012147aa"; };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in stdenvNoCC.mkDerivation rec {
  pname = "syncthing";
  version = "2.1.6";
  src = fetchurl {
    url = "https://github.com/syncthing/syncthing/releases/download/v${version}/syncthing-linux-${release.arch}-v${version}.tar.gz";
    inherit (release) sha256;
  };
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 syncthing "$out/bin/syncthing"
    runHook postInstall
  '';
  meta = {
    description = "Syncthing continuous file synchronization";
    homepage = "https://syncthing.net/";
    license = lib.licenses.mpl20;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    platforms = builtins.attrNames releases;
    mainProgram = "syncthing";
  };
}
