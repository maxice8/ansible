PYTHON ?= python3

COMPONENTS := \
	argocd \
	k3s \
	gateway-api \
	rancher \
	rancher-compliance \
	traefik-chart \
	traefik-image \
	cert-manager \
	sops-secrets-operator \
	netdata \
	argus \
	asf \
	backrest \
	forgejo-chart \
	forgejo \
	forgejo-runner \
	docker-dind \
	netbird \
	netbird-dashboard \
	pingvin-share \
	pocket-id \
	pomerium \
	syncthing \
	whoami \
	yq

COMPONENT_ALIASES := \
	archisteamfarm \
	cert-manager-chart \
	netbird-server \
	netdata-chart \
	rancher-chart \
	rancher-compliance-chart \
	sops-secrets-operator-chart

DRY_RUN_FLAG = $(if $(filter 1 true yes,$(dry_run)),--dry-run)

ifneq ($(filter update,$(MAKECMDGOALS)),)
ifeq ($(filter $(service),$(COMPONENTS) $(COMPONENT_ALIASES)),)
$(error Unknown update service '$(service)'. Use one of: $(COMPONENTS))
endif
endif

.PHONY: help list check-updates update secret

help:
	@printf '%s\n' \
		'Update a component:' \
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
