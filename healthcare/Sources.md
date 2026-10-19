---
title: Sources
type: reference
updated: 2026-08-30
tags: [sources, references]
---

# Sources

Every external reference, checked. Grouped by topic. Raw research transcript with the
full citation set: `scratchpad/agy-research-full.md` (Part 1 = A–C, Part 2 = D–G).

## Tender & codebase
- CLARION static security audit, Aug 2026 → [[Security Audit]] (`scratchpad/security-audit.md`)
- Target on-prem architecture, Aug 2026 → [[On-Prem Architecture]] (`scratchpad/architecture.md`)
- `docs/source/gemin-text.txt` — the Gemini HIE thread → [[Nationwide Health Information Exchange]]

## PHP / CodeIgniter 4
- [CodeIgniter 4 — RESTful handling](https://codeigniter.com/user_guide/incoming/restful.html)
- [CodeIgniter 4 — entities](https://codeigniter.com/user_guide/models/entities.html)
- [OpenAPI Generator](https://openapi-generator.tech/) · [swagger-php](https://zircote.github.io/swagger-php/) · [JanePHP](https://janephp.org/)

## Malaysia regulation
- [Jabatan Perlindungan Data Peribadi (PDPA)](https://www.pdp.gov.my) — PDPA (Amendment) Act 2024
- [e-Notifikasi](http://enotifikasi.moh.gov.my) — notifiable disease reporting (Act 342)
- [MSQH](https://msqh.com.my) — accreditation
- [Medical Device Authority](https://www.mda.gov.my) — Medical Device Act 2012 (Act 737), SaMD

## National interoperability
- [MHNexus — Health Information Exchange](https://www.mhnexus.com/index.php/project-items/hie/)
- [Smile Digital Health — Nation Connected](https://www.smiledigitalhealth.com/usecase/nation-connected-health-interoperability)
- [MY Core FHIR IG (Simplifier)](https://simplifier.net/guide/mycore) · [my-core.ig.mhnexus.com](https://my-core.ig.mhnexus.com/)

## On-prem AI
- [MAIA Sdn Bhd (ALi.ai)](https://maia.com.my/)
- Model licences: [Meta Llama](https://llama.meta.com/llama3/license/) · [Qwen2.5](https://huggingface.co/Qwen/Qwen2.5-7B/blob/main/LICENSE) · [Gemma](https://ai.google.dev/gemma/terms) · [MedGemma](https://huggingface.co/google/medgemma-4b-it) · [Meditron](https://huggingface.co/epfl-llm/meditron-70b) · [OpenBioLLM](https://huggingface.co/aaditya/Llama3-OpenBioLLM-8B)
- Runtimes: [Ollama](https://ollama.com) · [vLLM](https://github.com/vllm-project/vllm) · [llama.cpp](https://github.com/ggml-org/llama.cpp)
- ASR: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [WhisperX](https://github.com/m-bain/whisperX) · [Whisper](https://github.com/openai/whisper)
- Federated: [Flower](https://flower.ai) · [NVIDIA FLARE](https://nvflare.readthedocs.io)
- Drug DBs: [MIMS CDS](https://cds.mims.com/) · [First Databank](https://www.fdbhealth.com) · [Lexicomp](https://www.wolterskluwer.com/en/solutions/lexicomp)

## PACS / DICOM
- [Orthanc licensing](https://orthanc.uclouvain.be/book/faq/licensing.html) · [dcm4chee-arc-light](https://github.com/dcm4che/dcm4chee-arc-light)
- [OHIF Viewer](https://ohif.org/) · [Cornerstone3D](https://cornerstonejs.org/)
- [IHE Radiology Technical Framework Vol 2](https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol2.pdf)
- [NIST SP 1800-24 — Securing PACS](https://doi.org/10.6028/NIST.SP.1800-24)

## Integration & LDAP
- [Mirth Connect — a new era (NextGen)](https://www.nextgen.com/blog/industry-news/a-new-era-for-mirth-connect-by-nextgen-healthcare)
- [Open Integration Engine](https://openintegrationengine.org/)
- [ldap3](https://ldap3.readthedocs.io/) · [PHP LDAP](https://www.php.net/manual/en/book.ldap.php)

## Nationwide HIE
- [International Patient Summary](https://international-patient-summary.net/) · [ISO 27269](https://www.iso.org/standard/81839.html) · [HL7 FHIR IPS IG](http://hl7.org/fhir/uv/ips/)
- [IHE XDS](https://wiki.ihe.net/index.php/Cross-Enterprise_Document_Sharing) · [IHE MHD](https://wiki.ihe.net/index.php/Mobile_access_to_Health_Documents_(MHD)) · [IHE ATNA](https://wiki.ihe.net/index.php/Audit_Trail_and_Node_Authentication)
- [ONC — patient identity & matching](https://www.healthit.gov/topic/interoperability/patient-identity-and-matching)
- [Ceph erasure coding](https://docs.ceph.com/en/latest/rados/operations/erasure-code/) · [MinIO erasure coding](https://min.io/docs/minio/linux/operations/concepts/erasure-coding.html)
- National systems: [Estonia e-Health](https://e-estonia.com/solutions/healthcare/e-health/) · [Denmark sundhed.dk](https://www.sundhed.dk/) · [Austria ELGA](https://www.elga.gv.at/) · [Australia My Health Record](https://www.myhealthrecord.gov.au/) · [India ABDM](https://abdm.gov.in/) · [Singapore NEHR](https://www.synapxe.sg/healthtech/national-programmes/national-electronic-health-record-nehr)

## Soft / to re-verify
- PDPA 2024 exact clause commencement dates + the 72-hour breach window (guidance was pending).
- MedGemma exact repo names (`medgemma-4b-it` / `medgemma-27b-text-it`).
- "MDA/GD/0072 (June 2026)" SaMD change-management guidance (agy-cited, unconfirmed).
- Five-nines SLA tiering / active-active geo — industry practice, not single-source.
