# Stress and security test results, final set of 2026-11-13

One folder per reporting date. Everything the journal paper quotes comes from here.

```
2026-11-13/
  README.md            this file
  SHA256SUMS           checksum of every other file in this folder
  report/              generated results (rebuilt by tools/, never edited by hand)
    STATUS.md          pass / fail / known-gap counts per group and per Pi
    FAILURES.md        only the failed and known-gap checks, each with the reason
    matrix.csv|json    one row per check (id, test, Pi, status, detail, source file)
    measurements.json  speed, ping and latency numbers
    *.svg              coverage charts per Pi, and the failure list
  evidence/            raw files as collected from the Pis and the laptop (not edited)
    clean-pi/          THE DATASET: Clean Prod Pi 192.168.1.7, build 72039b8, one frozen config
    production-pi/     Dirty Prod Pi 192.168.1.10, old build (2026-10-24): reference runs
    production-sec/    security suite run from the laptop against the dirty Pi's public address
    production-sec-rerun/  its re-run of the failed login checks
    test-pi/           pilot runs on 192.168.1.7 before the clean build: not counted in the matrix
    laptop/            in-process race tests (no Pi)
    RUNS.md            what each individual run folder in the old Pi folders is
  tools/               build_matrix.py and build_failures.py (python 3, standard library)
```

Rules the data follows: one system, one build, one frozen configuration per dataset; the clean Pi and the dirty Pi are never mixed in one table; pilot runs are kept as evidence but not counted.

## Rebuild the reports

```
python tools/build_matrix.py      # reads evidence/, writes report/ and ../../../stress/*.svg
python tools/build_failures.py    # reads report/matrix.json, writes report/FAILURES.md and the failure SVG
```

## Verify

From this folder: `sha256sum -c SHA256SUMS` (every line must say OK). Regenerate it with
`find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS`.
Rebuilding the reports changes the files in `report/` only by their timestamps if the evidence is unchanged; run the checksum command again after any rebuild.

Interpretation, caveats and the full written results are in `qa/stress/result.md`.

## Integrity and sensitive data

Everything under `evidence/` is byte-identical to what was collected: nothing was edited or redacted. Before publishing, `qa/` was searched for private keys, tunnel and API tokens, OTP URIs and bearer tokens. The only hits are fragments of JWT access tokens printed by pytest in three JUnit failure messages (`evidence/clean-pi/campaign/sec/app.xml`, `sec-rerun-login/rerun.xml`, `rn-live-rerun/rn-live.xml`); pytest cut each one in the middle (`...`) so none has a signature, and they were valid for 15 minutes for demonstration accounts. The accounts and data are demonstration data.
