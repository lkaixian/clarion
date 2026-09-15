# CLARION — Exhibition Demo Script

A complete, run-it-cold procedure for presenting CLARION live at the
University HealthCare exhibition. Ranked by impact per `healthcare/Implementation
Roadmap.md`'s "Demo priorities" note — this script is that ranking turned
into an actual runbook: setup, exact clicks, talking points tied to tender
clauses, timing, fallbacks, and the Q&A you'll actually get asked.

Core script: **~11 minutes**. Full script with Q&A buffer: **~20 minutes**.
Can be cut down to Scenes 1–2 alone (~3 min) for a walk-by / short slot.

---

## 1. Cast & kit needed

| Role | Who | Device |
|---|---|---|
| Presenter | drives the web console | Laptop, on the venue's own screen/projector |
| "Patient" | shows the phone side | A phone/tablet running the Flutter app (or the Android emulator, less convincing live) |
| Second presenter (optional) | plays "responder" for the emergency scan | Can be the same laptop if solo |

**Network**: the laptop needs its own switchable connection (WiFi toggle or
a pluggable Ethernet cable) — Scene 2 depends on being able to visibly cut
it mid-demo.

## 2. Pre-event setup

### T-1 day (once, at the office — needs internet)
```bash
docker compose --env-file .env.docker up -d --build   # or: local dev per README.md §1
ollama pull llama3.2   # text model — CDS hint, voice-to-SOAP, NL summaries
ollama pull llava      # vision model — NRIC OCR (not in the core script, have it ready anyway)
```
Confirm both models answer locally: `ollama run llama3.2 "hello"` should
respond with **no** internet needed for that call.

Seed / reset demo data if the DB has drifted from a clean state (see § 7
Reset procedure).

**Upload one demo X-ray study for Scene 4 — there is no seeded DICOM
data.** Create an X-ray `ServiceRequest` (Ancillary → order an X-ray for
any seeded patient) and upload a sample DICOM image against it (any
de-identified sample chest X-ray works — see `docs/deployment.md`'s PACS
section for the upload path). Do this once, well before the event; do not
discover a missing study live.

**Issue the demo patient's Emergency Card for Scene 1 — seed.py does not
pre-issue one.** On the phone, log in as `patient@clarion.demo`, open
"Emergency Card", tick the scope checkboxes (blood type / allergies /
medications), and tap **Generate**. This is a real `POST /emergency/issue`
call — do it once ahead of time, not live (re-generating on stage works
too, it's just an extra step you don't need mid-script).

### T-1 hour (at the venue — do this WITH internet, before going dark)
- [ ] Stack is up: `docker compose ps` — everything `Up`/`healthy`.
- [ ] `curl -k https://localhost/healthz` → `{"status":"ok"}`.
- [ ] Ollama is running on the SAME machine/LAN the backend reaches, and
      has already answered once (models are loaded into memory/cache —
      the first real call after a cold Ollama start is slower).
- [ ] Log in as each demo role once (below) to warm up JWT/browser state
      and confirm no password has drifted from the table.
- [ ] Flutter app installed + logged in as the demo patient on the phone.
- [ ] Charge the phone. Seriously.

### T-5 min
- [ ] Web console open, logged OUT, at the login screen (`/login`).
- [ ] Browser zoom at a level the back row can read (Ctrl/Cmd + a few times).
- [ ] Close any dev tools / console panels.
- [ ] Phone unlocked, Flutter app open at the home screen.

## 3. Demo logins

`APP_ENV=demo` only (README.md's own table — reuse it, don't retype):

| Role | Email | Password |
|---|---|---|
| Admin | admin@clarion.demo | admin123 |
| Clinician | clinician@clarion.demo | clinician123 |
| Pharmacist | pharmacist@clarion.demo | pharmacist123 |
| Receptionist | receptionist@clarion.demo | receptionist123 |
| Patient (phone) | patient@clarion.demo | patient123 (or NRIC `520314-01-1234`) |

---

## 4. The script

### Cold open (30s) — don't log in yet

> "This is CLARION — an emergency-first clinic system we built for the University's
> two-campus health centre. Everything you're about to see runs **entirely
> on hardware in this room**. No cloud AI, no external dependency for
> patient care — that's not a slogan, we're going to prove it live in a
> minute."

### Scene 1 — The emergency scan (human moment, lead with it) — ~2 min

*This is on the PHONE, not the laptop — hand it to the person playing
"responder", or narrate while your co-presenter holds it.*

