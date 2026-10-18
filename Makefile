PYTHON ?= python3

.PHONY: bootstrap
bootstrap:
	./bootstrap.sh "$(host)"
