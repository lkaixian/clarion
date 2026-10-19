---
title: Tender Clauses Section 10
type: reference
updated: 2026-08-30
tags: [tender, uthm, clauses]
---

> Companion to [[UTHM HealthCare Tender]]. Verbatim extract from the .xlsm. Also lives in the repo at `docs/tender-clauses.md`.

# UTHM HealthCare — Tender Technical Schedule (working reference)

Source: `docs/source/062026JadualTeknikalHealthcare.xlsm` (sheet `ben-up-003H`), extracted verbatim.
Tender **UTHM/13(PKU)/P/05/001/2026** — *Supply, Delivery, Installation, Testing,
Commissioning Software for the Development of Patient Information Management System
(UTHM HealthCare) for Pusat Kesihatan Universiti, UTHM Parit Raja and Kampus
Cawangan Pagoh*. Jadual Ketiga — Jadual Teknikal Tender (Perkhidmatan).

Buyer: Universiti Tun Hussein Onn Malaysia (UTHM), Pusat Kesihatan Universiti (PKU),
86400 Parit Raja, Batu Pahat, Johor. Two branches: **PKU Parit Raja** and **PKU
Kampus Pagoh**. Scale: ~20,000 students + 3,000 staff.

> Instruction (R8): the tenderer may NOT write their name or price in the spec
> document. Response column is *SPESIFIKASI YANG DITAWARKAN* — mandatory, must
> state agreement **with commentary**; single words ("Noted"/"Comply"/"Agreed")
> are not acceptable (R19 / 1.1).

This file is a working reference for the compliance matrix in
`docs/uthm-healthcare-plan.md`. Not a deliverable.

---

## 1.0 SUPPLY AND DELIVERY
- **1.1** Written response to every paragraph; specific and detailed; no one-word answers.
- **1.2** Includes supply, delivery, testing, commissioning on-site at PKU UTHM.
- **1.3** State earliest delivery/commissioning date; submit detailed work schedule; UTHM sets install date.
- **1.4** Liquidated damages per tender conditions if not completed in time.
- **1.5** UTHM may accept/reject any extension of the delivery/completion period.
- **1.6** Work permits for professional workers are the vendor's responsibility.
- **1.7** All software to be new; no demonstration or used software accepted.
- **1.8** Spec is the **minimum requirement**; additional/more comprehensive spec by the vendor is welcomed.
- **1.9** Insurance cover costs during the project borne by the vendor.

## 2.0 INSTALLATION, TESTING AND COMMISSIONING
- **2.1** Site visit before support & maintenance period begins.
- **2.2** On-site installation by vendor at no extra cost.
- **2.3** Install site specified by UTHM; vendor visits to assess power/water; supplies any extra electrical devices to local standard.
- **2.4** Install/test/commission on-site by a qualified engineer (site advice, electrical connection, levelling, peripheral interfacing, testing to accepted standards, test run); all costs on vendor.
- **2.5** If unsatisfactory, UTHM may refuse handover and hire others at vendor cost.
- **2.6** Vendor justifies competency; submit past experience with similar jobs.
- **2.7** Work permits — vendor responsibility (dup of 1.6).
- **2.8** Spec is minimum requirement (dup of 1.8).
- **2.9** Insurance + unsatisfactory-work remedy (composite of 1.9 / 2.5).
- **2.10** Follow all government regulations during ITC; approvals from authorities are vendor responsibility.
- **2.11** Provide test certificate for the basic system; replace/correct if it deviates from certified results, at vendor expense.

## 3.0 TRAINING
- **3.1** Proper, satisfactory training at vendor's cost.
- **3.2** Minimum training:
  - **3.2.1** ≥20 personnel, ≥5 working days incl. refreshment. Cover: (a) operating the whole system, (b) maintenance & general care, (c) software + misc apps + case study.
  - **3.2.2** Medium of instruction / handouts in English or Bahasa Malaysia.
  - **3.2.3** Suggest additional training if the above is insufficient.
  - **3.2.4** Provide a training schedule proposal for each software tendered.
  - **3.2.5** Conduct a **Transfer of Technology** session on the source code and integration (hardware + software APIs).

