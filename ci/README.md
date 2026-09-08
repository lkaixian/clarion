# CLARION CI gate (P2.11)

One portable gate, runnable anywhere with no network:

```
ci/run.sh              # full: ruff · bandit · semgrep · SCA · check_schema · pytest
ci/run.sh --fast       # skip pytest + trivy (pre-commit)
ci/run.sh --no-sca     # skip dependency scanning
make ci                # same, from the repo root
```

Tender clauses: **** (OWASP-guided development), ****
("AI-assisted code quality & compliance review in the dev pipeline —
auto-detect logic errors, security vulns, OWASP deviations pre-deployment"),
**** (continuous automated vulnerability assessment).

## The gates

| Gate | Tool | Hard? | Offline? |
|---|---|---|---|
| Lint / pyflakes-equivalent | `ruff` (`ci/ruff.toml`) | yes | yes |
| Style (line length, imports, pyupgrade) | `ruff` | advisory | yes |
| Python SAST | `bandit -ll` | yes | yes — no data feed |
| CLARION security patterns | `semgrep` + `ci/semgrep/*.yml` | yes | yes — local rules |
| Python dependency CVEs | `osv-scanner` | yes | yes — pre-downloaded OSV DB |
| Filesystem / container CVEs + secrets | `trivy fs` | advisory | yes — pre-fetched DB |
| Schema: `alembic up→down→up`, no model drift | `python -m db.check_schema` | yes | yes |
| Tests | `pytest` | yes | yes |

`ruff` replaces the ad-hoc `python -m pyflakes` the earlier waves used.

## Install

```
pip install -r backend/requirements.txt -r backend/requirements-dev.txt   # ruff, bandit, semgrep, pytest
```

`osv-scanner` and `trivy` are Go binaries — install from your distro / a
vendored release tarball, not pip.

## Air-gapped setup

- **semgrep** — `ci/semgrep/*.yml` are local, no network. To add the
  community packs, `git clone https://github.com/semgrep/semgrep-rules`
  into `ci/semgrep/vendor/` and it's picked up by `--config ci/semgrep`.
  `ci/run.sh` already passes `--metrics=off --disable-version-check`.
- **osv-scanner** — on a connected host once:
  `osv-scanner scan --download-offline-databases --offline --lockfile backend/requirements.txt`
  then copy `~/.cache/osv-scanner/` to the runner and set `OSV_OFFLINE=1`.
- **trivy** — on a connected host:
  `trivy image --download-db-only` (or pull `ghcr.io/aquasecurity/trivy-db`
  as an OCI artifact), copy the cache dir to the runner. `ci/run.sh` runs it
  with `--skip-db-update --offline-scan`.
- **pip-audit is NOT used** — it has no offline mode (queries OSV/PyPI live).
  `osv-scanner` with a pre-downloaded DB covers the same ground offline. If
  you must keep pip-audit, run it on a periodically-connected mirror host and
  ship the report.

## Wiring to a forge

- **Woodpecker CI** (recommended for air-gap — no marketplace-action
  dependency): `.woodpecker.yml` in the repo root already calls `ci/run.sh`.
  Point the agent at an internal registry that has the `python:3.13-slim` (or
  a pre-baked `clarion-ci`) image.
- **Gitea / Forgejo Actions**: works air-gapped if the runner images are
  pre-loaded and `DEFAULT_ACTIONS_URL` in `app.ini` points at the internal
  forge (mirror `actions/checkout` there). A workflow that just runs
  `bash ci/run.sh` needs no other actions.
- **Anything else**: `make ci`.
