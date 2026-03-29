FROM docker.io/library/alpine:latest

# ADDED ca-certificates here
RUN apk add --no-cache borgbackup openssh-client python3 pipx tzdata ca-certificates

# Install borgmatic with the Apprise Discord integration
RUN pipx install --global borgmatic[apprise]

ENTRYPOINT ["borgmatic"]