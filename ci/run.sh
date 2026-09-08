#!/usr/bin/env bash
# CLARION CI gate (roadmap P2.11, the tender).
#
# One portable script. It is what `.woodpecker.yml` and the repo `Makefile`
# call, and it runs the same on a dev laptop, in Gitea/Forgejo/Woodpecker
# Actions, or on an air-gapped runner. No network required (see the
# per-tool notes in ci/README.md for feeding trivy / osv-scanner their DBs).
#
#   ci/run.sh              full gate
#   ci/run.sh --fast       skip the slow gates (pytest, trivy) -- pre-commit use
#   ci/run.sh --no-sca     skip dependency scanning (osv-scanner / pip-audit)
#
# Exit non-zero if any HARD gate fails. SOFT gates print and continue.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FAST=0 ; SCA=1
for a in "$@"; do
  case "$a" in
    --fast) FAST=1 ;;
    --no-sca) SCA=0 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

# pytest / check_schema need these; use throwaway values if the env is bare.
export SECRET_KEY="${SECRET_KEY:-ci-only-secret-key-not-for-any-deployment}"
export OTP_HMAC_KEY="${OTP_HMAC_KEY:-ci-only-otp-hmac-key}"
export APP_ENV="${APP_ENV:-demo}"

FAILED=()
run_hard() { echo "== $1 =="; shift; if "$@"; then echo "  OK"; else echo "  FAIL"; FAILED+=("$1"); fi; echo; }
run_soft() { echo "== $1 (advisory) =="; shift; "$@" || true; echo; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- lint -----------------------------------------------------------------
run_hard "ruff (F / E9 / B006)" \
  ruff check --config "$ROOT/ci/ruff.toml" "$BACKEND/app" "$BACKEND/db" "$BACKEND/tests" "$BACKEND/alembic"
run_soft "ruff style (line length, imports, pyupgrade)" \
  ruff check --isolated --select E,W,I,UP,B --statistics "$BACKEND/app"

if have shellcheck; then
  # lint every tracked *.sh (ci/, backend/backup/, backend/db/mariadb/, entrypoints)
  mapfile -t SH < <(git -C "$ROOT" ls-files '*.sh')
  run_hard "shellcheck" bash -c "cd '$ROOT' && shellcheck -x -S warning ${SH[*]}"
fi

# --- SAST ---------------------------------------------------------------
if have bandit; then
  run_hard "bandit (medium+ severity)" \
    bandit -q -r "$BACKEND/app" -ll -x "$BACKEND/app/tests"
else
  echo "!! bandit not installed -- pip install -r backend/requirements-dev.txt"; echo
fi

if have semgrep; then
  run_hard "semgrep (ci/semgrep local rules)" \
    semgrep scan --config "$ROOT/ci/semgrep" --error --severity ERROR --severity WARNING \
      --metrics=off --disable-version-check --quiet "$BACKEND"
else
  echo "!! semgrep not installed -- pip install -r backend/requirements-dev.txt"; echo
fi

# --- dependency / vulnerability scanning -------------------------------
if [ "$SCA" = 1 ]; then
  if have osv-scanner; then
    # OSV DB: `osv-scanner --offline --download-offline-databases` once on a
    # connected host, then copy ~/.cache/osv-scanner/ to the runner.
    run_hard "osv-scanner (Python deps)" \
      osv-scanner scan --lockfile "$BACKEND/requirements.txt" \
        --lockfile "$BACKEND/requirements-dev.txt" ${OSV_OFFLINE:+--offline}
  elif have pip-audit; then
    echo "!! pip-audit found but it has NO offline mode -- prefer osv-scanner for"
    echo "   air-gapped CI (see ci/README.md). Running it anyway:"
    run_hard "pip-audit" pip-audit -r "$BACKEND/requirements.txt" -r "$BACKEND/requirements-dev.txt"
  else
    echo "!! no SCA tool (osv-scanner / pip-audit) -- see ci/README.md"; echo
  fi
fi

# --- container / filesystem CVE scan (soft; needs a pre-fetched DB) ----
if [ "$FAST" = 0 ] && have trivy; then
  run_soft "trivy fs (config + secrets + deps)" \
    trivy fs --scanners vuln,secret,misconfig --skip-db-update --offline-scan --exit-code 0 "$ROOT"
fi

# --- schema integrity + tests ----------------------------------------
run_hard "alembic up/down + model-drift gate" \
  bash -c "cd '$BACKEND' && python -m db.check_schema"

if [ "$FAST" = 0 ]; then
  run_hard "pytest" \
    bash -c "cd '$BACKEND' && python -m pytest -q"
fi

# --- verdict --------------------------------------------------------
echo "=================================================="
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "CI GATE: PASS"
  exit 0
fi
echo "CI GATE: FAIL -- ${FAILED[*]}"
exit 1
