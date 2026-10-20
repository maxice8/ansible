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
      sha256 = "1bd4c0c8dfe453e9c88e5ba9fc4cac755422b66a53ddf75e7e1128f0ee1f5bc8";
    };
    x86_64-linux = {
      arch = "amd64";
      sha256 = "afa4011b0d30260908cdf3f5461b4ac7234dd4c01abe60ae1baf8ea4b8b80c96";
    };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation rec {
  pname = "release-argus";
  version = "0.39.0";
  src = fetchurl {
    url = "https://github.com/release-argus/Argus/releases/download/${version}/Argus-${version}.linux-${release.arch}";
    inherit (release) sha256;
  };
  dontUnpack = true;
  dontStrip = true;
  installPhase = ''install -Dm755 "$src" "$out/bin/argus"'';
  meta = {
    license = lib.licenses.asl20;
    platforms = builtins.attrNames releases;
    mainProgram = "argus";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
