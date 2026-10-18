# Shared systemd serviceConfig defaults for unprivileged applications.
# Import this attribute set into a unit; it creates no service by itself.
# Units must separately declare users, writable state paths and network policy.
{
  # Block privilege gains through exec, including setuid programs and file capabilities.
  NoNewPrivileges = true;
  # Remove all Linux capabilities; a unit needing one must explicitly override this.
  CapabilityBoundingSet = "";
  # Make the filesystem read-only, except systemd-managed state and explicit exceptions.
  ProtectSystem = "strict";
  # Hide /home, /root and /run/user from the service.
  ProtectHome = true;
  # Give the service private /tmp and /var/tmp directories.
  PrivateTmp = true;
  # Expose a minimal /dev without access to host physical devices.
  PrivateDevices = true;
  # Prevent writes to kernel settings such as /proc/sys.
  ProtectKernelTunables = true;
  # Prevent loading or unloading kernel modules.
  ProtectKernelModules = true;
  # Make the cgroup hierarchy read-only inside the service.
  ProtectControlGroups = true;
  # Prevent creating files with setuid or setgid permission bits.
  RestrictSUIDSGID = true;
  # Remove group/other permissions from newly created files and directories.
  UMask = "0077";
}
