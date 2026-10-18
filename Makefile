PYTHON ?= python3

.PHONY: bootstrap
bootstrap:
	./bootstrap.sh "$(host)"

.PHONY: secret
secret:
	$(PYTHON) scripts/update_secret.py "$(service)"
