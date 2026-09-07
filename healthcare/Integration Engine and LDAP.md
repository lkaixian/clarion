---
title: Integration Engine and LDAP
type: research
updated: 2026-08-30
tags: [research, integration, hl7, mirth, ldap, active-directory]
---

# Integration Engine and LDAP

Covers tender clauses **** (device/system integration), **** (lab
analyser API) and **** (LDAP).

## Analyser & device connectivity
- For **1–2 modern analysers**, a **thin HL7 v2-over-MLLP (TCP) service** is enough.
  A full integration engine is for multi-vendor routing at scale.
- Legacy **ASTM E1381/E1394** (serial/RS-232 lab protocols) are where an engine earns
  its keep. **IEEE 11073** is the current point-of-care device standard and maps to FHIR.
- The tender's "configurable service layer / middleware" = this integration
  service.

### Mirth Connect went closed-source
- **v4.6 (19 March 2025)** → single commercial/proprietary licence. Source no longer
  published. ([NextGen announcement](https://www.nextgen.com/blog/industry-news/a-new-era-for-mirth-connect-by-nextgen-healthcare))
- **v4.5.2** = last open-source (MPL) release. No more security patches.
- **[OpenIntegrationEngine (OIE)](https://openintegrationengine.org/)** = community fork
  of 4.5.2, stays MPL 2.0, "fully compatible with Mirth", not affiliated with NextGen.
  This is the live open option if a full engine is ever warranted.

## LDAP / Active Directory
Add as a **second auth provider** next to the existing local accounts:
1. Service-account **bind**.
2. **Search** for the user's DN.
3. **Re-bind as the user** to verify the password.
4. Map AD groups (`memberOf`) → CLARION roles via an admin-editable table.
5. **Just-in-time provision** a local `User` row on first login — no stored password.

- **Python:** `ldap3` (pure Python, RFC 4510 — preferred over `python-ldap` which needs
  C build tools). [ldap3.readthedocs.io](https://ldap3.readthedocs.io/)
- **PHP / CI4:** native `ldap` extension.
- Keep local accounts for break-glass admin, service integrations, and external/family
  patient logins.
- Keycloak is the future SSO seam — not needed for the demo.

Detail: `scratchpad/agy-research-full.md` Part 2 Topic F. See [[On-Prem Architecture]],
[[Sources]].
