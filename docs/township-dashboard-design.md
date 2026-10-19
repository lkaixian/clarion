# Township health dashboard: design (not built)

Goal: let a township see health trends across independent clinics without any clinic, or central, ever holding another clinic's patient rows.

## Recommendation: share counts, never rows

Earlier notes suggested a shared pseudonym key across facilities. Drop that. If only suppressed counts leave a clinic, there is nothing to pseudonymise and no key to leak.

```
clinic DB --(local query)--> weekly counts --(small-cell suppression, k=5)--> signed PUT /aggregates
central: sums per (week, category, age band) across clinics --(k again after summing)--> GET /township/summary
```

1. **What a clinic sends.** One signed document per week: `{week, facility_id, cells: [{category, age_band, count}]}`. Category is a coarse group (respiratory, GI, chronic review, injury, other), age band is 0-4 / 5-17 / 18-64 / 65+. A cell under 5 is not sent at all; it is added to an `other` bucket only if that bucket also reaches 5.
2. **What central does.** It verifies the clinic's Ed25519 signature (same scheme as visit pointers, `mpi/sigs.py`), stores the cells, and answers summary queries by summing. It applies the k=5 rule again to the sums, so a cell that is large only because several clinics contributed is fine, and one small cell is still hidden.
3. **Who sees it.** A township-admin login at central (read-only, no patient access). Optionally a public page limited to non-clinical numbers (clinic opening hours, current wait times).
4. **No consent screen needed for counts**, but get a PDPA read on whether suppressed aggregates still count as personal data for a township of this size. Very small clinics may need k above 5 or weekly roll-ups to monthly.

## Reuse in the codebase

- Local counting: `reporting_engine.run_report` already groups by fields and now drops groups under `MIN_CELL` when `anonymize=True`.
- Transport and auth: `mpi_client._call` and `mpi/main.py::authenticated_facility`.
- Scheduling: `app/jobs.py` queue (one job per week).

## Build list (about 2 days)

1. `aggregate_job` in `mpi_client.py` plus a category map for conditions.
2. `PUT /aggregates` and `GET /township/summary` in `mpi/main.py`, new table `aggregate_cells`.
3. A read-only township-admin page in the web console (or a separate static page served by central).
4. Tests: suppression at clinic and at central, signature check, a clinic cannot overwrite another's cells.

## Decisions needed before building

- Category list and age bands (clinical sign-off).
- Whether central is allowed to hold even suppressed health counts (data-protection officer).
- Who the township admin is and how that login is issued.

## Known limits

Differencing is still possible (the total with and without one clinic). Add noise or merge small clinics if a clinic could be identified from the totals.
