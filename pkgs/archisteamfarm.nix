# The official generic release includes managed .NET assemblies, plugins and the web UI.
# Use Nix's .NET runtime instead of downloading a mutable runtime alongside the service.
{
  lib,
  stdenvNoCC,
  fetchurl,
  unzip,
  makeWrapper,
  dotnetCorePackages,
  libkrb5,
  zlib,
  openssl,
}:
stdenvNoCC.mkDerivation rec {
  pname = "archisteamfarm";
  version = "6.3.11.7";
  src = fetchurl {
    url = "https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/${version}/ASF-generic.zip";
    sha256 = "cb3ddb9bd10560458a460664c9af6186e124e89801d118197a82eef5a9315ceb";
  };
  dontUnpack = true;
  nativeBuildInputs = [
    unzip
    makeWrapper
  ];
  installPhase = ''
    mkdir -p "$out/lib/ASF" "$out/bin"
    unzip -q "$src" -d "$out/lib/ASF"
    makeWrapper ${dotnetCorePackages.aspnetcore_10_0}/bin/dotnet "$out/bin/ArchiSteamFarm" \
      --add-flags "$out/lib/ASF/ArchiSteamFarm.dll" \
      --prefix LD_LIBRARY_PATH : "${
        lib.makeLibraryPath [
          libkrb5
          zlib
          openssl
        ]
      }"
  '';
  meta = {
    license = lib.licenses.asl20;
    mainProgram = "ArchiSteamFarm";
    platforms = lib.platforms.linux;
    sourceProvenance = [ lib.sourceTypes.binaryBytecode ];
  };
}
