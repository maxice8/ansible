FROM docker.io/library/alpine:latest

# Install dependencies needed by the script
RUN apk add --no-cache bash curl stress-ng

# Copy the script into the container and make it executable
COPY keep-vm-alive.sh /usr/local/bin/keep-vm-alive
RUN chmod +x /usr/local/bin/keep-vm-alive

# Run the script when the container starts
CMD ["/usr/local/bin/keep-vm-alive"]