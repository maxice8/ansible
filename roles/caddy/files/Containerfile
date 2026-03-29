# Stage 1: Build Caddy with the CrowdSec plugin
FROM docker.io/library/caddy:builder AS builder

RUN xcaddy build \
    --with github.com/hslatman/caddy-crowdsec-bouncer

# Stage 2: Create the final image
FROM docker.io/library/caddy:latest

COPY --from=builder /usr/bin/caddy /usr/bin/caddy