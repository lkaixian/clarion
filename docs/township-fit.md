# CLARION × Township of Tomorrow: fit report

Code-grounded assessment for the innovation challenge. Paths are relative to
`medibridge_package/`. Status: **complete** / **partial** / **stubbed or absent**.
Nothing here was run; it is read from source. Line numbers drift, so re-check before quoting.

## 1. Verdict

CLARION is a strong **safety, records and accessibility** story for the People
pillar (items 02, 03, 05). It is a clinic/hospital system, not a township
platform: nothing in the code or docs mentions townships, smart cities or SDGs,
and items 04, 06 and the whole Planet pillar have no real feature behind them.
Pitch it as the **health and safety backbone** of a township, not as a
township platform.

### Positioning claims vs the code

| Your claim | What the code does |
|---|---|
| "one federated, **resident-consented** record" | Federation is real (signed pointers, signed fetch, `backend/mpi/main.py`, `app/mpi_client.py`, `routers/federation.py`). But **no per-resident consent is checked**. The only gate is that the requesting staff member's facility has the patient present (`routers/federation.py:43-48`). The repo lists consent/presence proof as an open decision (`AGENTS.md`, `docs/deployment.md`). A facility-level opt-out (`records_shared_publicly`) exists; a per-patient one does not. |
| "NFC card is the **primary no-app interface**" | The card is a **secondary** credential. The app is the primary patient interface. The card is read by **staff and responder devices**, never by the resident (the `patient` role gets 403 on `/emergency/tag-keys`). Reception tap check-in works through a local NFC bridge (`web/src/pages/Reception.jsx`, `routers/reception/checkin.py`). There is no patient-facing kiosk and no card-tap queue. For elderly residents the real no-app-adjacent feature is **Senior Mode** in the app. |
| "every clinic, pharmacy and responder shares one record" | There is no tenant entity. Tenancy is a `facility_name` string plus one `HospitalSetting` row (`app/models.py`). Onboarding a hospital is manual and out-of-band. `docker-compose.spoke.yml` puts spokes on one shared DB, which contradicts independent businesses. Federated fetch is read-only, returns the newest 3 visits per patient and facility, and is never written into local tables. |

## 2. Feature inventory

### Backend
| Feature | Status | Where |
|---|---|---|
| FHIR-lite clinical model, facility scoping, RBAC + page permissions | complete | `app/models.py`, `app/auth.py`, `app/clinical_access.py` |
| Local + LDAP/AD auth, lockout, refresh-token sessions | complete | `app/ldap_auth.py`, `routers/auth_router.py` |
| Audit log: HMAC hash chain, DB triggers blocking edits, daily seal, 7-year archive | complete (WORM only with MinIO object lock provisioned; sealing is cron-dependent; MariaDB migration run still owed per `AGENTS.md`) | `app/audit_hash.py`, `db/seal_audit_day.py`, `app/audit_archive.py`, `db/verify_audit_chain.py` |
| Federation: central record locator, Ed25519-signed requests, signed content-hash check | complete for a demo | `backend/mpi/main.py`, `app/mpi_client.py`, `routers/federation.py` |
| Emergency QR/NFC scan, scoped fields, rate-limited | complete | `routers/emergency.py` |
| Sealed NFC tag (AES-256-GCM, UID-bound AAD, expiry) | complete | `app/tag_crypto.py` |
| Offline-read log upload, hash-chained per device | complete, weak integrity (see §5) | `routers/emergency.py` (`/emergency/offline-reads`) |
| PDPA consent ledger, data-subject requests, retention scan | complete; `cross_facility_sharing` now gates federation (see §4 gap 1) | `routers/pdpa.py`, `models.ConsentRecord` |
| Payments + cashier, PDF/email receipts | complete, **mock gateway only** (needs `APP_ENV=demo`) | `app/payment_providers.py`, `routers/payments.py` |
| Reporting engine, predictive analytics, notifiable-disease filing | complete, facility-local | `app/reporting_engine.py`, `app/predictive_analytics.py` |
| Orders (CPOE), purchasing, forms, PACS/DICOM, HL7 lab inbox | complete | `routers/orders.py`, `purchasing.py`, `forms.py`, `pacs.py`, `app/hl7_listener.py` |
| The University registry eligibility | stubbed: **mock** (`"mock": true`) | `app/campus_registry.py`, `routers/campus_registry_mock.py` |