1. On the **patient's** phone (already logged in as `patient@clarion.demo`):
   open **"Emergency Card"** → shows the QR card (issued during setup —
   see § 2's pre-event checklist; it's a real `EmergencyToken`, not
   staged data).
2. On a **second** phone (or the same one, switch accounts, or a laptop
   camera) open **"Scan Emergency Card"** and scan the QR — or key in
   the card reference by hand if you don't want to fumble a live scan.
3. The result appears **with no login on the scanning side** — blood
   type, critical allergies, active critical medications only (not
   everything on file — say this out loud, it's a deliberate design
   choice, not a gap).

**Talking points:**
- "No login needed on the responder's side — a paramedic at the roadside
  doesn't have a campus account. Every scan is still logged and auditable."
- "Only the *critical* subset is shown — a responder doesn't need a
  patient's full history to save their life, and showing less here is
  safer, not a limitation."
- Mention the NFC alternative exists too (physical card tap) for patients
  without a smartphone — don't demo it unless you brought an NFC tag.

### Scene 2 — Offline AI, cable unplugged (the tender requirement differentiator) — ~3 min

*This is the flagship beat. Don't rush it.*

1. On the laptop, log in as **clinician@clarion.demo**.
2. Go to **Patients**, "Start Session" (clock in + claim a room in one
   step), open a queued patient into consultation.
3. **Now physically disconnect the network** — unplug the cable or
   toggle WiFi off, visibly, and say so: *"I am now offline."*
4. Click **"Get CDS hint (on-prem AI, reference only)"** — wait for the
   response (a few seconds on CPU, faster with a GPU). It still works.
5. Add a medication that conflicts with a recorded allergy (any seeded
   patient with an allergy on file — check `PatientDetail` first if
   unsure which one) — the pre-save prescription-screen alert still
   fires, still offline.

**Talking points:**
- "Every AI call you just saw went to a model running on this laptop /
  this rack — not Anthropic, not OpenAI, not any cloud API. Clause
   forbids third-party AI cloud APIs for exactly the reason
  we're demonstrating: this has to keep working when the WAN to Branch, or
  the internet at large, is down."
- "This is advisory, never authoritative — a clinician always signs off.
  We say that about every AI feature in this system, not just this one."
- Reconnect the network once the beat is done (quietly, don't make a show
  of it — Scene 5's dashboard doesn't need to be offline).

### Scene 3 — Voice → SOAP — ~1.5 min

Same consultation screen as Scene 2.

1. Click **"🎙 Dictate SOAP (on-prem AI)"**.
2. Say a short, clearly-enunciated clinical sentence — rehearse this
   exact line beforehand so it transcribes cleanly, e.g.: *"Patient
   presents with a two-day cough, no fever, chest is clear on
   auscultation, advised rest and fluids, review in one week if not
   improved."*
3. Click stop — watch it land in the right SOAP fields (Subjective/
   Objective/Assessment/Plan), not just a wall of text.

**Talking point:** "Still fully offline, still the same local model
family — `faster-whisper` for the audio, the same on-prem LLM to
structure it."

### Scene 4 — DICOM viewer — ~1.5 min

