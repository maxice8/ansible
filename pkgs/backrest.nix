# Official Backrest with embedded UI, using Nix's restic and SSH rather than self-downloads.
{ lib, stdenvNoCC, fetchurl, makeWrapper, restic, openssh }:
let
  releases = {
    aarch64-linux = { arch = "arm64"; sha256 = "b53718cd6e042e7d99538cb652968ab966a5c53fabd556785648ceb13320a320"; };
    x86_64-linux = { arch = "x86_64"; sha256 = "acc7835a9c55b3d254f0fa285cacbe87ac912cb7e069d0211924838020e6921c"; };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in stdenvNoCC.mkDerivation rec {
  pname = "backrest"; version = "1.14.1";
  src = fetchurl {
    url = "https://github.com/garethgeorge/backrest/releases/download/v${version}/backrest_Linux_${release.arch}.tar.gz";
    inherit (release) sha256;
  };
  sourceRoot = "."; dontStrip = true;
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    install -Dm755 backrest "$out/bin/backrest"
    wrapProgram "$out/bin/backrest" \
      --set BACKREST_RESTIC_COMMAND ${restic}/bin/restic \
      --prefix PATH : ${lib.makeBinPath [ restic openssh ]}
  '';
  meta = { license = lib.licenses.gpl3Only; platforms = builtins.attrNames releases;
    mainProgram = "backrest"; sourceProvenance = [ lib.sourceTypes.binaryNativeCode ]; };
}
