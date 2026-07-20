VENV ?= .venv
VENV_BIN := $(abspath $(VENV))/bin
PY := $(VENV_BIN)/python
PIP := $(VENV_BIN)/pip
UV := $(VENV_BIN)/uv
PROFILE ?=
REGION ?= us-west-2
STACK ?= S3LineProcessorStack
LOCK_ARGS := --quiet --python-version 3.14 --universal --generate-hashes --no-annotate --custom-compile-command "make lock"

EXPECTED_ACCOUNT ?=
SMOKE_PY = SMOKE_EXPECTED_ACCOUNT="$(EXPECTED_ACCOUNT)" $(PY) scripts/live_smoke_test.py

.PHONY: help setup lock lock-check lint test synth check aws-check sandbox-ack bootstrap diff deploy smoke smoke-check

help:
	@echo "make setup                              Create/reuse .venv, install deps, enable pre-commit"
	@echo "make lock                               Regenerate the hash-pinned Python lockfile"
	@echo "make lock-check                         Verify the Python lockfile is current"
	@echo "make lint                               Run pre-commit on all files"
	@echo "make test                               Run local pytest (no AWS)"
	@echo "make synth                              Run cdk synth"
	@echo "make check                              lock-check + lint + test + synth"
	@echo "make aws-check PROFILE=<profile>        Verify the target AWS identity"
	@echo "make bootstrap PROFILE=<profile>        Bootstrap a developer-owned sandbox (ack required)"
	@echo "make diff PROFILE=<profile>             Review the live CDK diff"
	@echo "make deploy PROFILE=<profile>           check + diff + developer-owned sandbox deploy (ack required)"
	@echo "make smoke-check PROFILE=<smoke-profile> Read-only assumed-role smoke preflight"
	@echo "make smoke PROFILE=<smoke-profile>       Authorized live AWS smoke (write-capable)"
	@echo ""
	@echo "Local bootstrap/deploy require: SANDBOX_ACK=developer-owned"
	@echo "Optional smoke account pin: EXPECTED_ACCOUNT=<account-id>"

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
	TMPDIR=/tmp TMP=/tmp TEMP=/tmp $(PY) -m pytest

synth:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	PATH="$(VENV_BIN):$$PATH" npx cdk synth

check: lock-check lint test synth

aws-check:
	@test -n "$(PROFILE)" || { echo "Usage: make $@ PROFILE=<aws-profile> [REGION=$(REGION)]"; exit 2; }
	aws sts get-caller-identity --profile "$(PROFILE)" --region "$(REGION)"

sandbox-ack:
	@case "$(SANDBOX_ACK)" in \
		developer-owned|reviewer-owned) exit 0 ;; \
		*) \
		echo "Refusing a local AWS write."; \
		echo "Use the protected GitHub Deploy workflow for the repository stack."; \
		echo "For your own sandbox, add: SANDBOX_ACK=developer-owned"; \
		exit 2; \
		;; \
	esac

bootstrap: sandbox-ack aws-check
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	@account=$$(aws sts get-caller-identity --profile "$(PROFILE)" --query Account --output text); \
	PATH="$(VENV_BIN):$$PATH" AWS_REGION="$(REGION)" AWS_DEFAULT_REGION="$(REGION)" \
		npx cdk bootstrap "aws://$$account/$(REGION)" --profile "$(PROFILE)"

diff: aws-check
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	PATH="$(VENV_BIN):$$PATH" AWS_REGION="$(REGION)" AWS_DEFAULT_REGION="$(REGION)" \
		npx cdk diff --profile "$(PROFILE)"

deploy: sandbox-ack check diff
	PATH="$(VENV_BIN):$$PATH" AWS_REGION="$(REGION)" AWS_DEFAULT_REGION="$(REGION)" \
		npx cdk deploy --profile "$(PROFILE)"

smoke-check:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	@test -n "$(PROFILE)" || { \
		echo "Usage: make smoke-check PROFILE=<SMOKE_PROFILE> [REGION=$(REGION)] [STACK=$(STACK)] [EXPECTED_ACCOUNT=<account-id>]"; \
		echo "Read-only preflight only; does not authorize or run make smoke."; \
		exit 2; \
	}
	@$(SMOKE_PY) \
		--check-only \
		--profile "$(PROFILE)" \
		--region "$(REGION)" \
		--stack "$(STACK)"

smoke:
	@test -x "$(PY)" || { echo "Missing $(PY). Run: make setup"; exit 1; }
	@test -n "$(PROFILE)" || { \
		echo "Usage: make smoke PROFILE=<SMOKE_PROFILE>"; \
		echo "PROFILE must be an approved temporary assumed-role profile, not a docs placeholder."; \
		echo "Run make smoke-check first; obtain explicit authorization before this write-capable target."; \
		exit 2; \
	}
	@$(SMOKE_PY) \
		--profile "$(PROFILE)" \
		--region "$(REGION)" \
		--stack "$(STACK)" \
		--cleanup
