# Makefile
.PHONY: all clean
.PRECIOUS: %.bu %.ign

export SOPS_AGE_KEY_FILE ?= $(PWD)/.age-key.txt

all:
	@echo "Usage: make <hostname>"

%: %.ign
	@echo "Done! $@.ign is ready for deployment."

%.ign: %.env config.bu.tmpl
	@echo "=> Decrypting $*.env in memory..."
	@bash -c 'set -a; eval "$$(sops -d $*.env)"; set +a; envsubst < config.bu.tmpl > $*.bu'
	@echo "=> Compiling $*.bu to $@..."
	@podman run --interactive --rm quay.io/coreos/butane:release --strict < $*.bu > $@

clean:
	rm -f *.bu *.ign
