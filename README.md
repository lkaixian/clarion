# CLARION
### *(Clinical Access, Records & Information Operations Network)*

Emergency-first, interoperable health record continuity system. Backend, AI
layer, web console, and mobile app, wired together.

```
clarion/
├── backend/         FastAPI + SQLite. FHIR-lite data model, auth, AI
│                    endpoints, emergency QR/NFC, self-registration (NRIC
│                    OCR), audit logging.
├── web/             React + Tailwind hospital staff / admin console.
├── mobile_flutter/  Flutter patient app (Android) — the maintained mobile
│                    client. See mobile_flutter/README.md for its full
│                    architecture, feature list, and environment notes.
└── mobile/          Legacy React Native/Expo prototype, superseded by
                     mobile_flutter/. Kept for reference only.
```

## 1. Backend (start here — everything else depends on it)

```bash
cd backend
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env   # then edit — see below, this step is required
python seed.py         # creates demo admin/clinician/patient logins
uvicorn app.main:app --reload --port 8000
```

**`backend/.env` is required.** It must set `SECRET_KEY` and `OTP_HMAC_KEY`
(no hardcoded fallback for either, by design) — generate each with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Use two *different* values. Rotating either later invalidates every
issued JWT / in-flight OTP — expected, just means everyone re-logs in.

Swagger UI: `http://localhost:8000/docs`.

**Demo logins** (`seed.py`, only with `APP_ENV=demo` — the shipped
`.env.example` default):
| Role | Email | Password |
|---|---|---|
| Admin | admin@clarion.demo | admin123 |
| Clinician | clinician@clarion.demo | clinician123 |
| Pharmacist | pharmacist@clarion.demo | pharmacist123 |
| Patient | patient@clarion.demo | patient123 (or NRIC `520314-01-1234`) |

Outside `APP_ENV=demo` (any real deployment), `seed.py` never uses these —
it generates a fresh random password per account, forces a password change
on first login, and prints each one to the console exactly once
(Security Audit finding H3).

**Optional integrations** (all degrade gracefully if unset):
- `ANTHROPIC_API_KEY` — real LLM handover summaries + the primary path for
  self-registration's NRIC photo verification. Without it: summaries fall
  back to a deterministic generator (fine), but self-registration's OCR
  step falls back to Tesseract-only and **will not pass** unless Tesseract
  is also installed (see below) — the identity check fails closed rather
  than silently skipping.
- Tesseract OCR fallback: `sudo apt-get install tesseract-ocr` (Mac:
  `brew install tesseract`) + `pip install pytesseract` (already in
  `requirements.txt`).
- Mailgun (`MAILGUN_API_KEY`/`MAILGUN_DOMAIN`) — sends real OTP emails for
  password reset and self-registration. Without it, OTPs are generated and
  logged server-side but not emailed.

## 2. Web console

```bash
cd web && npm install && npm run dev
```

`http://localhost:5173`, log in with the clinician demo account. Wired to
`http://localhost:8000` by default — change `API_BASE` in
`web/src/api/client.js` if the backend is deployed elsewhere.

## 3. Mobile app (Flutter — `mobile_flutter/`)

```bash
cd mobile_flutter
flutter pub get
flutter run -d <device-id>
```

Full setup (SDK path quirks, API base URL overrides, building a release
APK, feature list) is documented in `mobile_flutter/README.md` — read that
before touching this app. Demo login: patient account above.

The legacy `mobile/` (React Native/Expo) app is not actively maintained;
use `mobile_flutter/` unless you specifically need the RN codebase.

## If something breaks

- **bcrypt error on `pip install`**: `requirements.txt` pins
  `bcrypt==4.0.1` — add it explicitly if installing packages by hand.
- **`email-validator` import error**: `pip install pydantic[email]`.
- **`RuntimeError` about `SECRET_KEY`**: `backend/.env` is missing/incomplete
  — see step 1.
- **CORS errors**: unset `APP_ENV`/`CORS_ALLOWED_ORIGINS` defaults to
  allow-all for local dev. If you've locked it down, confirm your web/mobile
  origin is in `CORS_ALLOWED_ORIGINS`.
- **Mobile app can't reach the backend**: `10.0.2.2` (Android emulator) or
  `localhost` won't work from a physical phone — use your machine's LAN IP,
  same Wi-Fi network, set it in the app's Settings screen (no rebuild
  needed) or via `--dart-define=API_BASE_URL=...`.
- **Self-registration always fails at the photo step**: no OCR backend is
  configured — see "Optional integrations" above.
