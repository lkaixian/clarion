# CLARION — Flutter (Android) patient app

A from-scratch native Flutter port of the patient-facing app in `../mobile`
(React Native/Expo), talking to the same FastAPI backend in `../backend`.
Built with `flutter create`, Dart 3 / null safety, and Provider for state
management.

This README is written with the same honesty policy as the root project
README: **every "verified" claim below was actually run in this
environment; anything not run is explicitly marked as not verified.**

---

## What's implemented

- **Login** (`lib/screens/login_screen.dart`) — email/password against
  `POST /auth/login` (form-urlencoded), token stored with
  `flutter_secure_storage`, demo-credentials hint, and a link to enable
  Senior Citizen Mode before signing in.
- **Home** (`lib/screens/home_screen.dart`) — own patient record
  (`GET /patients/{id}`): conditions, active medications, allergies, recent
  encounters, plus the AI handover brief (`GET /ai/summary/{id}`).
- **Emergency** (`lib/screens/emergency_screen.dart`) — scope checkboxes →
  `POST /emergency/issue` → renders the returned base64 PNG QR
  (`Image.memory`), reference, expiry, and a **Revoke** button
  (`POST /emergency/revoke/{ref}`). Polls `GET /emergency/current/{id}`
  every 5s while open so a card issued/revoked from the **web console or
  another device** shows up here too, QR image included — see "Bug fix:
  no synergy between phone-issued and web-issued QR cards" below.
- **Senior Citizen Mode** (`lib/screens/senior/*.dart`) — a genuinely
  distinct experience, not "Home with bigger fonts": near-black high
  -contrast theme, single-column layout, two giant tiles (Emergency Card /
  My Medications), and the emergency card screen **auto-issues the card the
  instant it opens** — zero scope-picking, at most one tap away from a
  scannable QR code from the home hub. See "Senior Citizen Mode" below.
- **Settings** (`lib/screens/settings_screen.dart`) — runtime-editable API
  base URL (persisted with `shared_preferences`) **and** the language
  picker (English / Bahasa Melayu / 简体中文 / தமிழ்).
- **Audit log** (`lib/screens/audit_log_screen.dart`) — "Who's viewed my
  record?", backed by `GET /patients/{id}/audit-log`.