## 4.0 WARRANTY PERIOD
- **4.1** State warranty period; quote post-warranty maintenance contract cost.
- **4.2** Warranty **2 years** from complete handover; state warranty terms for equipment + software.
- **4.3** Vendor fixes/replaces any manufacturer/installation defect immediately.
- **4.4** All labour and parts free during warranty; state any exclusions.
- **4.5** Support period for all supplied software **2 years**; issue a guarantee letter.

## 5.0 MAINTENANCE
- **5.1** Full maintenance support available **locally**; competent engineering support; name facilities + locations; outline maintenance scheme.
- **5.2** 1 year free maintenance.
- **5.3** Preventive maintenance **4× / year**; provide maintenance schedule.
- **5.4** On-site and remote support; max response time = next business day.
- **5.5** Contactable about issues via mobile phone (call/WhatsApp) or email.

## 6.0 SPARE PARTS
- **6.1** Not applicable for this procurement.

## 7.0 MANUALS AND DOCUMENTATION
- **7.1** 3 sets (1 original + 2 duplicates) of: (a) Operations manual, (b) Programming manual, (c) Maintenance manual, (d) electrical wiring/circuit diagram if applicable, (e) other special function manual, (f) performance test certificate from manufacturer / recognised body, (g) others.
- **7.2** All documents in Bahasa Malaysia or English.

## 8.0 LICENSE AND OWNERSHIP
- **8.1** Software must be legal; manufacturer's certificate + docs stating **UTHM is the rightful owner**.

## 9.0 OTHERS
- **9.1** Provide complete toolkit for servicing/adjustment/repair.
- **9.2** Complete catalogue + photographs of the proposed completed system.
- **9.3** Guarantee good after-sales service for all supplied packages.
- **9.4** UTHM may reject an offer that fails any clause.
- **9.5** Successful vendor completes and endorses a certificate of completion on handover.

---

## 10.0 TECHNICAL SPECIFICATION

### 10.1 PROJECT SCOPE
- **10.1.1 User Requirement Feasibility Study**
  - **10.1.1.1** Set up User Requirement Study sessions with key stakeholders per UTHM policy.
  - **10.1.1.2** Provide a detailed, comprehensive work implementation schedule.
  - **10.1.1.3** Vendor verifies spec compatibility with no hidden costs; the spec table is a minimum-spec guide.
- **10.1.2** Prepare the **System Requirement Specification Report** and get UTHM verification/approval.
- **10.1.3** Provide a detailed Work Implementation Schedule tailored to PKU UTHM.
- **10.1.4 User Acceptance Testing** — conduct a UAT session with main users for verification/acceptance.
- **10.1.5 Security Acceptance Testing** — system must pass UTHM's security control test.
- **10.1.6 Source Code** — follow correct programming specs; **all source code owned by UTHM**; UTHM has the right to know whether modules are open-source or proprietary.
- **10.1.7 OS Compatibility** — must be compatible with **Linux OS**.
- **10.1.8 Warranty** — **2-year** warranty after FAT signed; action within **24 hours** per report/complaint at no cost.
- **10.1.9 Pre-implementation** — site visit before support & maintenance begins.

### 10.2 PATIENT MANAGEMENT SYSTEM (UTHM HealthCare)
System MUST support multi-user Role & Access Management, split across two branches
(PKU Parit Raja / PKU Kampus Pagoh). Roles:
1. Super Admin  2. Management Admin  3. Health Officer / Dental Officer
4. Medical Assistant  5. Nurses  6. Support (Lab/X-ray/Physiotherapy)
7. Clinic Panel  8. PPO  9. Registrar Officer

#### 10.2.1 Modules (all mandatory)

