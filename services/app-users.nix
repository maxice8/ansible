# Create service accounts and reserve their user and group IDs.
# Keep ordinary Ubuntu accounts outside IDs 5000-5999.
{ lib, pkgs, ... }:
let
  ids = {
    forgejo = 5005;
    argus = 5007;
    archisteamfarm = 5013;
    netdata = 5011;
    forgejo-runner = 5012;
    backrest = 5008;
    runner-engine = 5009;
    pingvin-share = 5006;
    unbound = 5010;
  };
  ranges = {
    runner-engine = 500000;
    pingvin-share = 600000;
  };
in
{
  services.userborn.enable = lib.mkForce true;
  users.users = lib.mkForce (
    lib.mapAttrs (
      name: uid:
      {
        isSystemUser = true;
        inherit uid;
        # uidmap requires the process's primary GID to match passwd; share only the API group.
        group = if name == "runner-engine" then "forgejo-runner" else name;
        shell = "/usr/sbin/nologin";
      }
      // lib.optionalAttrs (builtins.hasAttr name ranges) {
        home = "/var/cache/${name}";
        subUidRanges = [
          {
            startUid = ranges.${name};
            count = 65536;
          }
        ];
        subGidRanges = [
          {
            startGid = ranges.${name};
            count = 65536;
          }
        ];
      }
    ) ids
  );
  users.groups = lib.mkForce (lib.mapAttrs (_: gid: { inherit gid; }) ids);
  system-manager.preActivationAssertions.applicationIdentities = {
    enable = true;
    script = ''
      ${pkgs.python3}/bin/python3 - <<'PY'
      import grp
      import json
      import pwd
      from pathlib import Path

      ids = json.loads('${builtins.toJSON ids}')
      for name, number in ids.items():
          for lookup, byname in [(pwd.getpwuid, pwd.getpwnam), (grp.getgrgid, grp.getgrnam)]:
              try:
                  assert lookup(number)[0] == name, "Account ID collision: " + name
              except KeyError:
                  pass
              try:
                  assert byname(name)[2] == number, "Account name collision: " + name
              except KeyError:
                  pass
      ranges = json.loads('${builtins.toJSON ranges}')
      for database in ["/etc/subuid", "/etc/subgid"]:
          path = Path(database)
          for line in path.read_text().splitlines() if path.exists() else []:
              owner, start, count = line.split(":")
              start = int(start)
              count = int(count)
              for name, target in ranges.items():
                  assert (
                      start + count <= target
                      or start >= target + 65536
                      or (owner == name and start == target and count == 65536)
                  ), "Subordinate ID overlap"
      PY
    '';
  };
}
