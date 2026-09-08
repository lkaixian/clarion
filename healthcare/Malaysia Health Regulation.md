---
title: Malaysia Health Regulation
type: research
updated: 2026-09-08
tags: [research, pdpa, moh, mda, compliance, malaysia]
---

# Malaysia Health Regulation

Covers PDPA 2024, MOH reporting, and medical-device regulation as they bear on
 the tender, and the AI features.

## PDPA (Amendment) Act 2024 — deep dive (2026-09-08, for [[Implementation Roadmap]] P2.10)

Multi-source verified (Skrine ×2, Mayer Brown, DLA Piper, Christopher Lee Ong,
Tay Partners, Rödl, DataGuidance — all 2024–2025 briefings).

**Act A1727**, gazetted 17 Oct 2024, phased: **1 Jan 2025** (admin provisions),
**1 Apr 2025** (Data Controller term, direct processor obligations, biometric =
sensitive, s.129 cross-border, penalties), **1 Jun 2025** (mandatory DPO,
breach notification, data portability).

### Data-subject rights — THERE IS NO RIGHT TO ERASURE
Proposed in PCP 01/2020, **dropped from the final Act**. The 6 rights:
| Right | Section | New? |
|---|---|---|
| Access (+ copy, 21 days +14 extension) | s.30 | no |
| Correction | s.34 (–37) | no |
| Withdraw consent (prospective only) | s.38 | no |
| Prevent processing causing damage/distress | s.42 | no |
| Prevent direct marketing | s.43 | no |
| **Data portability** (machine-readable, controller→controller) | **s.43A** | **YES — the only new right** |

So a "delete my record" flow is **not required**. Withdraw-consent (s.38) is
*prospective* — it stops optional secondary use, not lawfully-held data.

### Clinical records don't even run on consent
Medical/treatment data is **sensitive personal data** (s.4). Processed under the
**s.40 "medical purposes" exception** — s.40(1)(b)(iv): no consent needed when a
healthcare professional processes for medical purposes (s.40(4): diagnosis,
preventive medicine, care/treatment, *management of healthcare services*). Also
s.40 vital-interests + legal-defence grounds.

### Records cannot be deleted on request — retention overrides
- **s.10 Retention Principle:** erase when no longer needed *unless required by
  other law*.
- **PHFSA 1998 (Act 586)** + 2006 Regs + **Limitation Act 1953** (6-yr civil
  claim) mandate retention. **MMC Guideline 002/2006:** records are the
  *facility's property*; patient has access, **not** erasure.
- Retention periods (KKM *Jadual Pelupusan Rekod Perubatan 2016* + Act 586 +
  MMC — figures directionally corroborated, some agy-synthesised, treat as
  design defaults not legal advice):
  | Category | Keep |
  |---|---|
  | Adult out/inpatient | **7 years** from last contact |
  | Paediatric / minor | until age 18 + 7 ≈ **age 25** |
  | Obstetric / maternity | **21 years** from delivery |
  | Deceased | **7 years** post-death |
  | Medico-legal / forensic / litigation | **indefinite** / until exhausted + 7 yr |
  - It's "eligible for **disposal review**", not auto-purge. → P2.10 retention
    config = flag-only batch job (user decision 2026-09-08).

### DPO — MANDATORY for the University
Effective **1 Jun 2025**. Triggered by ANY of: ≥20,000 data subjects; ≥10,000
*sensitive*-data subjects; regular systematic monitoring. **University PKU (~23k
users, all health data) hits both count thresholds.** DPO must be
Malaysia-resident (≥180 days/yr), BM+English, direct access to management,
**registered with JPDP** (business contact details). JPDP *DPO Appointment
Guidelines* 25 Feb 2025 + *Circular 2/2025* 1 Aug 2025.

### Breach notification
≤ **72 hours** to the Commissioner ("as soon as practicable"; justify if
exceeded; forms / `dbnpdp@pdp.gov.my`). Notify **affected individuals within 7
days** of notifying the Commissioner **if "significant harm"** = sensitive data,
risk of financial loss / ID theft / physical harm, **or > 1,000 data subjects**.
*Guidelines on Data Breach Notification*, operational 1 Jun 2025.
Penalty for notification failure: RM250k / 2 yr. General non-compliance:
**RM1,000,000 / 3 yr** (enforceable since 1 Apr 2025).

### Cross-border (s.129) — N/A for CLARION
Whitelist abolished 1 Apr 2025. Now: destination law "substantially similar" OR
"adequate protection", OR statutory exception (consent/contract/vital
interests); **Transfer Impact Assessment** required (CBPDT Guidelines 29 Apr
2025, refresh every 3 yr) + SCCs/BCRs. **CLARION is on-prem with local AI —
nothing leaves Malaysia, so no TIA needed** (this is the same constraint as
[[Security Audit]] C1 / the tender).

### Jurisdiction note
s.3(1) PDPA exempts *federal/state government* bodies. Whether a public
university's health centre counts is a genuine open question (the exemption is
narrow) — **moot**: the tender demands PDPA compliance and CLARION builds to it
regardless. A private/fee-charging PKU falls squarely under the PDPA.

### Earlier summary (still valid)
- "Data User" → **"Data Controller"**; biometric now sensitive (bears on the
  NRIC-photo flow + any fingerprint check-in); processors carry direct
  Security-Principle obligations.

Source: JPDP [pdp.gov.my](https://www.pdp.gov.my) + the law-firm briefings above.
Raw research digest: session scratchpad (2026-09-08 agy research pass).

## MOH / KKM reporting
- **Notifiable infectious diseases** (Prevention & Control of Infectious Diseases Act
  1988, Act 342) → **e-Notifikasi** portal ([enotifikasi.moh.gov.my](http://enotifikasi.moh.gov.my)),
  24 h to 7 days to the District Health Office depending on disease. The Reporting
  module must generate these.
- **HMIS statistical returns** → Health Informatics Centre (attendance, morbidity,
  service provision).
- Private clinics also under the Private Healthcare Facilities & Services Act 1998
  (Act 586), monitored by CKAPS.

## Accreditation — MSQH
[Malaysian Society for Quality in Health](https://msqh.com.my). Voluntary,
ISQua-recognised. **2nd-edition Medical Clinic Accreditation standards, 2024**
(clinical operations, patient safety, infection control, governance). Separate
standards for dental clinics.

## Medical Device Authority — SaMD
Under the **Medical Device Act 2012 (Act 737)**, software with a medical purpose
(diagnosing, monitoring, treating, or driving clinical management) is a regulated
**Software as a Medical Device**.
- **Classification** A–D by intended purpose and how much it drives decisions.
- **Path:** appoint a Local Authorized Representative → Conformity Assessment Body
  reviews the CSDT technical file (IEC 62304 software lifecycle, ISO 14971 risk
  management) for Class B/C/D → submit via **MeDC@St**.
- **Abridged route** if already cleared by US FDA / EU CE / Singapore HSA.
- General wellness apps with no medical claim are exempt.

**Implication for CLARION:** the CDS layer, medication-safety engine
 and lab result interpretation are SaMD if deployed for real.
Out of scope for the competition; a named workstream for the tender. **Keep every AI
output framed as a reference aid to a clinician, never an autonomous decision** — which
is also what the open-weight model licences require ([[On-Prem Clinical AI]]).

Source: [mda.gov.my](https://www.mda.gov.my). Detail: `scratchpad/agy-research-full.md`
Part 1 Topic B.
