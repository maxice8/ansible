PYTHON ?= python3

COMPONENTS := \
	argocd \
	k3s \
	gateway-api \
	rancher-chart \
	rancher-compliance-chart \
	traefik-chart \
	traefik-image \
	cert-manager-chart \
	sops-secrets-operator-chart \
	netdata-chart \
	argus \
	archisteamfarm \
	backrest \
	forgejo-chart \
	forgejo \
	forgejo-runner \
	docker-dind \
	netbird \
	netbird-client \
	netbird-server \
	netbird-dashboard \
	pingvin-share \
	pocket-id \
	pomerium \
	syncthing \
	whoami \
	yq

DRY_RUN_FLAG = $(if $(filter 1 true yes,$(dry_run)),--dry-run)

.PHONY: help list update $(COMPONENTS)

help:
	@printf '%s\n' \
		'Update a component:' \
		'  make <component> version=<version>' \
		'' \
		'Preview without writing:' \
		'  make <component> version=<version> dry_run=1' \
		'' \
		'Available components:'
	@$(PYTHON) scripts/update_component.py --list

list:
	@$(PYTHON) scripts/update_component.py --list

update:
	@$(PYTHON) scripts/update_component.py $(DRY_RUN_FLAG) "$(component)" "$(version)"

$(COMPONENTS):
	@$(MAKE) --no-print-directory update component="$@" version="$(version)" dry_run="$(dry_run)"
