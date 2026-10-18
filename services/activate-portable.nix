# Deployment-time attachment; persistent units are started by host systemd at boot.
{ pkgs, name, image, healthURL }:
pkgs.writeShellScript "activate-portable-${name}" ''
  set -euo pipefail
  state=$(/usr/bin/portablectl is-attached '${image}/${name}.raw')
  action=attach
  # is-attached exits successfully even when its reported state is detached.
  if [ "$state" != detached ]; then
    action=reattach
  fi
  /usr/bin/portablectl "$action" --profile=mashu --now '${image}/${name}.raw'
  /usr/bin/systemctl enable ${name}.service
  # A listener can open before its health route is registered (brief HTTP 404).
  /usr/bin/curl --fail --silent --show-error --retry 10 --retry-all-errors --retry-delay 1 \
    --retry-connrefused --max-time 5 '${healthURL}'
''
