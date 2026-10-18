PYTHON ?= python3

.PHONY: bootstrap
bootstrap:
	./bootstrap.sh "$(host)"

.PHONY: secret
secret:
	$(PYTHON) scripts/update_secret.py "$(service)"

DRY_RUN_FLAG = $(if $(filter 1 true yes,$(dry_run)),--dry-run)

.PHONY: list check-updates update
list:
	$(PYTHON) scripts/update_component.py --list

check-updates:
	$(PYTHON) scripts/update_component.py --check

update:
	$(PYTHON) scripts/update_component.py $(DRY_RUN_FLAG) "$(service)" "$(version)"