- **Emergency Scanner** (`lib/screens/emergency_scanner_screen.dart`) —
  reachable from a big red button on the Login screen, **no sign-in
  required** (matches the backend's design: `/emergency/scan` and
  `/emergency/nfc/scan` need no auth). Three ways to look a card up, via a
  segmented control: **Scan QR** (live camera, `mobile_scanner`), **Tap
  NFC** (`nfc_manager`, reads a physical card's UID), or **Type Manually**
  (text entry for either a card reference or an NFC UID). See "Scanning
  and NFC" below for the permissions/hardware story.
- **Real medication + appointment reminders** (`lib/screens/reminders_screen.dart`,
  `lib/services/notification_service.dart`, `lib/providers/reminders_provider.dart`)
  — actual scheduled local notifications (`flutter_local_notifications`),
  not just a static list: active medications get a daily 8am/8pm reminder
  (toggleable per-drug, updates live — see the "toggle not updating live"
  bug fix below), and the patient can add ad-hoc appointment reminders
  (date/time picker, stored locally). A **"Send a test notification now"**
  button fires one immediately, for demo-ability. Handles Android's
  permanently-denied notification-permission state by routing to system
  Settings instead of silently re-asking. A **"Book an Appointment via
  MySejahtera"** button opens the MySejahtera app directly by its
  Play-Store-verified package name (`my.gov.onegovappstore.mysejahtera`,
  via `external_app_launcher`), falling back to its Play Store listing or
  website — see the honesty note in `lib/services/mysejahtera_launcher.dart`
  for exactly what is/isn't confirmed.
- **NFC physical cards** (backend `emergency.py` `/emergency/nfc/*`, web
  console's "NFC Physical Card" section on the patient detail page) — for
  senior citizens/anyone without a smartphone. Staff register a physical
  card's UID against a patient from the **web console**; a responder taps
  it against any NFC-capable Android phone in the app's Emergency Scanner,
  no login needed on either side. See "NFC end-to-end" below.
- **Reception desk check-in + queue number system** (backend
  `routers/reception.py`, web console's new `/reception` page,
  `lib/screens/queue_status_screen.dart`) — a receptionist checks a walk-in
  patient in (by QR card reference, NFC UID, or plain patient ID) from the
  **web console**, and this app shows the patient their own live queue
  status: ticket number, the facility's current "now serving" number,
  people ahead, department/reason, with 5s polling and an explicit empty
  state when there's no active ticket. See "Feature: Reception desk
  check-in + queue number system" below.

### A backend quirk this app works around, on purpose

`GET /ai/summary/{patient_id}` is restricted server-side to
`admin`/`clinician`/`records_officer` roles (see
`backend/app/routers/ai_router.py`) — a `patient`-role token gets a 403.
The reference React Native app already anticipates this
(`getSummary(...).catch(() => ({ handover_brief: "" }))`); this Flutter app
does the same (`PatientProvider.loadRecord` catches the failure and just
omits the "Your Health Summary" card rather than showing an error). This
is **not** a bug introduced here — it's pre-existing backend behavior this
app degrades gracefully around, same as the RN app.

---

## Architecture

```
lib/
  main.dart                    composition root: builds AppConfig, TokenStorage,
                                ApiClient, AuthProvider, PatientProvider,
                                LocaleProvider, RemindersProvider
  app.dart                     MaterialApp, localization wiring, splash + auth gate
  config/app_config.dart       API base URL: compile-time default + runtime override
  services/
    api_client.dart            typed Dio wrapper, one method per backend endpoint
    token_storage.dart         flutter_secure_storage wrapper (token + cached user)
    api_exception.dart         DioException -> friendly ApiException
    nfc_service.dart           nfc_manager wrapper: read a physical card's UID
    notification_service.dart  flutter_local_notifications wrapper: medication /
                                appointment reminder scheduling + test notification
    mysejahtera_launcher.dart  opens MySejahtera by verified package name
                                (external_app_launcher), website fallback
  providers/
    auth_provider.dart         session state, login/logout, senior-mode preference
    patient_provider.dart      patient record, AI brief, emergency card (+ live
                                polling/reconciliation against
                                GET /emergency/current/{id}), audit log, NFC card
                                status
    queue_provider.dart        reception queue status (+ live polling against
                                GET /reception/queue/status/{id})
    locale_provider.dart       persisted language choice
    reminders_provider.dart    which meds have reminders on, appointment list
  models/                      Patient, MBUser, EmergencyCard, AuditLogEntry,
                                AppointmentReminder
  screens/                     one file per screen (see above)
  screens/senior/               Senior Citizen Mode screens
  widgets/                     small shared widgets (SectionCard, LoadingView, ...)
  theme/app_theme.dart         standard palette + a separate SeniorColors palette
  l10n/                        ARB source files + flutter gen-l10n output
```

State management is **Provider** (not Riverpod/BLoC/GetX) — deliberately:
smallest dependency footprint of the mainstream options, and this app only
has a handful of screens and 6 small `ChangeNotifier`s, so anything heavier
would be over-engineering for a hackathon-scale app (and would cost more on
the low-end phones this app targets — see "Built for low-end devices"
below).

---

## Running it

```bash
cd mobile_flutter
flutter pub get
flutter run -d <device-id>          # flutter devices  to list attached devices/emulators
```

### Pointing at your backend

**Compile-time default** (used if nothing else is set):
`https://clarion.larmkx.com/api` - the central node's fixed public name, so a
phone needs no IP address. For an **Android emulator** against a backend on your
own machine, build with `--dart-define=API_BASE_URL=http://10.0.2.2:8000`
(10.0.2.2 is the emulator's alias for the host's `localhost`).

Override at build/run time:

```bash
flutter run -d <device-id> --dart-define=API_BASE_URL=http://192.168.1.42:8000
flutter build apk --debug --dart-define=API_BASE_URL=https://xxxx.trycloudflare.com
```

**Or, without a rebuild:** open the app → tap the settings (gear) icon on
the Login screen (or Home screen) → **API Settings** → paste a new base
URL → **Save**. This is persisted with `shared_preferences` and takes
precedence over the compile-time default on every subsequent request
(`AppConfig` is read fresh by `ApiClient` on every call). This is exactly
the workflow for later: start a Cloudflare tunnel in front of
`backend/`, copy the `https://<random>.trycloudflare.com` URL it prints,
paste it into this screen — no rebuild needed, and you can repeat this
every time the tunnel restarts with a new URL.

On a **physical phone** (not an emulator): use your computer's LAN IP
(`ipconfig`/`ifconfig`) instead of `10.0.2.2`, and make sure the phone and
the machine running `uvicorn` are on the same network — same requirement
as the RN app's `mobile/api/client.js`.

### Demo login

| Role | Email | Password |
|---|---|---|
| Patient | `patient@clarion.demo` | `patient123` |

(Same seeded account as the rest of the project — see `backend/seed.py`.)
Registering an NFC card is staff-only — use the **web console**
(`../web`) with the clinician account (`clinician@clarion.demo` /
`clinician123`) or admin account (`admin@clarion.demo` / `admin123`) to
do that; the patient app can only view/scan cards, not create them.

---

## Senior Citizen Mode

Reachable two ways: tap "Enable Senior Citizen Mode →" on the Login screen
before signing in (persisted, so it reopens in Senior Mode on future
launches too), or toggle it off again from inside Senior Mode
("Switch to Standard View").

This is deliberately **not** the standard Home screen with larger font
sizes. Differences that matter:

- **Different color system** — near-black background with white/yellow
  high-contrast text and a red/green/yellow accent system, instead of the
  pale blue standard theme. This is a legibility choice (contrast ratio),
  not just a "senior-themed skin".
- **Single-column, two-tile home hub** — no scrolling, no list of 6+
  sections to parse. Just "🚨 Emergency Card" and "💊 My Medications", each
  a full-width 140dp-tall tap target.
- **Zero-decision emergency card** — the standard Emergency screen asks
  the user to pick which fields to share via checkboxes; Senior Mode's
  emergency screen skips that entirely and **auto-issues** a card with the
  full recommended scope the instant it opens, so getting a scannable QR
  code is at most one tap from the home hub (`SeniorEmergencyScreen`).
- **Simplified medications list** — big single-column cards, no
  navigation, no secondary actions, just drug name + when to take it.
- **Fully localized** — Senior Mode respects the same 4-language picker as
  the rest of the app (see below), since older non-English-first speakers
  are exactly who this mode is for.

---

## Bug fix: regenerating an emergency QR card

Originally, hitting "Generate QR / Card" repeatedly on the Emergency screen
would issue a brand-new card each time, but the previous card stayed live
(scannable, unrevoked) with no indication anything happened to it — the
user had no way to know an old QR code sitting on a printed card or in a
screenshot was still valid. Fixed at both ends:

- **Backend** (`backend/app/routers/emergency.py::issue_emergency_card`):
  a patient should only ever have one live QR card at a time. Issuing a
  new one now automatically revokes any previous, still-valid QR grants
  for that patient first, and the response includes a
  `previous_cards_revoked` count. (Registered NFC physical cards are
  untouched by this — they're a separate, admin-managed medium.) Verified
  directly against the live seeded database with `TestClient`: issuing
  twice in a row revoked the first card (confirmed the old `card_reference`
  then 404s on `/emergency/scan`), and the second issuance correctly
  reported `previous_cards_revoked: 1`.
- **App** (`lib/screens/emergency_screen.dart`): if there's already a live
  card on screen, hitting Generate now shows a confirmation dialog first
  ("Generating a new one will automatically revoke it — the old QR code
  will stop working immediately"), and after a successful (re)issue shows
  a SnackBar stating exactly how many previous cards were auto-revoked.
  There's also a persistent note under the scope checkboxes saying only
  one card can be live at a time, so the behavior isn't a surprise even
  before the confirmation dialog appears.
- **Web console** (`web/src/pages/PatientDetail.jsx`): this fix surfaced a
  second, related bug — the web console had no way to know a card had
  been revoked/reissued **from the mobile app**, so it kept showing a
  stale QR code until the browser was manually refreshed. Fixed with a
  new read-only, no-side-effect endpoint (`GET /emergency/current/{patient_id}`)
  that the console now polls every 4 seconds; if the currently-active
  card's reference no longer matches what's on screen, the console marks
  it revoked automatically. A **Revoke** button was also added next to
  **Issue Card** (previously the web console couldn't revoke a QR card at
  all). Verified against the live seeded database with `TestClient`:
  issued a card, confirmed the status endpoint reports it active with a
  matching reference, revoked it, confirmed the status endpoint then
  reports `{"active": false}`.

---

## Bug fix: medication reminder toggle not updating live

Reported after real-device testing: switching a medication's reminder
on/off on the Reminders screen didn't visually update the `Switch` until
leaving the screen and coming back (which forces a full reload). Root
cause in `lib/providers/reminders_provider.dart`: `setMedicationReminderEnabled`
mutated the on/off state synchronously, but only called `notifyListeners()`
**once, at the very end** — *after* `await`-ing the OS-level notification
-scheduling calls (`flutter_local_notifications`). If that await was slow,
or threw (e.g. the notification permission wasn't actually granted, or
the plugin wasn't fully initialized), `notifyListeners()` never ran, so
Provider never told the `Switch` to rebuild — until some unrelated action
(re-entering the screen, which calls `load()` → its own `notifyListeners()`)
happened to trigger a rebuild anyway, making it look like the toggle "only
updates when you leave and come back." The same pattern existed in
`addAppointment`/`removeAppointment`, so all three were fixed the same
way: the in-memory state is updated and broadcast via `notifyListeners()`
**immediately**, before any `await`; the slower OS-level scheduling work
happens afterwards, wrapped in `try`/`catch` so a scheduling failure can
never again block or silently swallow a UI update. `syncWithActiveMedications`
was also changed to try/catch per-medication so one failure can't abort
scheduling the rest of the list.

---

## Bug fix: no synergy between phone-issued and web-issued QR cards

The big one, reported after real-device testing. Root cause: the Emergency
screen / `PatientProvider` only ever displayed `emergencyCard`, which was
only ever set as a side effect of *this* device calling
`POST /emergency/issue` itself. There was no equivalent, on the mobile
side, of the web console's `GET /emergency/current/{patient_id}` polling
(added in the previous round to fix the same class of problem on the web
side) — so a card issued from the web console, or a different install of
this app, never showed up on the phone at all, and a revoke/reissue done
elsewhere was invisible too.

**Backend contract change** (landed by a parallel agent working on this
at the same time, verified rather than assumed): `GET /emergency/current/{patient_id}`
now also returns `qr_code_base64` whenever `active: true` — the QR image
is never persisted, it's cheaply re-rendered on every call from the
grant's `card_reference` (the QR content is fully deterministic:
`CLARION-EMERGENCY:{card_reference}`), so a viewer that *didn't* itself
issue the card can still actually display it, not just know it exists.

**App fix**:
- `EmergencyCard.qrCodeBase64` is now **nullable** (`lib/models/emergency_card.dart`)
  — coded defensively against an older server that might not yet return
  the field, rather than assuming ordering with the parallel backend
  change. Added a `qrImageBytes` getter that centralizes the base64
  -decode-or-null logic (previously duplicated across two screens).
- New `ApiClient.getCurrentEmergencyCard(patientId)` → `EmergencyCard?`
  (`lib/services/api_client.dart`), wrapping `GET /emergency/current/{id}`.
- New `PatientProvider.refreshCurrentCard(patientId)` and
  `startCardPolling`/`stopCardPolling` (`lib/providers/patient_provider.dart`)
  — mirrors the web console's `CARD_STATUS_POLL_MS` pattern: polls every 5
  seconds while a card-displaying screen is open, and reconciles
  `emergencyCard` against whatever the backend says is actually live:
  adopts a card issued elsewhere if there wasn't one locally (or a
  different one is now live), and marks the local one revoked if the
  backend no longer reports an active card. Skips reconciliation while an
  issue/revoke request from this device is already in flight, so a poll
  tick can't race with it.
- Wired into `EmergencyScreen` and `SeniorEmergencyScreen`
  (`initState`/`dispose`, using a cached provider reference since Provider
  disallows `context` access inside `dispose()`). `SeniorEmergencyScreen`
  now also checks for an already-live card (issued elsewhere) before
  auto-issuing a redundant new one.

**Verified end-to-end with a `TestClient` script simulating two separate
devices/sessions** (not just read/reviewed — this was the explicit ask,
since previous rounds were each reported "fixed" only to turn out not to
be): logged in once, issued a card as "device A", then — using the *same*
login but modeling "device B never called `/issue` itself" — polled
`GET /emergency/current/{id}` and confirmed it returns `active: true`
with the matching `card_reference` **and** a `qr_code_base64` that is
byte-for-byte identical to the one `/issue` returned (confirming the
deterministic re-render actually reproduces the same image). Then
reissued from "device A" again and confirmed "device B"'s next poll
returns the *new* `card_reference`, proving the reconciliation data is
correct.

**What that TestClient script did NOT verify** (being explicit, per the
"don't imply success from code-reading alone" ask): it proves the backend
contract and data are correct and that the Dart code compiles against it.
It does **not** prove that, on a real phone, opening the Emergency screen
after a card was issued from the web console actually renders the QR
image on screen within ~5 seconds without user action — that requires an
actual device, which this sandbox doesn't have. If you can test this: log
in on the web console and on the phone as the same patient, issue a card
from the web console, then open (or wait ~5s within) the phone's
Emergency screen and confirm the QR appears without touching "Generate."

---

## Bug fix: notification permission "still broken" after a prior denial

Root cause (identified without a device, from reading Android's
documented permission-request behavior — flagged here as reasoning from
docs, not confirmed against real hardware): once the OS runtime
-permission dialog has been shown and denied once, Android will **not
show it again** — `shouldShowRequestPermissionRationale` becomes false,
and any later call to request the permission silently returns "denied"
with **no UI shown at all**. `flutter_local_notifications`' own
`requestNotificationsPermission()` (used previously) can't distinguish
this "permanently denied" state from an ordinary "not decided yet" state
— so if a user denied the prompt once (even by accident, or during
earlier testing of this same app), tapping "Enable" on the
notifications-disabled banner did *nothing visible*, which matches
"still broken" exactly.

**Fix** (`lib/providers/reminders_provider.dart`): switched to
`permission_handler`'s `Permission.notification`, which does expose a
distinct `PermissionStatus.permanentlyDenied`. `ensurePermissionRequested()`
now checks status first; if permanently denied, it stops trying to
re-request (which would be a silent no-op) and instead exposes
`notificationsPermanentlyDenied`, which the Reminders screen's banner
uses to swap "Enable" for "Open Settings" (`openAppSettings()`, opening
this app's system Settings screen — the only way to actually grant it
after a denial). Added a `WidgetsBindingObserver` to `RemindersScreen` so
returning to the app from Settings (`AppLifecycleState.resumed`)
re-checks the permission status automatically, rather than leaving the
banner stuck showing stale state.

**Also added, for demo-ability**: medication reminders fire at fixed
8am/8pm — not something you can wait around for in a live demo. Added a
"Send a test notification now" button (`NotificationService.showTestNotificationNow`,
`RemindersProvider.sendTestNotification`) that fires an immediate,
unscheduled notification, so the whole pipeline (permission → channel →
OS tray) is actually demonstrable on the spot, separate from whether the
permission-denial UX fix above is what was really needed.

**Not verified**: whether Android's permanently-denied behavior actually
manifests and is correctly detected on a real device — this was diagnosed
from Android's documented `shouldShowRequestPermissionRationale` semantics
and `permission_handler`'s own documented `PermissionStatus` values, not
by reproducing "deny the prompt twice, confirm the banner switches to
Open Settings, confirm granting it there is picked up on resume" on
actual hardware. Same for the test-notification button: it compiles and
the underlying `flutter_local_notifications.show()` call is what the
plugin's own docs describe as the correct API for an immediate
notification, but nobody has confirmed a notification visibly appeared
in a real notification shade after tapping it.

---

## Scanning and NFC

**QR camera scanner** (`mobile_scanner`): the "camera permission never
asked" issue was because there was no camera-based scanner at all before —
the original scan screen was text-entry only, so Android had no reason to
prompt. `lib/screens/emergency_scanner_screen.dart` now has a real
`MobileScanner` camera preview; `CAMERA` is declared in
`AndroidManifest.xml` and requested by the plugin the moment the scanner
opens. If permission is denied, the screen shows an explicit "Open
Settings" button (`permission_handler`'s `openAppSettings()`) rather than
a dead camera preview.

**NFC tap scanner** (`nfc_manager`): reads a physical card's UID
(`lib/services/nfc_service.dart`) and looks it up via
`/emergency/nfc/scan`. `NFC` + `android.hardware.nfc` (marked
`required="false"` so devices without an NFC chip can still install the
app) are declared in the manifest. The screen handles all of "NFC
unsupported on this device", "NFC off — turn it on in Settings", and "NFC
on, ready to tap" states explicitly.

**Segmented control** (the "button or slider" ask): `SegmentedButton<_ScanMode>`
at the top of the Emergency Scanner switches between **Scan QR** / **Tap
NFC** / **Type Manually** — all three call the same two backend endpoints
(`/emergency/scan`, `/emergency/nfc/scan`) under the hood.

**Big login-page button**: the small "simulate responder scan" text link
is gone — the Login screen now has a full-width red button ("🚨 Scan
Emergency QR / NFC Card") right below the app title, above the sign-in
form, since this is the flow a responder needs to find in an emergency
without knowing anything about the app.

---

## NFC end-to-end

For senior citizens / anyone without a smartphone, using a physical NFC
card instead of the app entirely:

1. **Staff registers the card** (web console, `PatientDetail.jsx` → "NFC
   Physical Card" section → "Register NFC Card"): reads a physical card's
   UID from a USB/phone NFC reader (or its printed UID), picks which
   fields to expose, and registers it against a patient via
   `POST /emergency/nfc/register`. Re-registering the same UID updates the
   existing grant (scope/expiry) instead of creating a duplicate — meant
   for fixing a typo or renewing an expiring card.
2. **A responder taps the card** against any NFC-capable Android phone
   running this app (Emergency Scanner → "Tap NFC" tab, no login) →
   `POST /emergency/nfc/scan` (no auth) → the same scoped fields the QR
   flow returns.
3. **Staff can revoke it** (web console, or `POST /emergency/nfc/revoke/{uid}`)
   if the physical card is lost.
4. **The patient can see (read-only)** whether a card is registered to
   them, on the Home screen's "Physical NFC Card" section — they can't
   register/revoke it themselves, matching how a real hospital would issue
   one.

Backend implementation reuses the existing `EmergencyToken` table (added
a nullable, unique `nfc_uid` column) rather than a parallel table, so scan
-logging/audit/revoke logic is shared between the QR and NFC paths — see
`backend/app/routers/emergency.py::_scoped_fields`. A **lightweight,
idempotent startup migration** (`backend/app/main.py::_migrate_lightweight`)
adds the new column(s) to an already-seeded `medibridge.db` via
`ALTER TABLE` (this project has no Alembic — SQLite + `create_all` is
intentionally minimal for a hackathon-scale app) — it's a no-op if the
columns already exist, and only ever adds columns.

**All of this backend behavior — issue/auto-revoke, scan, NFC
register/update/scan/revoke/list, and the RBAC checks (patient can't
register a card, can't register one for someone else, staff-only revoke)
— was actually executed against the live seeded database** with FastAPI's
`TestClient` in this environment (not just read/reviewed) — see "What was
actually verified" below for the exact assertions run.

**Not verified**: actual NFC hardware. `nfc_manager`'s Android
implementation and the UID-extraction code path
(`lib/services/nfc_service.dart`) were reviewed against the plugin's
source in the local pub cache to get the API right, and the app compiles
and builds correctly, but no physical NFC tag has been tapped against a
real device in this sandboxed environment (no device attached at all —
see "What was actually verified"). The UID hex-format contract between
this app and the web console's registration prompt (uppercase hex, no
separators) is a convention I chose, not something verified against a
particular real card reader's output format — confirm your reader's UID
format matches before relying on it.

---

## Feature: Reception desk check-in + queue number system

A receptionist (any existing staff role — `admin`/`clinician`/
`records_officer`; there is deliberately **no** separate "receptionist"
role/enum value, to avoid an RBAC ripple into `seed.py` and elsewhere)
identifies a walk-in patient by their **existing** emergency QR code
(`card_reference`), a registered physical NFC card (`nfc_uid`), or a direct
`patient_id`, and the system assigns a **per-facility, reset-daily** queue
number. Staff can then see the day's queue, call the next number, and mark
tickets complete/cancelled. Patients see, in this app, their own ticket
number and the facility's current "now serving" number.

**Backend** (`backend/app/routers/reception.py`, `models.QueueTicket`,
new schemas in `schemas.py`, registered in `main.py`):
- `POST /reception/checkin` — staff-only. Resolves the patient via exactly
  one of `patient_id`/`card_reference`/`nfc_uid` (a pydantic
  `model_validator`, not a single-field validator, enforces "exactly one" —
  a field-level validator wouldn't fire at all if every identifier field
  were omitted, since pydantic v2 skips validators on untouched defaults by
  default). `queue_number` is `1 + count of today's (UTC) tickets for this
  facility` — a **count-based, not globally-locked, sequence**; the
  docstring is explicit that a true multi-worker deployment has a small
  theoretical race here, matching how this codebase already caveats
  `EmergencyToken` issuance elsewhere.
- **Critical constraint, verified not just claimed**: identifying a patient
  via `card_reference`/`nfc_uid` is a **pure read lookup** against the same
  `EmergencyToken` table `/emergency/scan`/`/emergency/nfc/scan` use — it
  never revokes/consumes/mutates that grant. `_resolve_patient` in
  `reception.py` deliberately does **not** hard-gate on
  `revoked`/`expires_at` the way the emergency-scan endpoints do (documented
  inline: that gate exists to protect *medical data* from an unauthenticated
  responder — this endpoint is staff-authenticated already and discloses
  nothing beyond "here is a queue ticket", so a lapsed/revoked card should
  still be usable to *identify* someone at the front desk).
- `GET /reception/queue` — staff-only, scoped to `current_user.facility`
  (same "manager admin, not super admin" pattern as `MedicineInventoryItem`/
  `Ward` in `routers/admin.py`) — today's tickets plus computed
  `now_serving`/`waiting_count`.
- `POST /reception/queue/{id}/call` — if another ticket is already `called`
  at this facility, it's **auto-completed first** rather than rejecting the
  call (documented reasoning: in real front-desk use, calling the next
  number *is* the signal the previous one's turn ended — a hard rejection
  would just be an extra forced click with no real benefit).
- `POST /reception/queue/{id}/complete` / `.../cancel` — straightforward
  status transitions.
- `GET /reception/queue/status/{patient_id}` — patient reads only their own
  (403 otherwise); mirrors `GET /emergency/current/{id}`'s `{"active":
  false}` "nothing to show" convention exactly. Returns `now_serving` and
  `people_ahead` (count of `waiting` tickets with a lower number, same
  facility, today).

**Web console** (`web/src/pages/Reception.jsx`, staff-only route
`/reception`, nav link in `Layout.jsx` visible to non-patient roles): a
check-in form (card reference / NFC UID / patient ID text inputs — no
camera scanning library in the web app, that's what this Flutter app's
scanner is for) and a queue board that polls `GET /reception/queue` every
4s (`QUEUE_BOARD_POLL_MS`, matching `PatientDetail.jsx`'s
`CARD_STATUS_POLL_MS` naming/pattern), with a big "Now Serving" display and
Call Next / Complete / Cancel buttons.

**This app** (`lib/models/queue_ticket.dart`, `lib/services/api_client.dart`
`getQueueStatus`, `lib/providers/queue_provider.dart`,
`lib/screens/queue_status_screen.dart`): a new small standalone
`ChangeNotifier` (`QueueProvider`), matching this app's "several small
providers, not one big store" architecture — `startPolling`/`stopPolling`
mirror `PatientProvider.startCardPolling`/`stopCardPolling` exactly,
including the immediate first refresh (don't wait for the first timer
tick) and updating state + calling `notifyListeners()` **before** the
`await`, not after (same fix documented in "Bug fix: medication reminder
toggle not updating live" above). `QueueStatusScreen` shows "Your number:
N" / "Now serving: N" / "N people ahead of you" prominently, ticket
status/facility/department/reason, and an explicit empty state ("No active
queue ticket — check in at reception") when `active: false`. Reachable from
a new tile on the Home screen, next to the Reminders/Audit Log buttons.
`QueueProvider` is registered in `main.dart`'s composition root and
`app.dart`'s `MultiProvider`, alongside the existing providers.

**Verified, not just reviewed** — a `TestClient` script run directly
against the live seeded `backend/clarion.db` (see "Backend verification"
below for the exact scenario): logged in as the seeded clinician, issued a
fresh emergency QR card and registered an NFC card for the seeded demo
patient, then checked that patient in via **all three** identifier types
(`card_reference`, `nfc_uid`, bare `patient_id`) and confirmed the queue
number incremented 1 → 2 → 3 correctly; called ticket 1, confirmed the
patient's own `GET /reception/queue/status/{id}` reflected `now_serving`
correctly; called ticket 2 and confirmed ticket 1 was auto-completed;
confirmed `people_ahead` was computed correctly for the still-waiting
ticket; completed/cancelled the remaining tickets and confirmed the
patient's status correctly went back to `{"active": false}`; **and, the
actual point of the exercise — confirmed the emergency QR card and the NFC
card used to check the patient in were both still `active`/unrevoked
afterwards** (`GET /emergency/current/{id}` still reports `active: true`
with the *same* `card_reference`; `GET /emergency/nfc/{id}` still reports
`revoked: false` for that UID) — proving the "must not consume the
emergency credential" constraint actually holds, not just that the code
reads like it should. Also confirmed a `patient`-role token gets a clean
`403` on `POST /reception/checkin` and on `GET
/reception/queue/status/{other_patient_id}`, and that the "exactly one
identifier" validator correctly `422`s both zero-identifiers and
two-identifiers requests.

**What was NOT verified**: real on-device NFC/QR reception check-in flow —
same caveat as the rest of this app's scanning story (see "Scanning and
NFC" above). This round only exercised the backend contract via
`TestClient` and confirmed `web/`'s build and this app's `flutter analyze`/
`flutter build apk --debug` all succeed against the new code; nobody has
tapped a real physical NFC card or scanned a real QR code at a reception
desk with this feature, and the `QueueStatusScreen`'s on-device rendering
(polling cadence feel, text wrapping for longer department/reason strings,
CJK/Tamil glyph rendering of the new strings) has not been visually
confirmed on a real screen, matching every other "not visually confirmed on
a real device" item already listed under "Not verified by me in this
sandbox" below.

---

## Bug fix: reception queue race condition, wrong reset timezone, and a dead status

An architect-review pass on the reception/queue feature above confirmed its
3 critical safety properties (emergency-card non-mutation, RBAC, facility
scoping) were correct, but found 4 real issues, all fixed in the same
session, all re-verified — not just re-read — afterward:

**1. HIGH — genuine queue-number race condition, not just a theoretical
multi-worker one.** The original `_next_queue_number` docstring claimed the
count-then-insert race "matters for multi-worker deployments" — that was
wrong. FastAPI runs sync `def` routes (every route in `reception.py` is
`def`, not `async def`) in a threadpool even under a single `uvicorn`
process, and `database.py`'s SQLite engine sets `check_same_thread: False`
— so two concurrent `POST /reception/checkin` calls on different threads,
in a genuinely single-worker dev setup, really could both read the same
`COUNT(*)` before either commits and get handed the same `queue_number`.
Fixed with a real DB-level guarantee, not just tighter application logic:
`models.QueueTicket` gained a `UniqueConstraint(facility_name, queue_date,
queue_number)` (see fix #2 for the new `queue_date` column this also
required), and `routers/reception.py::_create_ticket_with_retry` replaced
the old plain count-then-insert with a bounded (5-attempt) retry loop —
compute the next number, attempt insert+commit, and on `IntegrityError`
(the constraint firing) roll back and recompute. This turns a previously
*silent* duplicate into either a correctly-serialized outcome or, in the
pathological worst case, a clean `409`.

  **Verified with a real concurrency test, not just reasoning about it**:
  a script spun up 12 real Python threads, each independently calling
  `_create_ticket_with_retry` for the same facility/date via its own DB
  session, and asserted the resulting `queue_number`s were exactly `1..12`
  with zero duplicates and zero errors — this reproduced the actual race
  (12 threads really do interleave their `COUNT(*)` reads under the GIL's
  I/O-release points/SQLite's own locking) and confirmed the fix resolves
  it, not just that the code compiles. Separately, also verified the
  constraint itself fires correctly by manually inserting two `QueueTicket`
  rows with an identical `(facility_name, queue_date, queue_number)` tuple
  and confirming the second raises `IntegrityError`.

**2. MEDIUM — the daily reset used UTC midnight instead of Malaysia-local
midnight.** This project's target market is Malaysia (Bahasa Melayu
localization, MySejahtera integration) — UTC+8, no DST. The original
`_utc_today_start()` reset the queue at UTC midnight, which is **8am
Malaysia time** — silently resetting the day's queue numbering mid-morning
while patients were still physically waiting. Fixed with a new
`_malaysia_today()` (`routers/reception.py`), using stdlib
`zoneinfo.ZoneInfo("Asia/Kuala_Lumpur")` (no new import, but see the
`tzdata` note below) to compute Malaysia-local midnight and convert it to
the equivalent naive-UTC instant this app's existing naive-UTC `DateTime`
columns are stored in. `models.QueueTicket` gained a new `queue_date`
column (Malaysia-local ISO calendar date, e.g. `"2026-08-19"`) — checked-in
tickets are now grouped by this stored date rather than a live UTC-range
filter, which is also what fix #1's unique constraint is keyed on. Applied
consistently everywhere a day boundary mattered: check-in's queue-number
computation, `GET /reception/queue`, and
`GET /reception/queue/status/{patient_id}`. The `Asia/Kuala_Lumpur`
timezone is hardcoded, not per-facility-configurable — the right
hackathon-scope call for a single-country demo app today, but documented
inline as something a real multi-region deployment would need to revisit.

  **A real, this-environment-discovered wrinkle**: `zoneinfo.ZoneInfo`
  resolves IANA timezone names from the OS's own tz database on
  Linux/macOS, but **Windows ships no such database at all** — importing
  `reception.py` on this Windows dev machine raised
  `ZoneInfoNotFoundError: 'No time zone found with key Asia/Kuala_Lumpur'`
  until the `tzdata` PyPI package (pure-Python IANA data, no C
  dependencies) was added to `requirements.txt` and installed. This wasn't
  inferred from documentation — it was hit directly while verifying this
  fix, then fixed for real.

  **Verified directly**: a spot-check froze "now" at `2026-08-18 17:30
  UTC` — deliberately chosen because it's already `2026-08-19` in Malaysia
  local time (`01:30 MYT`) while still `2026-08-18` in UTC, i.e. exactly
  the boundary case the old UTC-based logic got wrong — and asserted
  `_malaysia_today()` returns `queue_date == "2026-08-19"` (not
  `"2026-08-18"`) and the correct corresponding UTC instant
  (`2026-08-18 16:00:00`, i.e. Malaysia midnight converted to UTC).

**3. LOW — dead `"serving"` status removed.** `VALID_QUEUE_TICKET_STATUSES`
(`schemas.py`), `QueueTicket.status`'s docstring (`models.py`), and UI
branches in both `web/src/pages/Reception.jsx` and
`mobile_flutter/lib/screens/queue_status_screen.dart` referenced a
`"serving"` status that no endpoint ever actually transitioned a ticket
into — the real flow is only ever `waiting → called → done/cancelled`.
Removed everywhere (schema enum, model docstring/column comment, both UI
files' dead branches, and the now-unused `queueStatusServing` translation
key dropped from all 4 ARB files) rather than leaving a half-implemented
`call → serving → complete` step in the documented contract that the code
never actually offered.

**4. LOW — a day's last `called` ticket can be left stuck if staff never
hit Complete (accepted, not fixed).** If staff call a ticket and then never
call another one AND never manually complete/cancel it, it stays in
`called` state indefinitely — there is no background job to auto-close it.
This is genuinely harmless (fix #2's Malaysia-local `queue_date` filtering
means it naturally drops off every future day's board on its own, and
staff can still manually complete/cancel it any time via the existing
endpoints), so per the review's explicit guidance, no new "auto-close
stale tickets" mechanism was built — just a one-line code comment added
next to `call_ticket` in `reception.py` documenting this as known, accepted
behavior so a future maintainer doesn't mistake it for a bug.

**Migration note**: `models.QueueTicket` is a brand-new table introduced
this same session, with no real patient-facing data in it — only rows from
this session's own `TestClient` verification runs. Rather than adding a
`_migrate_lightweight()` entry to `main.py` for the new `queue_date` column
(the pattern every other schema change in this project follows, to protect
*real* seeded/demo data across restarts), the existing stale
`queue_tickets` table was dropped by hand once from the local
`backend/clarion.db`, and `create_all` recreated it fresh with the corrected
schema (including the new unique constraint, which SQLite can't add via a
plain `ALTER TABLE ADD COLUMN` anyway) on next import. This was a one-time,
this-session-only manual step, not a new migration mechanism — documented
inline in `main.py` right above `app.include_router(reception.router)`,
including an explicit note that any *future* column addition to
`QueueTicket`, once it has real data, would need a normal additive
`_migrate_lightweight` entry like every other table in that file.

**Re-verified end-to-end after all four fixes** (not just re-read): the
full `TestClient` script from the feature's original verification (issue
QR card → register NFC card → 403 checks → validator checks → check in via
all 3 identifier types with incrementing queue numbers → call/auto-complete
→ `people_ahead` → complete/cancel → confirm `{"active": false}` → confirm
the emergency QR **and** NFC credentials used for check-in are still
active/unrevoked) was re-run against the live seeded database and passed
in full, alongside the new concurrency and timezone-boundary checks above.
`web/ npm run build` — 0 errors. `flutter pub get` (gen-l10n) —
**262/262/262/262 keys**, identical across all 4 locales (one fewer than
before, matching the removed `queueStatusServing` key), zero
untranslated-message warnings. `flutter analyze` — 0 errors/0 warnings,
same 6 established `prefer_initializing_formals` info lints as before this
round (no new lint classes introduced). `flutter build apk --debug` —
succeeded.

---

## MySejahtera booking link — honesty note (round 2: real package name)

Round 1 fix (guessed package `com.mysejahtera.government` / a
`mysejahtera://` custom scheme, both wrong) turned out to still not work.
**Round 2**: the real Android package ID —
**`my.gov.onegovappstore.mysejahtera`** — was confirmed against the live
Google Play Store listing
(https://play.google.com/store/apps/details?id=my.gov.onegovappstore.mysejahtera)
and is now a verified fact with a source, not a guess.

`lib/services/mysejahtera_launcher.dart` was rewritten to use the
`external_app_launcher` package's `LaunchApp.openApp(androidPackageName:
'my.gov.onegovappstore.mysejahtera', openStore: true)` instead of
`url_launcher` + a guessed custom scheme — it opens the app directly if
installed, or the Play Store listing for that exact (now-correct) package
if not, with no scheme-guessing involved at all. The
`https://www.mysejahtera.gov.my/` website remains as a final fallback
only if the plugin call itself throws.

**A second, easy-to-miss bug found while wiring this up**: `external_app_launcher`'s
Android implementation checks whether the app is installed by calling
`PackageManager.getPackageInfo(packageName, 0)` directly. On Android 11+
(API 30+), package-visibility filtering makes that call throw
`NameNotFoundException` for *any* package not declared in this app's own
`<queries>` block in `AndroidManifest.xml` — **even if the target app
genuinely is installed** — which would have silently made every launch
attempt report "not installed" and fall through to opening the Play Store
listing instead, looking exactly like "the button doesn't open the app."
Fixed by adding `<package android:name="my.gov.onegovappstore.mysejahtera" />`
to the `<queries>` block.

**What's still unverified**: whether MySejahtera exposes any internal
deep-link scheme for jumping straight to its appointment-booking screen
specifically (rather than just opening the app to wherever it last was)
— no public documentation of one was found, so this launcher only opens
the app itself; the user still navigates to "appointments" inside
MySejahtera themselves. Also unverified, for the same reason as
everything else in this section: whether tapping the button on a real
Android 16 device with MySejahtera installed actually opens it — the
package name is now confirmed correct via the Play Store listing, the
`<queries>` fix addresses a real, documented Android visibility
restriction, and `flutter build apk` succeeds with the new dependency and
manifest entry, but none of that is the same as watching it actually
happen on a phone.

---

## Internationalization

Four languages, wired end-to-end (not stub ARB files):
**English, Bahasa Melayu, 简体中文 (Chinese Simplified), தமிழ் (Tamil)**.

- Implemented with Flutter's official `flutter_localizations` + `intl` +
  ARB files (`lib/l10n/app_{en,ms,zh,ta}.arb`), generated via the built-in
  `flutter gen-l10n` tool (configured by `l10n.yaml`, triggered
  automatically on `flutter pub get` / `flutter run` / `flutter build`
  because `generate: true` is set in `pubspec.yaml`). No hand-rolled i18n.
- Every user-facing string across every screen (Login, Home, Emergency,
  Emergency Scanner, Reminders, Senior Citizen Mode ×3, Settings, Audit
  Log) is pulled from `AppLocalizations` — none are hardcoded English left
  over. 133 keys per locale, confirmed identical across all 4
  (`grep -c "@override" lib/l10n/generated/app_localizations_*.dart` →
  133/133/133/133) with zero `gen-l10n` "untranslated message(s)" warnings.
- The language picker lives in **Settings**, next to the API base URL
  field, and persists the choice with `shared_preferences`
  (`lib/providers/locale_provider.dart`).
- **Translation confidence**: English and Bahasa Melayu are
  straightforward. Chinese Simplified uses standard, common medical/tech
  phrasing. **Tamil** is the one I'm least confident in for a few
  technical/novel-to-everyday-speech terms (Cloudflare tunnels, "emulator",
  "responder") — those specific strings are marked in
  `lib/l10n/app_ta.arb` with `"@key": {"description": "TODO: verify with
  native speaker — ..."}` metadata rather than silently guessing. Look for
  `TODO: verify with native speaker` in that file before shipping this to
  real Tamil-speaking users.

---

## Built for low-end devices

Senior Citizen Mode's entire premise is being usable on the phones seniors
actually own — often older, lower-RAM, lower-storage Android devices. That
shaped several concrete choices, not just Senior Mode's UI:

- **Dependencies kept as minimal as each feature allows**: `dio`
  (networking + interceptors), `flutter_secure_storage`,
  `shared_preferences`, `provider`, `flutter_localizations`+`intl` (ships
  with the Flutter SDK — no extra download weight). No animation/graphics
  libraries, no heavy state-management stack, no custom icon font packages
  (Material icons only, already bundled). The camera/NFC/notifications/
  deep-link features added later necessarily pull in `mobile_scanner`,
  `nfc_manager`, `flutter_local_notifications` + `timezone` +
  `flutter_timezone`, `permission_handler`, and `url_launcher` — each is
  the single, standard, actively-maintained package for that exact job
  (no alternatives stacked on top), and this is reflected honestly in the
  APK size numbers below (camera/ML Kit barcode scanning in particular
  adds real weight — there's no way around that for a real camera
  scanner).
- **`minSdkVersion` left at Flutter 3.44's own default (API 24 / Android
  7.0, 2016)** rather than raised — this project doesn't force it higher.
  (Not lowered below the Flutter-tested default either, since plugin
  compatibility below API 24 isn't guaranteed and an app that fails to
  install is worse than one with a slightly higher floor.)
- **Release build shrinking enabled** (`android/app/build.gradle.kts`):
  `isMinifyEnabled = true`, `isShrinkResources = true`, with
  `android/app/proguard-rules.pro` for the plugins that need explicit
  keep rules. Debug builds intentionally leave these off for fast
  iteration/readable stack traces.
- **Shallow, simple widget trees** — screens are mostly flat
  `Column`/`ListView` structures over a handful of small stateless
  widgets; state is scoped to 6 small `ChangeNotifier`s (`AppConfig`,
  `AuthProvider`, `PatientProvider`, `QueueProvider`, `LocaleProvider`,
  `RemindersProvider` — not one big app-wide store), so a change in, say,
  the emergency card doesn't rebuild the whole widget tree.
- **`flutter build apk --split-per-abi`** is recommended for any real
  release build (see "Building a release APK" below) — ships a
  per-architecture APK instead of one fat multi-ABI APK, which is
  meaningfully smaller on a single device.

---

## Building a release APK later

```bash
flutter build apk --release --split-per-abi
```

The `--dart-define=API_BASE_URL=...` override shown in earlier revisions of
this doc is **optional, not required** — every verified release build,
including this round's, has been run without it, since the Settings
screen's runtime-editable API base URL (see "Pointing at your backend"
above) already covers pointing an already-built release APK at a different
backend with no rebuild. Only pass `--dart-define` if you specifically want
a *different compile-time default* baked in for users who never open
Settings:

```bash
flutter build apk --release --split-per-abi \
  --dart-define=API_BASE_URL=https://your-backend-url
```

`--split-per-abi` produces `app-armeabi-v7a-release.apk`,
`app-arm64-v8a-release.apk`, `app-x86_64-release.apk` separately — install
the one matching the target device's architecture (`arm64-v8a` for
essentially all Android phones from the last ~8 years) instead of shipping
one universal APK.

### Release signing (P1.13)

Without any setup, `flutter build apk --release` above signs with Android's
public **debug key** — `android/app/build.gradle.kts` falls back to it and
prints a loud Gradle warning when it does. That output is fine for local
testing / demo installs but must **never** be distributed as the real
release: anyone can re-sign a package with the same well-known debug key, so
it proves nothing about provenance and Play Console will reject an upload
signed with it anyway.

To sign with a real key:

```bash
keytool -genkeypair -v -storetype JKS -keystore clarion-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias clarion
```

Keep the resulting `.jks` **outside this repo** (password manager / CI
secret store — it's a credential, and losing it means you can never publish
an update under the same `applicationId` again). Then copy
`android/key.properties.example` to `android/key.properties` (git-ignored),
fill in the real `storeFile` path + passwords, and rebuild — `build.gradle.kts`
picks it up automatically and the release variant signs with it instead of
the debug key, no warning. Verified in this environment: a throwaway test
keystore correctly overrides the fallback (`./gradlew.bat -q :app:signingReport`
showed `Variant: release / Config: release` pointing at the test `.jks`);
without `key.properties` present it falls back to the debug key as designed.

---

## What was actually verified in this environment (and what wasn't)

Unlike the React Native app in `../mobile` (which could only be
syntax-checked, per the root README), this environment **does** have a
working Flutter SDK and Android SDK, so more could actually be executed:

- ✅ **`flutter pub get`** — ran successfully, all dependencies (dio,
  flutter_secure_storage, shared_preferences, provider,
  flutter_localizations, intl, mobile_scanner, nfc_manager,
  flutter_local_notifications, timezone, flutter_timezone,
  permission_handler, url_launcher, flutter_lints) resolved with no
  conflicts.
- ✅ **`flutter gen-l10n`** (via `pub get`, `generate: true`) — ran
  successfully; all 4 locale files generated under `lib/l10n/generated/`,
  **139/139/139/139 keys** (grew from 133 this round — QR-synergy,
  permanently-denied-permission, and test-notification strings), zero
  untranslated-message warnings.
- ✅ **`flutter analyze`** — ran successfully: **0 errors, 0 warnings**.
  5 remaining `info`-level lints (`prefer_initializing_formals`) are a
  known false-positive for this codebase's pattern of public constructor
  parameter names mapped onto private fields (needed because Dart named
  parameters with a leading underscore aren't referenceable from other
  files/libraries) — left as-is intentionally, not suppressed.
- ✅ **`flutter test`** (`test/widget_test.dart`, a smoke test that pumps
  `LoginScreen` with real providers and checks the English strings
  render) — **1/1 passed.**
- ✅ **`flutter build apk --debug`** — **succeeded**, re-run after every
  round of fixes including this one (QR-card polling/reconciliation,
  `external_app_launcher` + its `<queries>` manifest entry,
  `permission_handler`-based permanently-denied detection). Core library
  desugaring for `flutter_local_notifications` remains enabled — see
  `android/app/build.gradle.kts`. **Not representative of a real
  install** — Flutter debug APKs bundle unstripped engine binaries for
  every ABI, a JIT snapshot, and unshrunk ML Kit barcode-scanning models;
  see the release numbers below for what a user would actually download.
- ✅ **`flutter build apk --release --split-per-abi`** — **succeeded**,
  re-run after this round's changes, including a new ProGuard keep rule
  for `external_app_launcher` (see `android/app/proguard-rules.pro`).
  Real, representative sizes (essentially unchanged from last round —
  `external_app_launcher` is a small, plain method-channel plugin):
  - `app-armeabi-v7a-release.apk` — **22.1 MB**
  - `app-arm64-v8a-release.apk` — **26.0 MB**
  - `app-x86_64-release.apk` — **28.3 MB**
- ✅ **Every new/changed backend endpoint, executed against the live seeded
  database** with FastAPI's `TestClient` (not just read/reviewed) — see
  "Backend verification" below for the exact commands and output,
  including this round's two-"device" QR-card-synergy round-trip.
- ✅ **Web console** (`../web`) — `npm run build` still succeeds cleanly
  (`vite build`, 0 errors) — unaffected by this round's changes, re-checked
  anyway.

**Round 4 (this round): reception desk check-in + queue number system.**
- ✅ **Backend** — new `models.QueueTicket`/`routers/reception.py` endpoints
  exercised against the live seeded `backend/clarion.db` with `TestClient`
  (not mocks) — see "Feature: Reception desk check-in + queue number
  system" above for the full scenario (all 3 identifier types, queue
  numbering, call/auto-complete, `people_ahead`, 403s, validator 422s, and
  — the actual point of the exercise — confirming the emergency QR/NFC
  credentials used to check the patient in were still active/unrevoked
  afterwards).
