# CLARION — change summary (2026-08-27)

Not committed yet. Backend + web + Flutter. Restart `uvicorn` and rebuild the web
app after pulling these; run `python seed.py` once (idempotent — safe on an
existing DB).

---

## Admin console

| Change | Detail |
|---|---|
| **Wards tab merged** | "Ward Capacity" + "Floors" + "Ward Map" → one **Wards** tab with a *Floors / Heat map / Full details* switcher. Heat map = read-only occupancy grid. |
| **Access Control tab** (new) | Roles × pages checkbox matrix. Sets which console pages each staff role can open, per facility. |
| **Hospital Settings tab** (new) | Display name / address / phone / timezone + a "share records with other hospitals" toggle. |
| **Sections tab** (new) | Front-desk registration counters per hospital (General Registration, O&G, ICU, …). Add / rename / deactivate / delete. |
| **Staff Roster** | Section dropdown per receptionist / clinician row (assign them to one counter, or "All sections"). |
| **Waiting Room Displays tab** (new) | Generate a shareable, no-login URL for a big screen in the waiting area. Scope to a section, choose masked or full names, revoke. |
| **Purchase Proposals panel** | In the Inventory tab — approve/reject pharmacist restock requests. |

## Roles & access

- New **`receptionist`** role — by default can only reach the Reception page.
- **Pharmacist** → Pharmacy only. **Clinician / records officer** → Patients + Reception.
- Enforced server-side (real 403), not just hidden links. Admin can change the
  matrix per facility (takes effect on the user's next login).
- **Admin now lands on `/admin`** straight after login; every role lands on its
  own first allowed page.
- Demo account: `receptionist@clarion.demo` / `receptionist123`.
- Receptionist can clock in/out and sees the **Rooms** tab as a read-only
  consultation-room status board. Claiming/releasing a room is clinician-only
  (admin / clinician / records officer) — receptionist and pharmacist can't.
- **Reception sections** — an admin assigns a receptionist (or clinician) to a
  registration counter; that person's Reception console is then hard-scoped to
  their section: queue board, check-in (department forced), ticket actions,
  consultation rooms, and per-patient queue status all filtered. A scoped
  account can't manage the facility-wide self-check-in QR (that tab is hidden).
  Unassigned staff see the whole facility as before. Demo:
  `receptionist@clarion.demo` is pinned to "General Registration".
- **"Now serving" is now per queue line** — calling a number on one counter no
  longer auto-completes the currently-serving patient on another counter
  (each distinct `department`, including none, is its own line). Facilities that
  never set a department are unaffected.

## Clinician workflow

- **One-step session** — a clinician clicks **Start session**, picks a free
  consultation room, and that clocks them in *and* claims the room. **End
  session** clocks out + releases. No separate clock pill for clinicians.
- **Clinician = Patients only** — clinicians no longer have the Reception page.
  Their room + a **waiting-patient board** (bar per patient: queue #, name,
  checked-in time, reason, Call / Complete) now live on the Patients page.
- **Public waiting-room display** — `/display/<token>` is a full-screen,
  no-login page for a TV in the waiting area: NOW SERVING + WAITING, auto-refresh,
  names masked by default. Admin generates/revokes the link in the console.
- **Digital signature** — every staff member has a **/profile** page with a
  signature pad. Saved once, it's stamped automatically on sign-offs.
- **Consultation sign-off** — completing a consultation requires the doctor's
  signature and records a signed outpatient encounter as proof.
- **Record sign-off (works on immutable records)** — a clinician can mark a
  condition **resolved** or a medication **discontinued** even on a record they
  can't edit (another hospital's, or after checkout). It's an append-only signed
  annotation — the original row is never changed. The patient record shows the
  effective state (e.g. "~~active~~ → resolved — Dr X · Hospital Y · date", with
  the signature); the emergency scan hides resolved conditions / stopped meds.

## Pharmacy

- **Search bar** — by name or barcode (hardware scanner types + Enter → jumps to match).
- **Barcode** field per medicine (admin-set).
- **Photo** per medicine — upload (≤2 MB PNG/JPEG/WebP), thumbnails in both consoles.
- **Low-stock banner** — count from `/pharmacy/summary`, click to filter.
- **Purchase approval** — pharmacist restock of a normal item files a *proposal*
  the admin approves; items an admin tags **auto-approved** restock instantly.
  Dispensing stock is unchanged.

## Cross-hospital record safety

- A patient's condition / medication / allergy / encounter can only be **edited by
  the facility that recorded it, and only while the patient is currently there**.
  Otherwise it's read-only — add a new entry to amend. Shown with a lock note in
  the patient record.
- Medication authorship (`recorded_by_facility`) is now separate from the
  prescriber (`prescribed_by_facility`), which can still be an external clinic.
- Hospital Settings "share records" toggle: when off, that facility's records
  (and documents) are hidden from other hospitals — emergency scans still see
  everything and log the override.

## Flutter (patient app)

- **Dark mode fixed** — text was invisible on the dark background; screens now
  use a theme-aware palette. Senior Mode unchanged.
- **App icon** — regenerated from the current CLARION logo (was still the old
  mark) + adaptive icon. Needs a device install to confirm.

---

## Security review fixes (applied)

Earlier waves: AI interaction-check honoured the record-sharing opt-out;
documents filtered by it too; purchase approval can't double-apply on a
double-click; authorship fields can't be rewritten via edit; `nosniff` on image
serve. Reception sections: per-line "now serving", scoped ticket/room actions,
scoped self-check-in QR, scoped per-patient queue status.

Clinician wave: the public waiting-room display no longer shows the free-text
visit reason; a resolved/discontinued sign-off only removes a critical item from
the **emergency scan** when it comes from the record's own authoring facility
(any facility's sign-off still shows in the normal record view); a clinician can
only call / complete / no-show a patient routed to the room they currently hold
(no signing off another doctor's patient); starting a session claims the room
first and rolls back the clock-in if that fails; single-word patient names are
masked on the public screen; the display rate-limit is per-token, not per-IP.

## To do on your side

1. `python seed.py` — adds the receptionist account, the section list + demo
   waiting-room display, a demo signature + resolved-condition sign-off, and
   narrows the stored `clinician` permission row to `["patients"]` (only if it
   was still the old `["patients","reception"]` default). All idempotent, no wipe.
2. Restart the backend so the new login payload, role, and page guards are live.
3. `cd web && npm run build` (or restart the dev server).
4. Flutter: `flutter build apk` + install to check the icon; toggle dark mode.
5. Nothing is committed — review `git status` and commit when ready. Note the
   tree already had unrelated uncommitted work before these changes.

## Known issues

- `mobile_flutter/test/widget_test.dart` fails — pre-existing, from an earlier
  round (expects `CLARION` text, login shows a logo image). Not touched here.
- `allowed_pages` is cached per session — a permission change reaches a user on
  their next login, not immediately.