### Local AI (`app/ai/`)
All inference is local (Ollama). Every feature has a non-LLM fallback.
| Module | Status |
|---|---|
| `summarize.py` handover brief | complete (template fallback) |
| `cds_hint.py` | complete; allergy-conflict check is deterministic |
| `voice_soap.py` | complete (faster-whisper + LLM; raw transcript fallback) |
| `nric_ocr.py` | complete (LLM vision → RapidOCR → Tesseract) |
| `interactions.py` | partial: small demo interaction table plus RxNorm/DailyMed lookups; not a licensed drug database |
| `audit_intelligence.py`, `report_narrative.py` | complete (explains alerts already flagged by rules) |

The Pi central node runs without Ollama, so on that node the LLM features use fallbacks. `docs/not-done-yet.txt` says this has not been confirmed on hardware.

### Web console (`web/src/pages/`)
| Feature | Status |
|---|---|
| Reception (incl. NFC card tab), Register, PatientList/Detail, Orders, Pharmacy, Ancillary, Dental, Billing, Cashier, Catalogue, Purchasing, Reporting, Forms, Security, AdminConsole | complete |
| Waiting-room TV with chime and spoken calls (`WaitingRoomDisplay.jsx`) | complete; speech is English only |
| Web i18n | **absent** (English only) |
| Web accessibility | partial: some aria; `docs/not-done-yet.txt` says contrast, keyboard and screen-reader not reviewed |

### Flutter app (`mobile_flutter/lib/`)
| Feature | Status | Notes |
|---|---|---|
| Languages en / ms / zh / ta | complete | `l10n/app_*.arb`, `providers/locale_provider.dart` |
| Senior Mode (high-contrast, 2-3 giant buttons, own language switcher) | complete | `screens/senior/*` |
| Large text | partial | follows system size, clamped at 1.3 (`main_shell.dart`); no in-app control |
| Screen-reader / accessibility review | absent | |
| Child mode / guardian screens | **absent** | |
| Self-registration with NRIC scan | complete | |
| Booking (incl. vaccination and chronic follow-up categories), bills, queue status, reminders, announcements | complete | `book_appointment_screen.dart`, `my_bills_screen.dart`, `queue_status_screen.dart`, `reminders_screen.dart` |
| Vitals | partial: read-only per visit; no home logging | |
| Offline | partial: NFC emergency read only | `tag_crypto.dart`, `offline_read_log.dart` |
| NFC emergency scanner (online and offline) | complete | `emergency_scanner_screen.dart`, `nfc_service.dart` |
| Write offline tag (staff) | partial: manual paste-and-write | `write_offline_tag_screen.dart` |

### Not present at all
Vaccination module / immunisation tracking, child growth records, home health
logging, transport of any kind, wellness or health-education content,
community feed, volunteering, sustainability or energy measurement, NTAG 424 DNA
tamper counter.

## 3. Mapping to the brief

| Brief item | Fit | What supports it | Honest weakness |
|---|---|---|---|
| 01 Community wellbeing | weak-moderate | Facility announcements pushed to the app; notifiable-disease filing | Announcements are clinical (e.g. a flu drive), not a community feed. Nothing about residents helping residents. |
| 02 Safety and security | **strong** | Emergency card readable with no network; scoped to emergency fields; hash-chained audit log; PDPA tooling; local AI, nothing leaves the site | Offline revocation is absent; stolen unlocked responder phone can read cards (§5). |
| 03 Accessibility and inclusion | **moderate** | Senior Mode; four languages in the app; NFC and QR alternatives | Web is English-only; accessibility never reviewed; no child mode; no in-app font control. |
| 04 Getting around | none | none | No transport, ambulance dispatch or appointment travel feature. Do not claim it. |
| 05 Digital living | moderate | App for booking, bills, queue; online payments; e-receipts | Payments run on a mock gateway; only the app is a digital channel. |
| 06 Feeling connected | none | none | No neighbour, volunteer or community feature. |
| 07 Healthy lifestyles | weak | Booking categories for vaccination and chronic follow-up | No wellness, education, vaccination tracking or growth records. |
| Planet (all) | none or incidental | Digital bills and a card instead of paper; small on-prem footprint (Pi config) | No measurement, no energy/waste/water claim. The Pi stack has never been built on ARM64. Claim "less paper" only if you can show a number. |

## 4. Gaps for the township story

Ordered by how much each damages the pitch.

