PYTHON ?= python3

builders ?= auto
VM_FLAGS = $(if $(vm_dir),--vm-dir "$(vm_dir)")
ACCESS_FLAGS = $(if $(tailscale_host),--tailscale-host '$(tailscale_host)') $(if $(recovery_host),--recovery-host '$(recovery_host)')

DRY_RUN_FLAG = $(if $(filter 1 true yes,$(dry_run)),--dry-run)

.PHONY: help bootstrap build deploy test vm-image list check-updates update secret

help:
	@printf '%s\n' \
		'Bootstrap Ubuntu prerequisites: make bootstrap host=mashu-admin' \
		'Build the ARM profile: make build' \
		'Build the ARM portable canary: make build output=packages.aarch64-linux.argus-canary' \
		'Deploy over SSH: make deploy host=mashu' \
		'Check live VPS access and health (read-only): make test' \
		'Build/cache the NixOS guest: make vm-image' \
		'Forbid VM builds: make build builders=none' \
		'' \
		'Update and commit a pinned release (Nixpkgs packages use flake.lock):' \
		'  make update service=<component> version=<version>' \
		'' \
		'Preview without writing:' \
		'  make update service=<component> version=<version> dry_run=1' \
		'' \
		'Update an encrypted service secret:' \
		'  make secret service=<service>' \
		'' \
		'Available components:'
	@$(PYTHON) scripts/update_component.py --list
	@printf '%s\n' '' 'Available secret services:'
	@$(PYTHON) scripts/update_secret.py --list

list:
	@$(PYTHON) scripts/update_component.py --list

check-updates:
	@$(PYTHON) scripts/update_component.py --check

update:
	@$(PYTHON) scripts/update_component.py $(DRY_RUN_FLAG) "$(service)" "$(version)"

secret:
	@$(PYTHON) scripts/update_secret.py "$(service)"

# Only the local NixOS VM is selected automatically; no production builder.
bootstrap:
	./bootstrap.sh "$(host)"

build:
	$(PYTHON) deploy.py build --output '$(or $(output),systemConfigs.mashu)' --builders '$(builders)' $(VM_FLAGS)

deploy:
	$(PYTHON) deploy.py deploy --target-host '$(or $(host),mashu)' --builders '$(builders)' $(VM_FLAGS) $(ACCESS_FLAGS)

test:
	$(PYTHON) deploy.py test --target-host '$(or $(host),mashu)' $(ACCESS_FLAGS)

vm-image:
	$(PYTHON) deploy.py vm-image --builders '$(builders)' $(VM_FLAGS)
