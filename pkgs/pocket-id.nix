# Official Pocket ID binary, including its embedded web UI; keep the deployed schema version.
# Checksums are pinned from the upstream v2.18.0 release manifest.
{ lib, stdenvNoCC, fetchurl }:
let
  releases = {
    aarch64-linux = { arch = "arm64"; sha256 = "a54762523208ad52aecfd110afc54c076dad92ea97522bff6a556cfc338adb0d"; };
    x86_64-linux = { arch = "amd64"; sha256 = "92800e76b826a6b05e6ba6350c4b1206106ad8e4066054166b0b1a956de6f542"; };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in stdenvNoCC.mkDerivation rec {
  pname = "pocket-id";
  version = "2.18.0";
  src = fetchurl {
    url = "https://github.com/pocket-id/pocket-id/releases/download/v${version}/pocket-id_linux_${release.arch}";
    inherit (release) sha256;
  };
  dontUnpack = true;
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 "$src" "$out/bin/pocket-id"
    runHook postInstall
  '';
  meta = {
    description = "Pocket ID passkey-based OpenID Connect provider";
    homepage = "https://pocket-id.org/";
    license = lib.licenses.bsd2;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    platforms = builtins.attrNames releases;
    mainProgram = "pocket-id";
  };
}
