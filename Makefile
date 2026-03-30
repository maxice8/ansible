# Makefile
.PHONY: all compile rebuild clean

all: rebuild

# 1. Inject variables and compile Butane to Ignition
config.ign: config.bu
	@echo "compiling ignition..."
	@podman run --interactive --rm quay.io/coreos/butane:release --strict < config.bu > config.ign

# 2. Run the existing rebuild script
rebuild: config.ign
	@./rebuild-fcos.sh

# 3. Clean up temporary files
clean:
	rm -f config.ign