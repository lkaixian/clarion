# qa/stress/py - race + degraded-network tests

    pip install -r requirements.txt
    BASE_URL=https://staging.example ADMIN_EMAIL=... ADMIN_PASSWORD=... pytest -v test_races_live.py
    python race.py --url https://staging.example --token JWT --method POST --path /x --json '{}' -n 20 --expect-single-success

Degraded network (Toxiproxy: `docker run -p 8474:8474 -p 18080:18080 ghcr.io/shopify/toxiproxy`):

    TOXIPROXY_URL=http://localhost:8474 BASE_URL=https://staging.example ADMIN_EMAIL=... ADMIN_PASSWORD=... pytest -v test_degraded_network.py

All live tests skip when BASE_URL is unset. In-process equivalents: `backend/tests/test_races.py`
(run it on MariaDB with `DATABASE_URL=mysql+pymysql://...`).
Known gaps are `xfail(reason=...)`; an XPASS means the gap was fixed, delete the marker.
