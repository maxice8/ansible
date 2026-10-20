# Build Pingvin's servers and the Prisma engines required by its lock file.
{
  lib,
  stdenv,
  buildNpmPackage,
  fetchFromGitHub,
  fetchurl,
  runCommand,
  autoPatchelfHook,
  nodejs_24,
  node-gyp,
  pkg-config,
  vips,
  openssl,
  zlib,
  python3,
  makeWrapper,
}:
let
  version = "1.22.4";
  prismaVersion = "6.6.0";
  engineRev = "f676762280b54cd07c770017ed3711ddde35f37a";
  backendNpmDepsHash = "sha256-ELbC/tS4Ug2nc221220/incyFKIjlUGlVF03WqcVpe0=";
  frontendNpmDepsHash = "sha256-9dZCrG2GRxDRTH7oXpQ+tXGxOptQbyT73Mj0HG4U9JY=";
  src = fetchFromGitHub {
    owner = "smp46";
    repo = "pingvin-share-x";
    rev = "2152bdcafaa85d936c5f59fd3465b35cdb562387";
    hash = "sha256-gB09NRomMyiJSuIRUgR2JsDqixs7TOvDpCi7x89i0+I=";
  };
  # Select binaries for the service's CPU, not the workstation's CPU.
  engineRelease =
    {
      x86_64-linux = {
        platform = "debian-openssl-3.0.x";
        query = "sha256-PeZ1cfNzzlVGy8y6mqpeXWj7KCPQmaW+5EzsVcX+XG0=";
        schema = "sha256-58Dw7bZGxQ9jeWU6yeBl+BZQagke1079cIAHvYL01Cg=";
      };
      aarch64-linux = {
        platform = "linux-arm64-openssl-3.0.x";
        query = "sha256-q4xDv7ty1MKOIq6+yZCQwq/lc1oBbxlBHJbw64Luz+g=";
        schema = "sha256-zrDLE2Bdq6F6yIb9w1PeHNK5sx6JMHz6Ui3cJyJjR98=";
      };
    }
    .${stdenv.hostPlatform.system};
  fetchEngine =
    name: hash:
    fetchurl {
      url = "https://binaries.prisma.sh/all_commits/${engineRev}/${engineRelease.platform}/${name}.gz";
      inherit hash;
    };
  engines =
    runCommand "pingvin-prisma-engines-${prismaVersion}"
      {
        nativeBuildInputs = [ autoPatchelfHook ];
        buildInputs = [
          openssl
          zlib
          stdenv.cc.cc.lib
        ];
      }
      ''
        mkdir -p $out/bin $out/lib
        gunzip -c ${fetchEngine "schema-engine" engineRelease.schema} > $out/bin/schema-engine
        gunzip -c ${fetchEngine "libquery_engine.so.node" engineRelease.query} > $out/lib/libquery_engine.node
        chmod +x $out/bin/schema-engine
        # runCommand does not run the standard fixup phase.
        autoPatchelf $out
      '';
  prismaEnvironment = {
    PRISMA_SCHEMA_ENGINE_BINARY = "${engines}/bin/schema-engine";
    PRISMA_QUERY_ENGINE_LIBRARY = "${engines}/lib/libquery_engine.node";
    PRISMA_ENGINES_CHECKSUM_IGNORE_MISSING = "1";
    PRISMA_SKIP_POSTINSTALL_GENERATE = "1";
  };
  backend = buildNpmPackage {
    pname = "pingvin-share-backend";
    inherit version src;
    sourceRoot = "source/backend";
    nodejs = nodejs_24;
    npmDepsHash = backendNpmDepsHash;
    nativeBuildInputs = [
      autoPatchelfHook
      python3
      node-gyp
      pkg-config
    ];
    buildInputs = [
      openssl
      zlib
      stdenv.cc.cc.lib
      vips
    ];
    env = prismaEnvironment // {
      SHARP_FORCE_GLOBAL_LIBVIPS = "1";
      npm_config_nodedir = "${nodejs_24}";
    };
    postPatch = ''
      substituteInPlace src/main.ts \
        --replace-fail 'parseInt(process.env.BACKEND_PORT || process.env.PORT || "8080"),' \
          'parseInt(process.env.BACKEND_PORT || process.env.PORT || "8080"), process.env.BACKEND_HOST || "127.0.0.1",'
      substituteInPlace src/config/logo.service.ts \
        --replace-fail 'const IMAGES_PATH = "../frontend/public/img";' \
          'const IMAGES_PATH = process.env.IMAGES_DIRECTORY || "../frontend/public/img";'
    '';
    preBuild = ''
      (cd node_modules/sharp && node-gyp rebuild --directory=src)
      rm -rf node_modules/@img/sharp-*
      node_modules/.bin/prisma generate
    '';
    postBuild = ''
      node_modules/.bin/tsc prisma/seed/config.seed.ts --outDir dist/prisma/seed --rootDir prisma/seed
      npm prune --omit=dev --ignore-scripts
      rm -rf node_modules/@img/sharp-*
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p $out
      cp -r dist prisma node_modules package.json $out/
      cp ../LICENSE $out/LICENSE
      runHook postInstall
    '';
    # Ubuntu uses glibc. Remove unused musl binaries before dependency repair.
    preFixup = ''
      find $out -type f -name '*.musl.node' -delete
    '';
  };
  frontend = buildNpmPackage {
    pname = "pingvin-share-frontend";
    inherit version src;
    sourceRoot = "source/frontend";
    nodejs = nodejs_24;
    npmDepsHash = frontendNpmDepsHash;
    nativeBuildInputs = [
      autoPatchelfHook
      python3
      node-gyp
      pkg-config
    ];
    buildInputs = [
      stdenv.cc.cc.lib
      vips
    ];
    env = {
      NEXT_TELEMETRY_DISABLED = "1";
      API_URL = "http://127.0.0.1:3002";
      SHARP_FORCE_GLOBAL_LIBVIPS = "1";
      npm_config_nodedir = "${nodejs_24}";
    };
    preBuild = ''
      # Reuse the header dependency from the backend's lock file.
      ln -s ${backend}/node_modules/node-addon-api node_modules/node-addon-api
      (cd node_modules/sharp && node-gyp rebuild --directory=src)
      rm -rf node_modules/@img/sharp-* node_modules/node-addon-api
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p $out/.next/cache
      cp -r .next/standalone/. $out/
      cp -r .next/static $out/.next/static
      cp -r public $out/public
      cp ../LICENSE $out/LICENSE
      runHook postInstall
    '';
  };