**10.2.1.1 Dashboard Module**
- **10.2.1.1.1** Summarised data over time for audit reporting: patients in queue, attended, physician availability, patient waiting time.
- **10.2.1.1.2** *Intelligent patient-flow prediction engine* — forecast clinic load for current & next operational day from historical visit patterns, seasonal trends, scheduled appointments.
- **10.2.1.1.3** *Real-time operational health score* — composite index from wait times, physician availability, queue length, unresolved referrals.

**10.2.1.2 Frontdesk Module**
- **10.2.1.2.1** Integrate with **SMP, SMS, e-klinik panel**; new-patient eligibility checks via the Registrar's system.
- **10.2.1.2.2** Pre-Registration — existing patients self-register before visiting.
- **10.2.1.2.3** Patient Management — register/add/delete/update patient details; assign patient to physician; payment method setting.
- **10.2.1.2.4** Appointment — manage appointments, reminders, history, rescheduling.
- **10.2.1.2.5** Staff Management — display available physician & room, logged-in users.
- **10.2.1.2.6** Billing — manage invoice & receipt, payment tracking.
- **10.2.1.2.7** Report & Analysis — patient demography and charges reports.

**10.2.1.3 Consultation Module**
- **10.2.1.3.1** **'Sign' feature** — physician signs off completed patient records.
- **10.2.1.3.2** Patient Management — physician views patient queues, sets appointments.
- **10.2.1.3.3** Consultation — record progress notes, diagnosis, treatment plan, follow-up scheduling.
- **10.2.1.3.4** References — refer patient to physiotherapy, X-ray, laboratory, or outsource physician; review results/feedback after the session.
- **10.2.1.3.5** Medication — prescribe / edit / delete / update medication records.
- **10.2.1.3.6** Reporting Management — lab / X-ray / physio reports, Digital Medical Certificate, Referral Letter, Timeslip, diagnosis.
- **10.2.1.3.7** Billing — physician views/manages consultation fees.
- **10.2.1.3.8** *Clinical decision support layer* — from presenting complaint, vitals, history: differential diagnosis suggestions, drug contraindication flags, evidence-based treatment pathways (reference aids only).
- **10.2.1.3.9** *Intelligent medication safety engine* — screen prescriptions against known allergies, current meds, existing diagnoses; real-time alerts before confirmation.
- **10.2.1.3.10** *Voice-to-clinical-text transcription* — dictate notes into structured **SOAP** fields.

**10.2.1.4 Pharmacy and Inventory Module**
- **10.2.1.4.1** Patient Management — pharmacist views queue & appointments.
- **10.2.1.4.2** Medication dispensing — dispense, history, update, print medication label.
- **10.2.1.4.3** Stock management — dispense from Stock Master & Stock Unit (Inventory), expiry monitoring, vendor details, purchasing & reorder.
- **10.2.1.4.4** Medication records — view/add/update/delete meds issued by physician.
- **10.2.1.4.5** Billing — view/manage total charges per patient.

**10.2.1.5 Admin Module**
- **10.2.1.5.1** User Account Management — add/edit/update user details, password reset, roles, access monitoring, change notification.
- **10.2.1.5.2** Patients Management — manage patient details, view history/appointments.
- **10.2.1.5.3** Appointment — manage slots, send reminders.
- **10.2.1.5.4** Billing — invoices, access all patient details; integrated with SMP, SMS, e-klinik panel.
- **10.2.1.5.5** Report & Analysis — patient medical info reports, data export.
- **10.2.1.5.6** System Configuration — notification settings, content/text/appearance edits.
- **10.2.1.5.7** Security Management — data recovery / backup, security protocol.

**10.2.1.6 Billing Module**
- **10.2.1.6.1** Patient Details — view patient details and visit history.
- **10.2.1.6.2** Payment and Charges — generate invoice/receipt, handle payment.
- **10.2.1.6.3** Billing Management — payment history & charges, add/update/delete claims.