1. **Per-resident consent for federation. Done.** `routers/federation.py` now requires the patient's `cross_facility_sharing` consent (opt-in; newest ledger row wins) before the requesting hospital looks up or fetches (403, audited `federation_denied_no_consent`) and before the origin hospital serves a peer (404, audited `federation_peer_denied_no_consent`). Visit pointers are also consent-gated now: `mpi_client._publish_job` publishes nothing to central without the grant. Staff record it from a checkbox on the patient's Demographics tab (`components/SharingConsent.jsx`; admin / records officer only, as the API requires). Consent is asked on the New Patient form and recorded by admin, records officer or clinician; a late grant publishes the newest three visits and a withdrawal removes this facility's pointers from central. Still open: each hospital reads its own copy of the ledger.
2. **Guardian consent for minors. Done for sharing consent.** A signed-in patient who is the recorded guardian (`PatientDependant`) of someone under 18 can view and record `/pdpa/consent` for them (ledger source `guardian`, audited). A spouse or ex-partner link never counts as a guardian link. Still open: data-subject requests and appointments for the child, a guardian screen in the app, and a hand-over at 18 (the link is not ended automatically; the age check simply stops allowing it).
3. **Responder role for guard/volunteer. Done.** `POST /admin/responders` creates a named account with a mandatory expiry (capped, default 90 days). `auth.get_current_user` confines the role to the emergency scan, tag keys, offline-read upload and `/auth/*` (403 elsewhere). Expiry is enforced on every request, at login, after MFA and on refresh, and the app stops using cached keys at the account's `valid_until`. Scans are attributed to the account in the audit log. Managed from the admin console's Responders tab. Still open: the responder device still holds the one global key set.
4. **Multi-clinic federation across independent businesses.** No tenant or organisation entity; manual onboarding via `POST /admin/facilities`; central is the trust root unless peers are pinned (`CLARION_PEER_KEYS`); the replay cache is shared through Redis when `REDIS_URL` is set (`mpi/sigs.py`) and falls back to per-process memory if Redis is down; the NRIC pepper is weak against a small NRIC space (OPRF listed as open). Spoke compose shares one DB.
5. **NFC rewrite at clinic visits. Partly done.** The card list now shows `tag_stale` (a digest of what was last sealed for the card against the patient's current critical data) and the web console warns "Card is out of date: register it again to rewrite it". Still open: nothing rewrites the card automatically, there is no read-only lock, and cards registered before this check show no flag.
6. **Township-level anonymised dashboard. Partly done.** Anonymised reports now use a keyed pseudonym (HMAC from `SECRET_KEY`, not a plain hash) and drop any group below 5 rows (`suppressed_groups` in the response). The risk-stratification worklist deliberately shows real names (it is a clinical worklist, not an export). Still open: everything is facility-local; a township view needs cross-facility aggregation and a shared pseudonym key.
7. **Children and elderly without the app.** No child mode; no card-only flow for residents. The card is useful only when a staff device is nearby.
8. **Vaccination and growth records, home vitals.** Booking category only.
9. **Web accessibility and i18n.** Web is English-only and unreviewed.
10. **Planet pillar** has no feature. Decide whether to leave it out.

## 5. Security questions (answered from code)

### 5.1 What data is on the NFC tag? Is it emergency-tier only?

**Yes, emergency-tier only, and no name or NRIC.** `_build_compact_tag_text`
(`backend/app/routers/emergency.py:284`) emits only:

- `BT:` blood type
- `AL:` allergy name and severity
- `MED:` drug name and dose
- `COND:` condition names

It reuses the same scope logic as the online scan, keeps only items flagged
`critical_for_emergency`, and is further limited by the grant's scope. The
default budget is 128 bytes (or the real tag size if the caller passes
`tag_max_bytes`). Truncation drops conditions first, then medications, then
allergies, then blood type. The sealed payload also carries an expiry
(`X:<yyyymmdd>`).

Format (`register_nfc_card`, `emergency.py`): the sealed `tag_blob`,
`C1.<key_id>.<b64url(nonce12 ‖ ciphertext ‖ tag16)>`, AES-256-GCM. The AAD is
`C1|key_id|UID` (`app/tag_crypto.py:73`, used at `:88`), so a blob copied to a
different physical tag will not open.

**Update (plaintext fallback removed).** An earlier version also returned a
plaintext `tag_text` and the web console fell back to it when the blob did not
fit. That is gone: the endpoint no longer returns plaintext, a tag too small
for the sealed record (under 89 bytes) is refused with a 422 before anything is
saved, and the app's Write Offline Tag screen (and `NfcService.writeNdefText`)
refuse anything that is not a whole `C1.` blob. Plaintext tags already in the
field are still read. The web console still sends no `tag_max_bytes`, so it
assumes the 128-byte default and cannot detect a physically smaller tag; the
app's write step reports "too large" in that case.

Other things to know:
- The tag is not locked. No read-only lock appears in the write path.
- The online scan, which is a different path, adds the patient's full name and age (`emergency.py:234`).
- `app/emergency_export.py` is a separate nightly encrypted export for facility hardware and **does** include full name and NRIC. It is not the tag, and it has no per-patient consent behind it.
- NTAG213/215/216 work. The NTAG 424 DNA phase (per-read counter) is not built; `tag_type == "ntag424"` only changes the validity period and a warning.

### 5.2 Who holds the offline decryption key? Can a stolen phone read the card?

**Any signed-in staff or responder device holds it. A stolen, unlocked, signed-in phone can read cards. A resident's own phone cannot.**

- Keys are derived by HKDF-SHA256 from `CLARION_TAG_KEY_SECRET`, falling back to `SECRET_KEY` (`app/tag_crypto.py:58`). Rotating the fallback secret silently orphans every tag in the field.
- There is **one global key set**: no per-facility, per-user or per-patient keys. Any role holder can open any sealed tag.
- `GET /emergency/tag-keys` (`emergency.py:~807-825`) is limited to `admin`, `clinician`, `records_officer` and `emergency_responder`. It is rate-limited to 20 per minute, sends `Cache-Control: no-store`, and each fetch is audited. The `patient` role gets 403 (tested in `tests/test_tag_crypto_offline_reads.py`).
- The phone caches keys in `flutter_secure_storage` (`mobile_flutter/lib/services/offline_read_log.dart`) for `CLARION_TAG_KEY_MAX_AGE_HOURS` since the last refresh (**24 hours by default, was 72**, set by the server). Logout clears them; a 401 or 403 on sync clears them; a mere network error keeps them.
- **Update: biometric / PIN gate.** The app now asks for the phone's fingerprint, face, PIN or pattern (`local_auth`) before it reads the cached keys, then not again for 60 s. A phone with no screen lock cannot read tags offline. Disabling the account on the server still only takes effect on the device's **next successful sync**, so an offline thief who can pass the unlock keeps access until the cache window runs out. This is an app-level check, not a hardware-bound key: a rooted device or extracted secure storage is not stopped by it.
- Offline reads go into a per-device SHA-256 hash chain and are uploaded later, with idempotent, conflict-detected upload. The chain is **unkeyed and client-asserted**: the code's own docstrings (`tag_crypto.py`, `offline_read_log.dart`) say the device owner can wipe or rewrite entries before first upload, and dropped tail entries are undetectable without the 424 DNA counter. `read_at` is device-chosen; the server records skew but does not reject on it.

### 5.3 How does revocation work for a lost card?

**Online: complete. Offline: complete for cards registered after the change.**

- Online: `POST /emergency/nfc/revoke/{id}` sets `revoked = True` and writes an audit row (`emergency.py:~922-941`). `/emergency/nfc/scan` then returns 404 for a revoked or expired card. The raw UID is never stored; only `HMAC-SHA256(OTP_HMAC_KEY, "nfc-uid:" + canonical UID)` plus the last 4 characters (`app/auth.py:183-195`). The scanner falls back to the on-tag record only on a true no-response outage, never on a real 404.
- Offline (**update**): `GET /emergency/tag-keys` now returns a `revocation_key` and the ids of cards revoked and not yet expired. The scanner recomputes `HMAC-SHA256(revocation_key, "rev|UID")` from the UID it reads and refuses a listed card before showing anything. A device only learns of a revocation at its next sync, so the exposure window is at most the key lifetime (24 h by default). Cards registered before this change carry no revocation id (the raw UID is not stored) and must be registered again to be revocable offline; `POST /emergency/nfc/revoke/{id}` now says `offline_revocable: false` for those. An attacker who trips the scan rate limit (429) can still force the offline path.
- A cloned tag (UID and blob copied; UIDs are readable) opens on any device that holds the keys.
- Re-registering a UID re-enables a revoked grant; a UID registered to another patient is rejected.
- The UID-hash key is shared with OTP hashing (`OTP_HMAC_KEY`).

## 6. Cheap changes before submission

Ordered by effort. Items 2 to 5 have since been implemented (see the updates above); 1, 6 and 7 are still suggestions.

1. **Reword the pitch** to what exists: "emergency card read by responder devices, works offline, federated records signed per hospital". "Resident-consented" is now true for federation reads once consent is recorded; do not say "primary no-app interface" for residents.
2. **Wire `ConsentRecord` into federation fetch** (one check in `routers/federation.py`) so the consent claim becomes true for the demo.
3. **Ship a revoked-card list with `/emergency/tag-keys` sync** and shorten the 72-hour key TTL for a visible offline-revocation story.
4. **Gate cached keys behind a device PIN or biometric** in the Flutter secure-storage read.
5. **Scoped guard/volunteer account:** a time-boxed `emergency_responder` with its own limited key epoch, for the safety scene.
6. **Roadmap slide, not code:** a k-anonymised township dashboard (cross-facility counts, minimum cell size, salted or no pseudonyms).
7. **Skip or measure the Planet pillar.** If you claim paper reduction, count paper forms replaced; do not claim energy savings from the Pi config until it has been built and measured.
