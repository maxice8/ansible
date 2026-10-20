SHELL := /bin/sh
.SHELLFLAGS := -eu -c
.ONESHELL:
.DEFAULT_GOAL := help

builders ?= none
host ?= mashu
ACCESS_FLAGS = $(if $(tailscale_host),--tailscale-host '$(tailscale_host)') $(if $(recovery_host),--recovery-host '$(recovery_host)')

ifeq ($(firstword $(MAKECMDGOALS)),update)
ifneq ($(words $(MAKECMDGOALS)),1)
ifneq ($(words $(MAKECMDGOALS)),3)
$(error Usage: make update [<component> <version>] [dry_run=1])
endif
service := $(word 2,$(MAKECMDGOALS))
version := $(word 3,$(MAKECMDGOALS))
ifneq ($(filter build deploy test bootstrap diff push help list check-updates update secret,$(service) $(version)),)
$(error Service and version must not be Make command names)
endif
.PHONY: $(service) $(version)
$(service) $(version): ; @:
endif
endif

PYTHON ?= python3

DRY_RUN_FLAG = $(if $(filter 1 true yes,$(dry_run)),--dry-run)

.PHONY: build deploy test bootstrap diff push help list check-updates update secret

help:
	@printf '%s\n' \
		'VPS workflow' \
		'  make build                        Build the profile' \
		'  make diff                         Compare with the deployed profile' \
		'  make deploy                       Deploy and check readiness' \
		'  make test                         Check VPS health' \
		'  make bootstrap host=<ssh-host>    Prepare Ubuntu prerequisites' \
		'  make push                         Push Git commits' \
		'' \
		'Updates (commit changes automatically)' \
		'  make update                       Update all flake inputs' \
		'  make update inputs=nixpkgs        Update only Nixpkgs' \
		'  make update <component> <version> Update a local package pin' \
		'  Add dry_run=1 to preview a local package update.' \
		'' \
		'Other commands' \
		'  make check-updates                Validate update mappings' \
		'  make secret service=<service>     Update an encrypted secret' \
		'' \
		'Components (Nixpkgs packages use flake.lock):'
	@$(PYTHON) scripts/update_component.py --list
	@printf '%s\n' '' 'Secret services:'
	@$(PYTHON) scripts/update_secret.py --list

list:
	@$(PYTHON) scripts/update_component.py --list

check-updates:
	@$(PYTHON) scripts/update_component.py --check

secret:
	@$(PYTHON) scripts/update_secret.py "$(service)"

bootstrap:
	@./bootstrap.sh '$(host)'

build:
	@$(PYTHON) deploy.py build --output '$(or $(output),systemConfigs.mashu)' --builders '$(builders)'

deploy:
	@$(PYTHON) deploy.py deploy $(if $(filter command line,$(origin host)),--target-host '$(host)') --builders '$(builders)' $(ACCESS_FLAGS)

test:
	@$(PYTHON) deploy.py test --target-host '$(host)' $(ACCESS_FLAGS)

push:
	@git push

update:
ifneq ($(word 2,$(MAKECMDGOALS)),)
	@$(PYTHON) scripts/update_component.py $(DRY_RUN_FLAG) "$(service)" "$(version)"
else
	@if git diff --quiet HEAD -- flake.lock; then
	    nix flake update $(inputs)
	else
	    echo 'Committing existing flake.lock changes.'
	fi
	git diff --quiet HEAD -- flake.lock && exit 0
	git commit --only -m 'build(deps): update flake.lock' -- flake.lock
endif

diff:
	@host='$(host)'
	case "$$host" in -*) echo "Invalid SSH host." >&2; exit 1 ;; esac
	test -e result || { echo "Run make build first." >&2; exit 1; }
	work=$$(mktemp -d /tmp/mashu-diff.XXXXXX)
	trap 'ssh -S "$$work/ssh" -O exit "$$host" >/dev/null 2>&1 || :; rm -rf -- "$$work"' 0
	trap 'exit 1' 1 2 15
	ssh -o BatchMode=yes -o ConnectTimeout=10 -M -N -f -S "$$work/ssh" "$$host"
	deployed=$$(ssh -S "$$work/ssh" -o ProxyCommand=false "$$host" readlink -e /nix/var/nix/gcroots/system-manager-current)
	case "$$deployed" in /nix/store/*) ;; *) echo "Invalid deployed profile: $$deployed" >&2; exit 1 ;; esac
	sudo -n env "NIX_SSHOPTS=-F /dev/null -S $$work/ssh -o BatchMode=yes -o ProxyCommand=false" \
	nix copy --from "ssh://$$host" --substitute-on-destination --no-check-sigs "$$deployed"
	nvd diff "$$deployed" ./result