**10.2.1.7 Procedure Module**
- **10.2.1.7.1** Procedure Management — receive registered patient from Frontdesk or physician order; insert clinical indication; sign off procedures.
- **10.2.1.7.2** Clinical Management — add/update/delete assessment, plan, progress notes.
- **10.2.1.7.3** Procedure Parameter Management — add/update/delete procedures & charges.
- **10.2.1.7.4** Reporting Management — patient visit history, data & statistics.

**10.2.1.8 Laboratory Module** — *enables registering patients directly without consultation or physician order.*
- **10.2.1.8.1** Laboratory Test Management — clinical indications, sign off procedures, patient list + past history.
- **10.2.1.8.2** Test Parameter Management — add/update/delete lab tests, parameters, charges.
- **10.2.1.8.3** Reporting Management — store internal/external lab results (softcopy), sample handling, external lab details, data & statistics.
- **10.2.1.8.4** *Intelligent result interpretation support* — flag critical/abnormal results, suggest follow-up tests, reference-range contextualisation, surfaced before sign-off.
- **10.2.1.8.5** *Longitudinal trend analysis* — compare current results to historical baseline, identify meaningful deviations.

**10.2.1.9 X-ray Module** — *enables registering patients directly without consultation or physician order.*
- **10.2.1.9.1** X-ray Test Management — receive from Frontdesk/physician; clinical indications; sign off; patient list + history.
- **10.2.1.9.2** Test Parameter Management — add/update/delete X-ray tests & charges.
- **10.2.1.9.3** Reporting Management — store X-ray results (softcopy), data & statistics.

**10.2.1.10 Physiotherapy Module** — *enables registering patients directly without consultation or physician order.*
- **10.2.1.10.1** Registration and Appointment — register new physiotherapy session, update/delete appointment.
- **10.2.1.10.2** Clinical Documentation — add/update/delete assessment and progress notes.
- **10.2.1.10.3** Treatment Parameter Management — add/update/delete treatments, parameters, charges.
- **10.2.1.10.4** Reporting Management — treatment session details, data & statistics.

**10.2.1.11 Dental Module**
- **10.2.1.11.1** **"Sign-off" feature** — physician signs off completed patient.
- **10.2.1.11.2** Patient Management — physician views queues, sets appointments.
- **10.2.1.11.3** Consultation — record progress notes, insert data into **dental chart**.
- **10.2.1.11.4** References — refer to X-ray or outsource physician; review results/feedback.
- **10.2.1.11.5** Medication — prescribe / edit / delete / update medication records.
- **10.2.1.11.6** Reporting Management — X-ray report, Digital Medical Certificate, Referral Letter, Timeslip, diagnosis.

**10.2.1.12 Reporting Module**
- **10.2.1.12.1** Admission/discharge summaries; disease-specific reports (diabetes, hypertension); lab & imaging turnaround-time data; filter by date/department/diagnosis/clinician; export **PDF and Excel**.
- **10.2.1.12.2** Use Dashboard / Frontdesk & Registration / Pharmacy & Inventory data → operational performance reports; automate daily/weekly/monthly reporting.
- **10.2.1.12.3** Meet local **Ministry of Health** reporting standards + accreditation body requirements; notifiable disease reports; quality & safety compliance reports; **data anonymization**.
- **10.2.1.12.4** Financial performance reports — billing summaries, claims & payment status, total charges by department.
- **10.2.1.12.5** **Custom Report Builder** — ad-hoc reports without IT; select fields from all modules; filter/sort/group; save & share templates.
- **10.2.1.12.6** Real-time interactive dashboards & analytics — wait times, service usage, trend & comparative stats.
- **10.2.1.12.7** *Predictive analytics* — forecast patient visit volumes, disease burden trends, pharmacy stock depletion.
- **10.2.1.12.8** *Automated clinical insight engine* — natural-language summary reports for non-technical management + MOH submission.
- **10.2.1.12.9** *Population health stratification* — cluster patients by risk profile, surface high-risk cohort summaries.

