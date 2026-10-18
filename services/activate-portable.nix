# Deployment-time attachment; persistent units are started by host systemd at boot.
{ pkgs, name, image, healthURL }:
pkgs.writeShellScript "activate-portable-${name}" ''
  set -euo pipefail
  state=$(/usr/bin/portablectl is-attached '${image}/${name}.raw')
  # is-attached exits successfully even when its reported state is detached.
  if [ "$state" = detached ]; then
    /usr/bin/portablectl attach --profile=mashu --now '${image}/${name}.raw'
  elif [ "$(/usr/bin/systemctl show ${name}.service -p RootImage --value)" != '${image}/${name}.raw' ] \
    || [ "$(/usr/bin/systemctl show ${name}.service -p FragmentPath --value)" != '/etc/systemd/system.attached/${name}.service' ] \
    || ! /usr/bin/cmp -s /etc/systemd/portable/profile/mashu/service.conf \
      /etc/systemd/system.attached/${name}.service.d/10-profile.conf; then
    # A profile change needs reattachment even when the image itself is unchanged.
    /usr/bin/portablectl reattach --profile=mashu --now '${image}/${name}.raw'
  fi
  # Wait for the queued restart, including graceful shutdown, before probing health.
  /usr/bin/systemctl enable --now ${name}.service
  # Cold runtimes and late route registration can outlast the systemd start job.
  /usr/bin/curl --fail --silent --show-error --retry 60 --retry-max-time 60 --retry-all-errors --retry-delay 1 \
    --retry-connrefused --max-time 5 '${healthURL}'
''