- ✅ **Web console** (`../web`) — `npm run build` re-run after adding
  `pages/Reception.jsx`, the `/reception` route, the nav link, and the new
  `api/client.js` functions — **0 errors**.
- ✅ **`flutter pub get`** (triggers `flutter gen-l10n`) — ran successfully
  after adding the 19 new queue-related keys to all 4 ARB files —
  **263/263/263/263 keys**, identical across all 4 locales
  (`grep -c "@override" lib/l10n/generated/app_localizations_*.dart`),
  zero untranslated-message warnings.
- ✅ **`flutter analyze`** — **0 errors, 0 warnings**. 6 `info`-level
  lints total (up from the previously-documented baseline of 5): the same
  5 pre-existing `prefer_initializing_formals` false-positives, **plus one
  new instance of the identical pattern** in the new
  `queue_provider.dart` (a public constructor parameter mapped onto a
  private field, same reasoning as every other provider in this codebase —
  left as-is intentionally, consistent with the existing baseline, not a
  new class of problem). A separate, genuinely new `use_null_aware_elements`
  info lint appeared on 4 lines of **pre-existing, untouched** code in
  `api_client.dart` (`updatePatientProfile`'s body-building map) — not
  caused by this round's changes, most likely a `flutter_lints`/analyzer
  version pulled in transitively by `pub get`. Fixed anyway (rewritten
  using Dart's null-aware map-element syntax, `'key': ?value`) since it was
  a trivial, safe cleanup, rather than leaving an unexplained lint-count
  regression in place.
- ✅ **`flutter build apk --debug`** — **succeeded** (`√ Built
  build\app\outputs\flutter-apk\app-debug.apk`), re-run after all of this
  round's changes (new model/provider/screen/screens wiring, `main.dart`/
  `app.dart` composition-root changes, `home_screen.dart`'s new tile). Same
  harmless KGP-migration warning as every prior round.
- ❌ **`flutter test`** — **could not be run this round**: both directly and
  via the `C:\flutter_sdk` junction workaround, `flutter test` fails during
  Dart's native-assets build-hook step (`Hook exited with a reserved exit
  code: 64` / the same underlying `'D:\New' is not recognized...` class of
  failure documented in "Environment notes specific to this machine" below)
  triggered by the `objective_c` package's build hook — a macOS-only
  transitive dependency (via `path_provider_foundation`) that has nothing
  to do with this app's Android target or this round's actual code changes.
  Notably, `flutter build apk --debug` does **not** hit this same failure
  (it only resolves/builds hooks needed for the Android target), so this
  looks like a `flutter test`-specific native-assets-hook regression in
  this Flutter SDK version, not something introduced by the reception/queue
  feature. Left unresolved and reported honestly rather than silently
  dropped — `test/widget_test.dart` itself was not modified this round and
  there is no reason to believe it would fail if this tooling issue weren't
  in the way, but that is an inference, not a confirmed pass.

**Round 5 (this round): version bump only (`1.2.0+3` → `1.2.0+4`) to give
the already-landed round-4 reception/queue code (which shipped without a
build-number bump alongside it) its own installable build, plus a fresh
release build/verification pass. No app code changed this round.**
- ✅ **`pubspec.yaml`** — `version: 1.2.0+4` (version *name* left at `1.2.0`
  — this is a build-number-only bump for a new build of already-1.2.0
  code, not a version-name change; flagging that judgment call explicitly
  per the task brief rather than silently deciding it).
- ✅ **`flutter analyze`** — ran via `C:\flutter_sdk\bin\flutter.bat analyze`
  (the junction workaround — see "Environment notes specific to this
  machine" below): **0 errors, 0 warnings**, the same **6** pre-existing
  `prefer_initializing_formals` `info`-level lints as the round-4 baseline
  above (`auth_provider.dart` ×2, `patient_provider.dart`, `queue_provider.dart`,
  `api_client.dart` ×2) — identical count, no new lint classes, so the code
  is unchanged from round 4 as expected.
- ✅ **`flutter build apk --release --split-per-abi`** — ran via
  `C:\flutter_sdk\bin\flutter.bat build apk --release --split-per-abi`
  (no `--dart-define=API_BASE_URL=...` override, matching every prior
  verified release build — the Settings screen's runtime override covers
  that need). **Succeeded** in 115.3s. Real, actually-measured
  (`ls -la build/app/outputs/flutter-apk/`) sizes — slightly larger than
  round 3's numbers above (the round-4 reception/queue feature — new
  model/provider/screen, 19 new ARB keys ×4 locales — added real code
  between that measurement and this one; this round's own build has no
  new dependencies over round 4, so the growth is attributable to that
  already-landed feature, not to anything this round changed):
  - `app-armeabi-v7a-release.apk` — **24,363,855 bytes ≈ 23.2 MB**
  - `app-arm64-v8a-release.apk` — **28,428,509 bytes ≈ 27.1 MB**
  - `app-x86_64-release.apk` — **30,886,104 bytes ≈ 29.5 MB**
  - `android/local.properties` was regenerated by this build with
    `flutter.versionCode=4` / `flutter.versionName=1.2.0`, confirming the
    `pubspec.yaml` bump actually flowed through to the Android build
    metadata Gradle used.
- ❌ **`flutter test`** — not re-attempted this round; still expected to hit
  the same unrelated native-assets/`objective_c` build-hook failure
  documented under "Round 4" above (no dependency or SDK change happened
  this round that would affect it).
- Not re-run this round (no backend/web code changed): backend `TestClient`
  suite, `web/ npm run build`. Both were last verified in round 4 above and
  nothing in `backend/` or `web/` was touched this round.

### Not verified by me in this sandbox (no emulator/device attached here)

This sandbox never had an Android emulator or physical device attached
(`flutter devices` only shows Windows-desktop and Edge-web targets), so
everything below was only compiled/built/code-reviewed by me, not run —
**however, the app's developer has tested this build on a real Android 16
device across three rounds now** and reported back what actually works
and what didn't; those reports are what drove every bug fix documented
above. I'm keeping this list intact and explicit about *which round* each
item was last confirmed in, rather than marking things "verified" based
on a chat message alone or letting an old "confirmed working" claim imply
this round's changes were also re-confirmed on-device (they weren't —
only re-verified by me, via `TestClient`/`flutter analyze`/`build`, as
detailed throughout this doc).

- **Login / view record / issue / revoke** — confirmed working on-device
  in round 1.
- **Camera QR scanning** — confirmed working on-device in round 1 (this
  is what surfaced the original "camera permission never asked" issue,
  fixed that round).
- **The medication reminder toggle** — confirmed *broken* on-device in
  round 2, fixed (see "Bug fix: medication reminder toggle" above), **not
  yet re-confirmed on-device** after the round-2 fix.
- **The MySejahtera deep link** — confirmed *broken* on-device in round 2
  (wrong package name/scheme), fixed again in round 3 with a verified
  package name (see the dedicated honesty note above), **not yet
  re-confirmed on-device** after either fix.
- **QR-card synergy between the phone and the web console** — confirmed
  *broken* on-device in round 3 (this message). Fixed with real,
  `TestClient`-verified backend/data-layer changes (see the dedicated bug
  -fix section above), but **the actual on-device experience — opening
  the Emergency screen and watching a web-issued card's QR appear without
  touching "Generate" — has not been confirmed**, only the data contract
  it depends on.
- **The notification-permission "permanently denied → Open Settings"
  flow** — diagnosed from Android's documented permission-request
  behavior (not from an on-device repro of this specific symptom), fixed
  in round 3, **not verified on-device at all** — see the dedicated
  bug-fix section above for exactly what is and isn't confirmed.
- **The "send test notification now" button** — new in round 3, compiles
  and builds, **not verified to actually produce a visible OS
  notification** on any device.
- **NFC tap scanning on real hardware** — still not independently
  confirmed either way as of the last report, across all three rounds.
  `nfc_manager`'s Android implementation and the UID-extraction code path
  (`lib/services/nfc_service.dart`) were reviewed against the plugin's
  source in the local pub cache to get the API right, and the app
  compiles/builds correctly, but nobody has confirmed a physical NFC tag
  scan end-to-end yet. See "NFC end-to-end" above for the specific
  caveat about the UID hex-format convention.
- **All 4 languages' actual on-screen rendering** — the ARB files parse
  and `gen-l10n` produced clean Dart for all 4 locales with no missing
  keys, but nobody has visually confirmed CJK/Tamil glyph rendering,
  text overflow, or line-wrapping on a real screen. Given the amount of
  text in some strings (e.g. `emergencyDesc`, `responderScanDesc`), check
  for overflow on small screens before a real demo.
- **Release build correctness at runtime** — the release build itself is
  verified (succeeded, installable APKs produced), but **not** actually
  *installing and running* that release APK on a device. ProGuard keep
  rules are based on reading each plugin's known reflection usage; R8
  shrinking occasionally breaks something at runtime that still compiles
  fine, so confirm login / emergency-card-issuance / camera scan / NFC
  scan / secure-storage all still work on a real release-mode install
  before relying on it for a demo.
- **A physical device / LAN-IP / Cloudflare-tunnel run** — untested by
  necessity (no tunnel is running per the task brief); the Settings
  screen's override mechanism has been code-reviewed, not exercised
  against a real tunnel URL.
- **(Round 4) Reception desk check-in + queue number system, on-device** —
  the backend contract (via `TestClient`), `web/`'s console page, and this
  app's `QueueStatusScreen`/`QueueProvider` all compile and the backend
  behavior is genuinely verified (see the dedicated feature section
  above), but nobody has actually checked a real patient in at a real
  reception desk (web console) and watched their queue number/`now
  serving`/`people ahead` appear and update live on a real phone running
  this screen — same "not yet confirmed on real hardware" caveat as every
  other feature in this list. The 5-second polling cadence, and text
  wrapping for a long `reason`/`department` string on a small screen, are
  also unconfirmed visually.

### Backend verification (actually run, not just reviewed)

Run from `backend/` with `python -m pip install fastapi "uvicorn[standard]"
sqlalchemy "pydantic[email]" "python-jose[cryptography]" "passlib[bcrypt]"
bcrypt==4.0.1 python-multipart qrcode pillow` (installed successfully in
this environment), then exercised directly against the **existing, already
-seeded** `medibridge.db` via `fastapi.testclient.TestClient` — no mocks:

- Logged in as the demo patient; issued an emergency card twice in a row.
  First issuance auto-revoked 11 stale grants left over from earlier
  manual testing in this same session (proving the auto-revoke-on-reissue
  fix actually queries and revokes real rows, not just the count from the
  immediately-previous call); second issuance correctly reported
  `previous_cards_revoked: 1`. Confirmed the first card's reference then
  correctly 404s on `/emergency/scan` ("Invalid or expired emergency
  card"), and the second (current) card's reference correctly returns the
  scoped fields.
- Logged in as the demo clinician; registered an NFC card
  (`POST /emergency/nfc/register`), re-registered the same UID with a
  different scope and confirmed it **updated in place** rather than
  duplicating, scanned it with **no auth** (`POST /emergency/nfc/scan`)
  and got back the correct scoped fields, listed it via
  `GET /emergency/nfc/{patient_id}` as both staff and the patient
  themselves, confirmed a patient **cannot** register a card
  (`403 Forbidden`), revoked it (`POST /emergency/nfc/revoke/{uid}`), and
  confirmed scanning the revoked UID correctly 404s afterwards.
- The lightweight startup migration (`_migrate_lightweight` in
  `backend/app/main.py`) was implicitly exercised too — the pre-existing
  `medibridge.db` on disk didn't have the new `nfc_uid`/`registered_by`
  columns, and all of the above worked against it without a manual
  migration step or a fresh `python seed.py`.
- **(Added after real-device testing)** `GET /emergency/current/{patient_id}`
  (the new read-only status endpoint powering the web console's live
  polling — see "Bug fix: regenerating an emergency QR card"): issued a
  card, confirmed the endpoint reports `active: true` with the matching
  `card_reference`, revoked it, confirmed the endpoint then reports
  `{"active": false}`. Also confirmed it correctly reflects a card left
  over from an *earlier, unrelated* `TestClient` run in this same
  environment (i.e. it's reading real DB state, not something cached
  per-request).
- **(Added after real-device testing)** `web/ npm run build` re-run after
  the web console changes (live polling, Revoke button) — still 0 errors.
- **(Added after real-device testing)** `flutter analyze` / `flutter test`
  / `flutter build apk --debug` all re-run after the
  `reminders_provider.dart` and `mysejahtera_launcher.dart` fixes — still
  0 errors/warnings, 1/1 test passing, debug build still succeeds.
- **(Round 3)** Simulated "device A issues, device B (which never called
  `/issue` itself) discovers it" for the QR-card-synergy fix: issued a
  card, then fetched `GET /emergency/current/{patient_id}` as if from a
  second device and confirmed `active: true`, the matching
  `card_reference`, **and** a `qr_code_base64` that is byte-for-byte
  identical (`assert`ed, not eyeballed) to what `/emergency/issue`
  returned for the same card — proving the deterministic QR re-render
  actually reproduces the same scannable image, not just a
  structurally-similar one. Then reissued from "device A" again and
  confirmed "device B"'s next poll returns the new `card_reference`.
- **(Round 3)** Full backend syntax + `TestClient` round-trip (issue →
  poll active/matching → revoke → poll inactive) re-run one more time
  after all round-3 files were finalized, as a final consolidated check
  — passed.
- **(Round 3)** `flutter analyze` / `flutter test` / `flutter build apk
  --debug` / `flutter build apk --release --split-per-abi` / `web npm run
  build` all re-run after every round-3 change (QR polling/reconciliation
  in `patient_provider.dart`/`emergency_screen.dart`/`senior_emergency_screen.dart`,
  `external_app_launcher` + manifest `<queries>` fix, `permission_handler`
  -based permanently-denied detection, test-notification button, 6 new
  ARB keys ×4 locales) — 0 errors/warnings (same 5 pre-existing `info`
  notices), 1/1 test passing, all four build commands succeeded.
- **(Round 4)** New reception desk check-in + queue number system, run
  against the live seeded `clarion.db` with `TestClient`: logged in as the
  seeded clinician and patient; as the patient, issued a fresh emergency
  QR card (`POST /emergency/issue`); as the clinician, registered an NFC
  card for the same patient (`POST /emergency/nfc/register`); confirmed a
  `patient`-role token gets `403` on `POST /reception/checkin` and on
  `GET /reception/queue/status/{other_patient_id}`, and that omitting all
  three identifiers or supplying two at once both `422` with the exact
  "Provide exactly one of..." message; checked the patient in three times
  as the clinician — once via `card_reference`, once via `nfc_uid`, once
  via bare `patient_id` — and asserted `queue_number` incremented `1 → 2 →
  3` and `source` was recorded correctly (`qr`/`nfc`/`manual`) each time;
  fetched `GET /reception/queue` and confirmed `waiting_count == 3` and
  `now_serving is None` before anything was called; called ticket 1 and
  asserted the patient's own `GET /reception/queue/status/{id}` reported
  `now_serving` matching ticket 1's number; called ticket 2 and asserted
  (a) ticket 1's status flipped to `done` with a `completed_at` set (the
  documented auto-complete-on-next-call behavior) and (b) the still-waiting
  ticket 3's `people_ahead` was correctly `0` (tickets 1/2 no longer count
  as `waiting`); completed ticket 2 and cancelled ticket 3, then asserted
  the patient's queue status returned to `{"active": false}`; and —
  **the actual point of the exercise** — asserted
  `GET /emergency/current/{patient_id}` still reported `active: true` with
  the exact same `card_reference` used for check-in, and
  `GET /emergency/nfc/{patient_id}` still reported `revoked: false` for
  the same `nfc_uid`, proving reception check-in genuinely never mutates
  the underlying `EmergencyToken` grant. All assertions passed.
- **(Round 4)** `web npm run build`, `flutter pub get` (gen-l10n),
  `flutter analyze`, and `flutter build apk --debug` all re-run after
  every round-4 change — see the dedicated "Round 4" bullet list further
  above for exact results (all passed except `flutter test`, which could
  not be run this round due to an unrelated native-assets tooling failure
  — see that same bullet list for details).

If you're picking this up: install/verify an Android emulator or connect
a device (`flutter devices`), start the backend
(`cd ../backend && uvicorn app.main:app --reload --port 8000`), run
`flutter run -d <device>` from `mobile_flutter/`, and log in with the demo
patient account above.

### A forward-compat warning you'll see (harmless today)

Every build prints:

```
WARNING: Your app uses the following plugins that apply Kotlin Gradle
Plugin (KGP): flutter_timezone, mobile_scanner, nfc_manager
Future versions of Flutter will fail to build if your app uses plugins
that apply KGP.
```

This did **not** fail the build in this Flutter version (3.44.1) — both
debug and release builds succeeded with it present. It's Flutter warning
that a future SDK version will require these specific plugins to migrate
to its new "Built-in Kotlin" plugin mechanism. Nothing to fix right now;
worth re-checking `flutter pub outdated` for newer versions of these 3
packages before upgrading the Flutter SDK later.

---

## Environment notes specific to this machine

The Flutter SDK on this machine lives at `D:\New folder\flutter` (path
contains a space). The Android SDK lives at `D:\AndroidStudioSDK`; the
shell's `ANDROID_HOME` env var was initially pointed at the Android Studio
*executable* rather than the SDK, so this project's
`android/local.properties` pins `sdk.dir` explicitly
(`sdk.dir=D:\\AndroidStudioSDK`), and `flutter config --android-sdk
"D:\AndroidStudioSDK"` was also run so Flutter's own tool config is
correct independent of any given shell's environment.

**The space in `D:\New folder\flutter` broke two different things, at two
different layers**, both worth knowing about if you hit similar errors:

1. `flutter create` itself failed with `'D:\New' is not recognized as an
   internal or external command` when invoked as a bare `flutter` command
   from Git Bash — worked once the fully-quoted path to `flutter.bat` was
   invoked directly (`"/d/New folder/flutter/bin/flutter.bat"`).
2. `flutter build apk` failed deeper in the toolchain, inside Dart's
   **native assets / build hooks** step (`Target dart_build failed`,
   `'D:\New' is not recognized...`), triggered by transitive dependencies
   of `flutter_secure_storage` (`path_provider_android`'s `package:jni`
   and `path_provider_foundation`'s `package:objective_c`, both of which
   now use Dart's native-assets hook system, and neither of which are
   even needed for an Android-only build — but the hook runner still tries
   to compile hooks for every resolved package in the graph). This
   reproduced with `--no-enable-native-assets` too — that flag doesn't
   skip the hook, it just makes any package that *needs* one hard-fail
   instead. **Fix used:** created a Windows directory **junction** at a
   space-free path pointing at the real SDK
   (`New-Item -ItemType Junction -Path 'C:\flutter_sdk' -Target 'D:\New
   folder\flutter'`, no admin rights required, unlike a symbolic link) and
   invoked `flutter` via `C:\flutter_sdk\bin\flutter.bat` for the build.
   `android/local.properties`'s `flutter.sdk` line reflects this
   (`C:\\flutter_sdk`) as a result of that successful build. If you clone
   this project onto a machine where your Flutter SDK path has no spaces,
   you won't hit this at all and can ignore the junction entirely — delete
   `android/local.properties` and let `flutter run`/`flutter build`
   regenerate it pointing at your own SDK.
