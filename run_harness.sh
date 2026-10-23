#!/usr/bin/env bash
# One-command test harness for the BARCA possession pipeline.
#
#   ./run_harness.sh            # all four sections (invariants, ablation, sweep, bootstrap)
#   ./run_harness.sh invariants  # just the invariant tests
#
# Everything the harness generates lands under tests/_results/ (reports, scorer outputs) and
# tests/_cache/ (variant label CSVs) inside this repository: mtah-2027 is only ever read from.
set -euo pipefail
cd "$(dirname "$0")"
exec "${PYTHON:-../../.venv/bin/python}" -m pytest tests -v "$@"