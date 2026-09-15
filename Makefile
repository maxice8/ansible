PYTHON ?= python3

DRY_RUN_FLAG = $(if $(filter 1 true yes,$(dry_run)),--dry-run)

.PHONY: help list check-updates update secret

help:
	@printf '%s\n' \
		'Update and commit a component:' \
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