**10.2.1.13 Mobile Apps**
- **10.2.1.13.1** Provided via secure **API** services; integrable with existing/future mobile platforms.
- **10.2.1.13.2** Full API support for mobile functionality, data access, system interactions.
- **10.2.1.13.3** Secure mobile pre-registration — select location/department/doctor, choose date/time slot, booking confirmation + reminders, reschedule/cancel.
- **10.2.1.13.4** Patients view visit dates, doctor, department; recorded vital signs (BP, temp, pulse); basic diagnosis & treatment notes; past prescriptions & instructions; download/share visit summaries as **PDF**.
- **10.2.1.13.5** Real-time alerts — appointment reminders, test-result availability, health campaign / clinic announcements.

**10.2.1.14 Calling System**
- **10.2.1.14.1** Generate queue numbers by visiting type; auto-assign correct number.
- **10.2.1.14.2** Compatible **printer** produces a queue-number ticket.
- **10.2.1.14.3** Central display on clinic TVs/monitors — active queue numbers + assigned counters/rooms.
- **10.2.1.14.4** Role-based access — call next / hold / skip; monitor count per queue type.

**10.2.1.15 Picture Archiving and Communication (PACS) System**
- **10.2.1.15.1** Integrated **PACS** platform to store/manage/retrieve X-ray results from the developed system.
- **10.2.1.15.2** Secure image viewer — zoom, rotate, measurement tools.
- **10.2.1.15.3** Use **DICOM** standards to receive images from imaging devices, auto-link to correct patient record.
- **10.2.1.15.4** Secure transmission to share images + reports with other departments / external specialists.
- **10.2.1.15.5** Reliable archiving & backup — long-term image storage, DR capability, regulatory retention.

#### 10.2.2 System Technology
- **10.2.2.1** Must use **PHP Framework CodeIgniter 4**.
- **10.2.2.2** Must use **Linux OS**.
- **10.2.2.3** Must be **web responsive**.
- **10.2.2.4** University provides a secure hosting environment (data-centre-grade reliability).
- **10.2.2.5** University provides network bandwidth & uptime per internal ICT standards.
- **10.2.2.6** University provides firewall, VPN, access-control policies.
- **10.2.2.7** Integrate with medical hardware — **Label Printer, Blood Test Machine, X-ray Image Viewing Machine**.
- **10.2.2.8** Integrate with UTHM systems — **SMP, SMS, e-klinik panel**.
- **10.2.2.9** Vendor configures the **Virtual Server** prepared by PTM + Antivirus provided by PTM.
- **10.2.2.10** All security issues referred to the related department in PTM.
- **10.2.2.11** Ensure system + DB compatibility with the University's hosting environment.
- **10.2.2.12** Full cooperation during installation, testing, deployment.
- **10.2.2.13** Application hosted in a secure, scalable, performance-optimised configuration.
- **10.2.2.14** Uploaded image files resized to a compatible format to reduce storage.
- **10.2.2.15** **Embedded intelligent engine** for real-time inference & decision support, natively in the application layer, **no third-party AI cloud APIs** — data sovereignty + offline operational continuity.
- **10.2.2.16** **Federated model updating** — inference engine improves over time from anonymised usage patterns within UTHM's data environment; no identifiable patient data leaves.
- **10.2.2.17** Demonstrate active integration of a **proprietary or licensed AI inference engine (e.g. ALi.ai or equivalent)** at submission, with docs confirming deployment in a **CodeIgniter 4 / Linux** environment.