1. Go to **Ancillary** (same clinician login), find/open an X-ray
   `ServiceRequest` that already has a study attached (seed one ahead of
   time if none exists — don't discover this live).
2. Open the viewer — zoom, pan, measure.

**Talking point:** "This is a real DICOM viewer over a real Orthanc PACS
server, not an image preview. Zoom/pan/measure are the actual clinical
primitives a radiologist needs."

### Scene 5 — Dashboard: prediction + operational health — ~1.5 min

1. Go to **Dashboard** — same clinician session, no relogin needed.
2. Point at the patient-flow **prediction** panel and the **operational
   health score** — say what the number means in one sentence, don't
   read every panel.

**Talking point:** "This isn't a lagging KPI screen — it's forecasting
tomorrow's load from today's queue and encounter data, so a facility
manager can staff ahead of a surge instead of reacting to one."

### Scene 6 — Frontdesk: new-patient intake + the University eligibility check — ~2 min

*The newest beat — worth its own slot, but say clearly it's a mock.*

1. No need to re-login — stay on **clinician@clarion.demo** from Scenes
   2–4 (clinician already has this page). `admin`/`records_officer` also
   work; `receptionist` does **not** have access to this screen today —
   don't switch to that login for this scene.
2. Go to **Patients** → **"+ New Patient (One-Click Intake)"**.
3. Type NRIC `000101-01-0001` into the NRIC field.
4. Click **"Check University Eligibility"** — a result appears: *"✓ Eligible
   via SMP (student, Faculty of Computer Science and Information
   Technology) — Ahmad bin Ismail (mock)"*, labeled **"(mock campus
   registry — demo)"**. Full Name auto-fills.
5. Finish the form (DOB auto-detects from the NRIC) and submit.

**Talking points — say this part plainly, don't oversell it:**
- "This is a working integration **boundary** — a real network call, a
  real adapter, a real UI flow — against a clearly-labeled **mock**
  standing in for the University's actual SMP, SMS, and e-klinik panel systems.
  We don't have real specs or credentials for those yet — that's the University's
  own internal infrastructure."
- "The important part architecturally: swapping the mock for the real
  systems, once the University provides an endpoint, is **one environment variable
  change** — `CAMPUS_REGISTRY_BASE_URL` — not a rewrite."
- Try NRIC `951010-05-0003` too if there's time — shows the "not
  eligible / graduated" negative case, which is just as important to
  show as the happy path (proves it's not hardcoded to always say yes).

### Close (30s)

> "Everything you've seen today — the emergency card, the offline AI, the
> DICOM viewer, the prediction dashboard, even this campus eligibility
> check — is running on FastAPI, React, and a local LLM, deliberately
> architected so the eventual PHP CodeIgniter 4 port doesn't have to
> redo the hard parts. Questions?"

---

## 5. Fallback / troubleshooting

| If this happens | Do this |
|---|---|
| Ollama is cold / slow on first call | Warm it up during Scene 1 (run one throwaway CDS-hint call before the audience arrives — see T-1 hour checklist) |
| WiFi/network toggle doesn't visibly "look offline" to the audience | Say it out loud twice — "I've disconnected the network" — the point is the claim, the AI response proves it, not a visual network icon |
| A scene's demo data got used/consumed by an earlier visitor (e.g. the NRIC from Scene 6 is now a registered patient) | Use a different seeded/mock NRIC, or run § 7 Reset between visitor groups if you have a gap |
| The DICOM viewer has no study to open | Skip Scene 4, mention it verbally instead — don't debug live |
| A login fails | Check `APP_ENV=demo` is actually set (README.md) — outside demo mode these passwords don't exist |
| Someone asks to see the source code | Fine to talk through — every dependency in the stack is open-source (`docs/transfer-of-technology.md` § 2); check with whoever owns the GitHub repo before deciding whether to actually pull it up live, its visibility isn't something to assume on stage |
| The whole stack is unresponsive | `docker compose restart backend web` (fast) before a full `down`/`up` (slow) — see docs/operations-manual.md § 5 |

## 6. Anticipated Q&A — answer honestly, every time

| Question | Honest answer |
|---|---|
| "Is the University eligibility check really talking to SMP/SMS?" | No — it's a clearly-labeled mock. We don't have real specs or credentials for the University's internal systems. The integration point is real and built; the data behind it is a stand-in. |
| "Is this the final system, or does it get rewritten?" | This FastAPI/React stack is the competition demo. The tender itself requires a PHP CodeIgniter 4 port for the actual delivery — this demo is deliberately architected (layered, portable schema) so that port doesn't redo the hard design work. |
| "What happens if the AI gives a wrong answer?" | Every AI feature in this system is advisory only — a human clinician always signs off before anything is recorded. We never let a model write to the record on its own. |
| "Is patient data encrypted?" | Yes — TLS in transit, encryption at rest (MariaDB TDE / WORM object storage for documents+imaging), and every access is logged in a tamper-evident hash chain. Happy to show `docs/deployment.md`'s audit-chain section if there's time. |
| "What about the two-campus / Branch setup?" | Built and configured (an isolated edge proxy + an offline emergency-data export for a WAN outage) — not shown live today since it needs two real network sites to demo properly. Ask if you want the architecture walked through. |
| "How much of the tender does this actually cover?" | Point at `healthcare/Compliance Matrix.md` if asked for specifics — don't recite percentages from memory, they change as work lands. |

## 7. Reset procedure (between visitor groups / before the next day)

If the demo DB has accumulated visitor-created patients, appointments, or
queue tickets and you want a clean slate:

```bash
# fresh seed, SQLite demo DB (destructive — wipes everything to the seeded baseline)
cd backend && rm -f clarion.db && python seed.py   # seed.py runs `alembic upgrade head` itself
```

For a MariaDB-backed demo stack, see `backend/db/README.md`'s migration
notes instead — don't drop a shared database without checking who else is
using it.

Re-run the **T-1 hour** checklist (§ 2) after any reset — a fresh DB has
no warmed-up login sessions, and the Emergency Card / DICOM study Scenes
1 and 4 depend on need to be issued/uploaded again from scratch.
