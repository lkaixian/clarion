#!/usr/bin/env bash
# run_sec_pi.sh - the whole security suite (CK, T, A + host scripts) from the Pi against the public URL.
# SEC_OUT=<dir> ./run_sec_pi.sh      (needs root for the host stages: sniff, exposure scan, host audit)
set -u
. "$(dirname "$0")/campaign_env.sh"
OUT=${SEC_OUT:?set SEC_OUT}; mkdir -p "$OUT"

# The edge blocks /openapi.json, so give the A1 matrix the schema of the running app.
docker exec clarion-pi-backend-1 python -c "import logging; logging.disable(50); import json; from app.main import app; open('/tmp/openapi.json','w').write(json.dumps(app.openapi()))" \
  && docker cp clarion-pi-backend-1:/tmp/openapi.json "$OUT/openapi.json" && export SEC_OPENAPI_FILE=$OUT/openapi.json

export SEC_USER=clinician@clarion.demo SEC_PASS=clinician123
export SEC_ADMIN_USER=admin@clarion.demo SEC_ADMIN_PASS=admin123
export SEC_CLINICIAN_USER=clinician@clarion.demo SEC_CLINICIAN_PASS=clinician123
export SEC_PHARMACIST_USER=pharmacist@clarion.demo SEC_PHARMACIST_PASS=pharmacist123
export SEC_RECEPTIONIST_USER=receptionist@clarion.demo SEC_RECEPTIONIST_PASS=receptionist123
export SEC_PATIENT_USER=patient@clarion.demo SEC_PATIENT_PASS=patient123
export APP_ENV=demo SEC_BEHIND_CF=1 SEC_RUN_BURST=1 SEC_DOCKER=1 PYTHON=$VENV/bin/python SEC_OUT=$OUT
export SEC_LOG_CMD="docker compose -f $COMPOSE_FILE --project-directory $REPO_C --env-file $REPO_C/.env.docker logs --since 15m proxy backend"
export PATH=$VENV/bin:$PATH
cd "$REPO_C/qa/stress/sec" && ./run_sec.sh --host
