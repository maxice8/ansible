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
      sha256 = "1e99403746406e8199efc903ddd1940d5728a60e50241f7aa6c9f2b907bd8ec9";
    };
    x86_64-linux = {
      arch = "amd64";
      sha256 = "51a8cdf4a1252e79f4b3855d7a7891af6c6635105420768c460e2f0690385d6f";
    };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation rec {
  pname = "forgejo";
  version = "17.0.1";
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
