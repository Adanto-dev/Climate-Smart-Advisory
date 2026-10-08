#!/usr/bin/env bash
# One command:  ./run.sh            interactive officer review (you type your name and approve/reject)
#               ./run.sh --yes-as "Your Name"   non-interactive, SIMULATED approval (logged as such)
#               ./run.sh evals      re-run the eval suite and regenerate EVALS.md
#               ./run.sh test       unit tests
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -e ".[dev]"
python scripts/make_data.py >/dev/null
case "${1:-}" in
  evals) exec python -m evals.run_evals ;;
  test)  exec python -m pytest -q ;;
  *)     exec python -m csa.cli run "$@" ;;
esac
