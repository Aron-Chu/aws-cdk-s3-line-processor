#!/usr/bin/env bash
# Mask CloudFormation stack OutputValue entries in GitHub Actions logs.
# Missing stacks are a no-op. Other describe-stacks failures abort.
set -euo pipefail

STACK_NAME="${1:-S3LineProcessorStack}"
STACK_JSON="$(mktemp)"
STACK_ERR="$(mktemp)"
trap 'rm -f "$STACK_JSON" "$STACK_ERR"' EXIT

set +e
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --output json >"$STACK_JSON" 2>"$STACK_ERR"
status=$?
set -e

if [ "$status" -ne 0 ]; then
  if grep -Eqi 'does not exist' "$STACK_ERR"; then
    exit 0
  fi
  cat "$STACK_ERR" >&2
  exit "$status"
fi

jq -r '.Stacks[0].Outputs[]? | .OutputValue // empty' "$STACK_JSON" \
  | while IFS= read -r value; do
    [ -n "$value" ] || continue
    echo "::add-mask::$value"
  done
