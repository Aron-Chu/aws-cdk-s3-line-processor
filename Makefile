# Super-simple local helpers. Run from WSL/Linux.
#
#   make setup
#   make check
#   make smoke PROFILE=s3-line-processor-operator

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UV := $(VENV)/bin/uv
PROFILE ?=
REGION ?= us-west-2
STACK ?= S3LineProcessorStack
LOCK_ARGS := --quiet --python-version 3.14 --universal --generate-hashes --no-annotate --custom-compile-command "make lock"

.PHONY: help setup lock lock-check lint test synth check smoke

help:
	@echo "make setup                              Create/reuse .venv, install deps, enable pre-commit"
	@echo "make lock                               Regenerate the hash-pinned Python lockfile"
	@echo "make lock-check                         Verify the Python lockfile is current"
	@echo "make lint                               Run pre-commit on all files"
	@echo "make test                               Run local pytest (no AWS)"
	@echo "make synth                              Run cdk synth"
	@echo "make check                              lock-check + lint + test + synth"
	@echo "make smoke PROFILE=<cli-profile>        Live AWS smoke (IAM user or SSO profile)"
	@echo ""
	@echo "Example: make smoke PROFILE=s3-line-processor-operator"

setup:
	@if [ ! -x "$(PY)" ]; then \
		if command -v uv >/dev/null 2>&1; then \
			uv python install 3.14; \
			uv venv --seed --python 3.14 "$(VENV)"; \
		elif command -v python3.14 >/dev/null 2>&1; then \
			python3.14 -m venv "$(VENV)"; \
		else \
			echo "Python 3.14 not found on PATH."; \
			echo "Install uv (https://docs.astral.sh/uv/) and rerun: make setup"; \
			echo "Or install Python 3.14 and ensure python3.14 is available."; \
			exit 1; \
		fi; \
	fi
	$(PIP) install --require-hashes -r requirements.lock
	npm ci
	$(PY) -m pre_commit install

lock:
	@test -x "$(UV)" || { echo "Missing $(UV). Run: make setup"; exit 1; }
	$(UV) pip compile $(LOCK_ARGS) --upgrade requirements-dev.txt -o requirements.lock

lock-check:
	@test -x "$(UV)" || { echo "Missing $(UV). Run: make setup"; exit 1; }
	@set -e; \
	tmp=$$(mktemp); \
	trap 'rm -f "$$tmp"' EXIT; \
	$(UV) pip compile $(LOCK_ARGS) --constraints requirements.lock requirements-dev.txt -o "$$tmp" >/dev/null; \
	cmp -s requirements.lock "$$tmp" || { \
		echo "requirements.lock is stale. Run: make lock"; \
		exit 1; \
	}

lint:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	$(PY) -m pre_commit run --all-files

test:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	$(PY) -m pytest

synth:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	PATH="$(CURDIR)/$(VENV)/bin:$$PATH" npx cdk synth

check: lock-check lint test synth

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