#### 10.2.3 System Development Guidelines
- **10.2.3.1** Developed using **OWASP** application-development & security guidelines.
- **10.2.3.2** Design/develop the DB to meet functional & performance needs.
- **10.2.3.3** Structured, normalised, scalable database.
- **10.2.3.4** Create all necessary tables, indexes, stored procedures, views.
- **10.2.3.5** Best practices in data integrity and security.
- **10.2.3.6** Full documentation of DB schema and relationships.
- **10.2.3.7** University hosts the developed database.
- **10.2.3.8** Vendor not required to supply a separate DB server.
- **10.2.3.9** **AI-assisted code quality & compliance review** in the dev pipeline — auto-detect logic errors, security vulns, OWASP deviations pre-deployment.
- **10.2.3.10** Schema natively supports **HL7 FHIR-compatible data modelling** — future interop with **MySejahtera or PADU** with no schema restructuring.
- **10.2.3.11** **Automated data-quality monitoring** in the DB layer — detect missing values, duplicate patients, inconsistent coding, anomalous entries; configurable admin alerts.

#### 10.2.4 System Integration, Data Migration and Authentication
- **10.2.4.1** Integrate with the university's existing databases (student info, staff records).
- **10.2.4.2** Fully integrable architecture — connect with existing/future systems, DBs, APIs, devices without major redesign.
- **10.2.4.3** Integrate with external hardware/devices (biometric, IoT, lab/medical equipment, sensors) via **API**.
- **10.2.4.4** Secure data exchange machine↔system via **REST/JSON**, with auth + encryption.
- **10.2.4.5** Configurable **service layer / middleware** to manage machine-API comms + real-time/near-real-time DB sync.
- **10.2.4.6** Import data from the existing clinical system; migration verified by PKU UTHM.
- **10.2.4.7** Integration secure and compliant with data-protection policies.
- **10.2.4.8** Integration is **read-only** for reference and validation.
- **10.2.4.9** Support real-time or scheduled syncing.
- **10.2.4.10** Integrate with laboratory machines, X-ray viewing machines, label printers.

#### 10.2.5 System Security
- **10.2.5.1** Comply with **PDPA** — encryption at rest & in transit, **RBAC**, audit logs, data-retention per UTHM guidelines.
- **10.2.5.2** Security control module — manage user access levels by role.
- **10.2.5.3** Standard credential spec (login ID + password) and must support **LDAP**.
- **10.2.5.4** Vendor configures the Virtual Server prepared by PTM + Antivirus (dup of 10.2.2.9).
- **10.2.5.5** Security issues referred to PTM (dup of 10.2.2.10).
- **10.2.5.6** *Intelligent anomaly detection* via behavioural analytics — flag suspicious access, unusual login, exfiltration attempts in real time, no manual rule config.
- **10.2.5.7** *AI-driven audit-trail intelligence* — monitor/correlate/prioritise audit events, surface high-risk activity with context.
- **10.2.5.8** Continuous **automated vulnerability assessment** of own codebase + API endpoints; OWASP-aligned remediation recommendations before each update.

#### 10.2.6 Access Control and Configuration
- **10.2.6.1** System Administrator controls user access via the Module facility; can change system configuration and user access with guaranteed access.

#### 10.2.7 System Hardware & Backup Specification (Vendor-provided)
- **10.2.7.1 Database Server**
  - **10.2.7.1.1** Vendor provides & maintains a **dedicated DB server**; support ~20,000 students + 3,000 staff.
  - **10.2.7.1.2** Server installed **on-premise** at the university data centre or securely integrated with existing hosting.
  - **10.2.7.1.3** DBMS compatible with enterprise RDBMS — **Oracle, MS SQL Server, MariaDB, or MySQL** — subject to university technical approval and licensing.
- **10.2.7.2 Data & System Backup** (vendor responsibility) — comprehensive automated backup:
  - **10.2.7.2.1.1** Daily incremental + weekly full backups.
  - **10.2.7.2.1.2** Encrypted backup files (at rest and in transit).
  - **10.2.7.2.1.3** Minimum **30-day** retention.
  - **10.2.7.2.2.1** Full system image snapshot before major updates/changes.
  - **10.2.7.2.2.2** Restorable system state within a defined **RTO**.
  - **10.2.7.2.3.1** Quarterly restore testing.
  - **10.2.7.2.3.2** Backup success/failure reporting with logs.
  - **10.2.7.2.4.1** Clear DR procedures + responsible contact points.
  - **10.2.7.2.4.2** Documented **RPO** and **RTO**.
