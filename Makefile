SHELL := /bin/sh
.DEFAULT_GOAL := bootstrap

host ?= mashu
.PHONY: bootstrap
bootstrap:
	./bootstrap.sh '$(host)'
