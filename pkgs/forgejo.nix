# Same-version upstream binary with embedded assets; hashes pin the official release.
{
  lib,
  stdenvNoCC,
  fetchurl,
}:
let
  releases = {
    aarch64-linux = {
      arch = "arm64";
      sha256 = "e5ec437cd6357e8d1b4580cb47ab1daa58a32b33971a63db63446a535d33adb7";
    };
    x86_64-linux = {
      arch = "amd64";
      sha256 = "5a3b07e124ed70b4e46ee3939515f003bd3cc85352257a9a4607a527251042ca";
    };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation rec {
  pname = "forgejo";
  version = "17.0.0";
  src = fetchurl {
    url = "https://code.forgejo.org/forgejo/forgejo/releases/download/v${version}/forgejo-${version}-linux-${release.arch}";
    inherit (release) sha256;
  };
  dontUnpack = true;
  dontStrip = true;
  installPhase = ''install -Dm755 "$src" "$out/bin/forgejo"'';
  meta = {
    license = lib.licenses.gpl3Plus;
    platforms = builtins.attrNames releases;
    mainProgram = "forgejo";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
