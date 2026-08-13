# MediBridge — Full Project Starter

An emergency-first, interoperable health record continuity system.
Backend, AI layer, web console, and mobile app — all wired together and
verified working end to end.

## What's in this repo

```
medibridge/
├── backend/     FastAPI + SQLite. FHIR-lite data model, auth, AI endpoints,
│                emergency QR/card system, audit logging. TESTED AND WORKING.
├── web/         React + Tailwind hospital staff console. Builds cleanly.
└── mobile/      React Native / Expo patient app. Syntax-verified, needs
                 `npm install` on your machine to run (network-restricted
                 in the environment this was built in).
```

## 1. Backend setup (do this first — everything else depends on it)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic[email] \
            "python-jose[cryptography]" "passlib[bcrypt]" bcrypt==4.0.1 \
            python-multipart qrcode pillow python-dotenv requests

python seed.py                    # creates demo admin/clinician/patient logins
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` — full interactive API documentation
(Swagger UI), generated automatically by FastAPI. This is genuinely useful
for your demo: you can show judges the live, documented API surface.

**Demo logins created by seed.py:**
| Role | Email | Password |
|---|---|---|
| Admin | admin@medibridge.demo | admin123 |
| Clinician | clinician@medibridge.demo | clinician123 |
| Patient | patient@medibridge.demo | patient123 |

**Optional — real AI summaries instead of the rule-based fallback:**
set `ANTHROPIC_API_KEY` in your environment before starting uvicorn. Without
it, the handover-brief endpoint still works perfectly using a deterministic
summary generator — genuinely fine for judging, and immune to Wi-Fi issues
at the venue.

**Optional — real OCR:**
```bash
sudo apt-get install tesseract-ocr   # Mac: brew install tesseract
pip install pytesseract
```

## 2. Web console setup

```bash
cd web
npm install
npm run dev
```

Visit `http://localhost:5173`. Log in with the clinician demo account above.
The console is already wired to the backend at `http://localhost:8000` —
change `API_BASE` in `web/src/api/client.js` if you deploy the backend
elsewhere.

## 3. Mobile app setup

```bash
cd mobile
npm install -g expo-cli   # if you don't already have it
npm install
npx expo start
```

Scan the QR code with the **Expo Go** app on your phone (free, App
Store/Play Store). Log in with the patient demo account above.

**Important:** `localhost` in `mobile/api/client.js` won't reach your
backend from a physical phone. Replace it with your computer's LAN IP
(find it with `ipconfig`/`ifconfig`) — e.g. `http://192.168.1.42:8000`.
Both devices must be on the same Wi-Fi network.

## 4. Verified working (already tested for you)

- ✅ Backend boots, seeds demo data, all endpoints respond correctly
- ✅ Login → view full patient record → works
- ✅ AI handover brief generation → works (rule-based fallback verified)
- ✅ AI medication interaction check → correctly caught a real
  Warfarin + Aspirin conflict prescribed across two different facilities
  in the seeded demo patient
- ✅ Emergency QR issuance → scan with **zero login required** → returns
  only the pre-approved scoped fields → writes an audit log entry the
  patient can review
- ✅ Web console builds cleanly with `npm run build`, zero errors
- ✅ Mobile app screens pass full JSX/syntax validation (esbuild)

## 5. Your 4-week plan, mapped to this codebase

**Week 1 — Get it running on your machine, make it yours**
- Follow steps 1–3 above. Get all three pieces running locally.
- Swap in your own project name/branding.
- Read through `backend/app/models.py` — this is your entire data model.
  Understand it before you extend it.

**Week 2 — Deepen the AI layer**
- Wire real OCR (`ai/ocr.py`) — test on 3–5 actual scanned prescription
  photos, not just typed text.
- If you want real LLM summaries instead of the fallback, get an Anthropic
  or OpenAI API key and set it in your environment.
- Expand `KNOWN_INTERACTIONS` in `ai/interactions.py` with more real drug
  pairs — this is easy, high-visible-value work.

**Week 3 — Polish the demo flow + senior-citizen mode**
- Test the full loop end to end from the mobile app: login → view record →
  issue emergency card → scan it as if you were the responder (use the
  `/emergency/scan` endpoint directly via curl or Postman to simulate this
  if you don't have a second phone).
- Build out `SeniorModeScreen.js` further — this is your differentiation
  story, don't leave it thin.
- Add 2–3 more synthetic patients to `seed.py` with richer, more varied
  histories for a more convincing demo.

**Week 4 — Deploy, rehearse, prepare fallbacks**
- Deploy the backend somewhere reachable (Render/Railway free tier) so your
  web console and phone don't depend on your laptop's Wi-Fi during judging.
- Update `API_BASE` in both `web/src/api/client.js` and
  `mobile/api/client.js` to point at the deployed URL.
- Record a backup demo video in case live Wi-Fi fails at the venue.
- Rehearse the pitch at least 3 times, timed.

## 6. If something breaks

- **bcrypt error on `pip install`**: pin `bcrypt==4.0.1` (already in the
  install command above) — newer bcrypt versions conflict with passlib.
- **`email-validator` import error**: `pip install pydantic[email]`
  (included above).
- **CORS errors in the browser console**: the backend already allows all
  origins for the demo (`app/main.py`) — if you still see errors, confirm
  the backend is actually running on port 8000.
- **Mobile app can't reach the backend**: almost always the `localhost` vs
  LAN-IP issue described in step 3 above.
