---
title: Malaysia Health Regulation
type: research
updated: 2026-08-30
tags: [research, pdpa, moh, mda, compliance, malaysia]
---

# Malaysia Health Regulation

Covers PDPA 2024, MOH reporting, and medical-device regulation as they bear on
 the tender, and the AI features.

## PDPA (Amendment) Act 2024
Phased in through 2025–2026. Changes that touch a clinical system:
- "Data User" → **"Data Controller"**.
- Mandatory **Data Protection Officer**, registered with the Commissioner.
- Mandatory **breach notification** to the Commissioner, and to affected individuals
  where significant harm is likely. A **72-hour** window is the working benchmark
  (official guidance was still settling — *re-check before any formal submission*).
- Penalties raised to **RM 1,000,000 and/or 3 years**.
- **Biometric data is now sensitive personal data** — bears on the NRIC-photo flow and
  any fingerprint check-in.
- **Data processors** now carry direct statutory Security-Principle obligations (not
  only the controller).
- Cross-border: the whitelist is **removed** — transfer allowed where destination law is
  "substantially similar" or gives "adequate protection", with a Transfer Impact
  Assessment expected. **No hard localisation mandate** — but the tender's on-prem
  hosting settles it anyway.

Source: [pdp.gov.my](https://www.pdp.gov.my) + law-firm briefings (Skrine, Mayer Brown,
Deloitte). *Exact clause commencement dates are soft — verify.*

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
