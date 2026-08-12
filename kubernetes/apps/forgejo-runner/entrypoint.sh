#!/bin/sh
set -eu
cd /data

until nc -z 127.0.0.1 2375; do
  sleep 1
done

if [ ! -f .runner ]; then
  forgejo-runner register --no-interactive \
    --instance "$FORGEJO_INSTANCE_URL" \
    --token "$FORGEJO_RUNNER_TOKEN" \
    --name "forgejo-runner-mashu"
fi

exec forgejo-runner daemon --config /etc/forgejo-runner/config.yml
