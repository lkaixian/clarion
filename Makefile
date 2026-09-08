# CLARION -- dev + CI shortcuts (roadmap P2.11).
# The CI gate is one portable script, ci/run.sh; these are thin wrappers.
.PHONY: ci ci-fast lint security test schema deps install help

help:
	@echo "make install   - pip install runtime + dev deps"
	@echo "make ci        - the full CI gate (ci/run.sh)"
	@echo "make ci-fast   - CI gate without pytest / trivy (pre-commit)"
	@echo "make lint      - ruff only"
	@echo "make security  - bandit + semgrep + SCA"
	@echo "make test      - pytest"
	@echo "make schema    - alembic up/down + model-drift gate"

install:
	pip install -r backend/requirements.txt -r backend/requirements-dev.txt

ci:
	bash ci/run.sh

ci-fast:
	bash ci/run.sh --fast

lint:
	ruff check --config ci/ruff.toml backend/app backend/db backend/tests backend/alembic

security:
	bandit -q -r backend/app -ll
	semgrep scan --config ci/semgrep --error --severity ERROR --severity WARNING \
		--metrics=off --disable-version-check backend
	@command -v osv-scanner >/dev/null 2>&1 && \
		osv-scanner scan --lockfile backend/requirements.txt --lockfile backend/requirements-dev.txt $${OSV_OFFLINE:+--offline} || \
		echo "osv-scanner not installed -- see ci/README.md"

test:
	cd backend && python -m pytest -q

schema:
	cd backend && python -m db.check_schema