- **10.2.7.3 Server Hosting**
  - **10.2.7.3.1** Hosting infrastructure provided by the University.
  - **10.2.7.3.2** Vendor integrates the DB server with the existing hosting environment.
  - **10.2.7.3.3** Ensure compatibility and secure connectivity.
  - **10.2.7.3.4** Collaborate with the internal infrastructure team during deployment & maintenance.
- **10.2.7.4 Support & Maintenance**
  - **10.2.7.4.1** ≥2 dedicated **onsite** support staff throughout the 2-year complimentary support period.

#### 10.2.8 Implementation Cost for PKU Kampus Cawangan Pagoh
- **10.2.8.1 Integration with laboratory machines/devices through API**
  - **10.2.8.1.1** Seamless data exchange system↔lab devices via standardized API.
  - **10.2.8.1.2** API pushes patient demographics + test orders to the lab device.
  - **10.2.8.1.3** Lab device returns results automatically → storage, review, report printing.
  - **10.2.8.1.4** Comply with industry standards for data integrity, security, interoperability.
  - **10.2.8.1.5** Compatibility with existing & future lab machines identified by PKU UTHM.
  - **10.2.8.1.6** Test environment for validation before production.
- **10.2.8.2 Label printer + calling-system printer config**
  - **10.2.8.2.1** Configure & test label printers for patient sample labelling.
  - **10.2.8.2.2** Label templates: patient name, IC number, item details, barcode (if applicable).
  - **10.2.8.2.3** Auto-trigger label printing from orders.
  - **10.2.8.2.4** Configure the calling-system printer for queue numbers.
  - **10.2.8.2.5** Printing synchronised between the system and the calling-system module.
- **10.2.8.3 Monitor/TV for calling system**
  - **10.2.8.3.1** Configure & set up display monitors/TVs in waiting areas.
  - **10.2.8.3.2** Show real-time queue numbers, clinic counters, patient names/initials.
  - **10.2.8.3.3** Visual + audio notifications for patient calls.
  - **10.2.8.3.4** Layout/design follows PKU UTHM standard format & branding.
  - **10.2.8.3.5** End-to-end testing and demonstration.

### 10.3 VENDOR TECHNICAL PERSONNEL REQUIREMENTS
- **10.3.1** Development team includes qualified, registered technical personnel.
- **10.3.2 Registered Technologist — MBOT**
  - **10.3.2.1** ≥1 lead technical person with active **MBOT** registration as Technologist (TS) or Senior Technologist (TSr) in ICT / related engineering.
  - **10.3.2.2** MBOT person actively involved across the lifecycle (design, dev oversight, UAT facilitation, handover); named in the project team.
  - **10.3.2.3** Submit certified copy of MBOT certificate, current status, signed declaration.
- **10.3.3 Clinical Governance — Registered Medical Doctor / Clinical Advisor**
  - **10.3.3.1** Active clinical governance participation — a registered medical practitioner in the advisory/governance structure.
  - **10.3.3.2** ≥1 doctor registered with the **Malaysian Medical Council (MMC)** or equivalent, as Clinical Advisor for dev + UAT + commissioning.
  - **10.3.3.3** Advisor reviews/validates clinical workflows, signs off on clinical data-standards compliance, advises on safety & data integrity.
  - **10.3.3.4** If not a full-time employee, submit a Letter of Appointment / MoU / engagement agreement.
  - **10.3.3.5** Submit proof of current MMC registration, CV, letter of consent.
- **10.3.4 AI & Health Informatics Competency**
  - **10.3.4.1** ≥1 team member with verifiable competency/certification in health informatics, clinical data management, or AI in healthcare (**HIMSS, HL7**, or equivalent).
  - **10.3.4.2** Submit credentials / certificates / institutional references.