in
runCommand "pingvin-share-${version}"
  {
    nativeBuildInputs = [ makeWrapper ];
    passthru = {
      inherit
        version
        backend
        frontend
        engines
        ;
    };
    meta = {
      description = "File sharing with a NestJS backend and Next.js frontend";
      homepage = "https://github.com/smp46/pingvin-share-x";
      license = lib.licenses.bsd2;
      platforms = [
        "x86_64-linux"
        "aarch64-linux"
      ];
    };
  }
  ''
    mkdir -p $out/bin
    ln -s ${backend} $out/backend
    ln -s ${frontend} $out/frontend
    makeWrapper ${nodejs_24}/bin/node $out/bin/pingvin-share-backend \
      --add-flags ${backend}/dist/src/main.js \
      --set PRISMA_QUERY_ENGINE_LIBRARY ${engines}/lib/libquery_engine.node
    makeWrapper ${nodejs_24}/bin/node $out/bin/pingvin-share-migrate \
      --add-flags '${backend}/node_modules/prisma/build/index.js migrate deploy --schema ${backend}/prisma/schema.prisma' \
      --set PRISMA_SCHEMA_ENGINE_BINARY ${engines}/bin/schema-engine \
      --set PRISMA_QUERY_ENGINE_LIBRARY ${engines}/lib/libquery_engine.node
    makeWrapper ${nodejs_24}/bin/node $out/bin/pingvin-share-seed \
      --add-flags ${backend}/dist/prisma/seed/config.seed.js \
      --set PRISMA_QUERY_ENGINE_LIBRARY ${engines}/lib/libquery_engine.node
    makeWrapper ${nodejs_24}/bin/node $out/bin/pingvin-share-frontend \
      --add-flags ${frontend}/server.js \
      --set NEXT_TELEMETRY_DISABLED 1
  ''
