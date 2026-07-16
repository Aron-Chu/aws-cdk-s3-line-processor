# Super-simple local helpers. Run from WSL/Linux.
#
#   make setup
#   make check
#   make smoke PROFILE=s3-line-processor-operator

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PROFILE ?=
REGION ?= us-west-2
STACK ?= S3LineProcessorStack

.PHONY: help setup lint test synth check smoke

help:
	@echo "make setup                              Create/reuse .venv, install deps, enable pre-commit"
	@echo "make lint                               Run pre-commit on all files"
	@echo "make test                               Run local pytest (no AWS)"
	@echo "make synth                              Run cdk synth"
	@echo "make check                              lint + test + synth"
	@echo "make smoke PROFILE=<cli-profile>        Live AWS smoke (IAM user or SSO profile)"
	@echo ""
	@echo "Example: make smoke PROFILE=s3-line-processor-operator"

setup:
	@if [ ! -x "$(PY)" ]; then \
		if command -v uv >/dev/null 2>&1; then \
			uv python install 3.14; \
			uv venv --python 3.14 "$(VENV)"; \
		elif command -v python3.14 >/dev/null 2>&1; then \
			python3.14 -m venv "$(VENV)"; \
		else \
			echo "Python 3.14 not found on PATH."; \
			echo "Install uv (https://docs.astral.sh/uv/) and rerun: make setup"; \
			echo "Or install Python 3.14 and ensure python3.14 is available."; \
			exit 1; \
		fi; \
	fi
	$(PIP) install -r requirements-dev.txt
	npm ci
	$(PY) -m pre_commit install

lint:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	$(PY) -m pre_commit run --all-files

test:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	$(PY) -m pytest

synth:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	PATH="$(CURDIR)/$(VENV)/bin:$$PATH" npx cdk synth

check: lint test synth

smoke:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	@test -n "$(PROFILE)" || { \
		echo "Usage: make smoke PROFILE=s3-line-processor-operator"; \
		echo "PROFILE must be a real local AWS CLI profile (IAM user or SSO), not a docs placeholder."; \
		exit 2; \
	}
	$(PY) scripts/live_smoke_test.py \
		--profile "$(PROFILE)" \
		--region "$(REGION)" \
		--stack "$(STACK)" \
		--cleanup
