---
title: On-Prem Clinical AI
type: research
updated: 2026-08-30
tags: [research, ai, llm, samd, offline, malaysia]
---

# On-Prem Clinical AI

Tender clauses **–17**: an embedded inference engine, **no third-party AI
cloud APIs**, data sovereignty + offline continuity, "federated model updating", and a
"proprietary or licensed AI inference engine (e.g. **ALi.ai** or equivalent)" in a
CI4/Linux environment.

> [!success] Resolved 2026-09-13 (P4.3)
> `ai/summarize.py` and `ai/nric_ocr.py` now call `ai/local_llm.py` (local Ollama, see
> `docs/deployment.md`) instead of Anthropic — both degrade to their existing
> deterministic/Tesseract fallback automatically if Ollama isn't running. See
> [[Security Audit#C1]]. `ai/interactions.py`'s NIH RxNav/DailyMed calls are a separate,
> narrower dependency (drug-identity lookup, not an AI cloud API) — still open, P4.4.
> **Not yet built:** the CDS hint, medication-safety rule engine wiring, voice→SOAP, and
> NL report narrative features below — the local-LLM *plumbing* is done, the specific
> clinical *features* are still to build.

## "ALi.ai" — what it actually is
**MAIA Sdn Bhd** ("Medical Augmented Intelligence Automation"), Cyberjaya — a
clinician-led Malaysian company doing **workflow/administrative AI** (Ali Life = TPA
claim automation, Ali Queue, Ali Baby = ultrasound enhancement). **Not a foundational
LLM.** [maia.com.my](https://maia.com.my)

Read the clause as: *run open-weight models locally, and be able to name a Malaysian AI
capability.* A partnership conversation with MAIA is worth having; it is not a technical
dependency.

## "Federated model updating" for one site = category error
Federated learning (Flower, NVIDIA FLARE) needs **multiple institutions** training
without sharing raw data. For a single clinic the honest reading of the tender is
**periodic local LoRA / PEFT fine-tuning** on de-identified local data. Say that plainly.

## The stack that covers every AI clause
| Tender feature | Clause | Local component |
|---|---|---|
| Clinical decision support (differential dx, contraindication flags) | | Instruction-tuned 8–14B LLM + retrieval over local guidelines |
| Medication-safety screening | | **Rule engine + licensed drug DB** (MIMS, formulary-mapped) — deterministic, not the LLM |
| Voice → structured SOAP | | `faster-whisper` (MIT) ASR + small model to segment into SOAP fields |
| NL report / clinical-insight summaries | | Same local LLM, templated prompts over structured data |
| Lab result interpretation & trend flags | –5 | Reference-range rules + trend math; LLM only for the narrative |
| Access anomaly detection / audit-trail intelligence | –7 | Behavioural heuristics over the audit hash-chain; LLM for explanation |
| Patient-flow prediction / operational health score | –3 | Classical time-series (EWMA / gradient-boosted) — **no LLM** |

## Open-weight models & licences
| Model | Licence | Clinical caveat |
|---|---|---|
| Llama 3.1/3.2/3.3 | Meta Llama Community Licence | Acceptable-use bars unlicensed medical practice |
| Qwen2.5 (7B/14B) | Apache-2.0 | — (72B = Qwen Licence) |
| Gemma 2 | Gemma Terms of Use | — |
| Mistral 7B v0.2/0.3 | Apache-2.0 | (larger = MNPL) |
| MedGemma | HAI-DEF Terms | **prohibits autonomous diagnosis** |
| Meditron 7B/70B | Llama 2 Community | authors warn vs unvalidated clinical deployment |
| OpenBioLLM-8B | Llama 3 Community | — |

**All carry acceptable-use clauses forbidding autonomous clinical decision-making and
medical-device use.** Fine — every feature above is a clinician *reference aid*. This
also aligns with [[Malaysia Health Regulation#Medical Device Authority — SaMD]].

## Runtimes & hardware
- **Runtimes:** `Ollama` (easiest local API), `vLLM` (production throughput,
  PagedAttention), `llama.cpp` (CPU / Apple Silicon / mixed). LM Studio = desktop GUI,
  not headless prod.
- **Hardware:** 7–8B quantised ≈ 6–8 GB VRAM (single RTX 3060/4060); 70B quantised ≈
  40–48 GB (dual RTX 3090/4090 or an A6000). CPU is too slow for real-time voice→SOAP.
- **ASR:** Whisper (MIT, large-v3 ~10 GB VRAM), `faster-whisper` (MIT, ~4× faster,
  CTranslate2), WhisperX (BSD-4, word timestamps + diarization).

## Licensed drug-interaction databases in Malaysia
- **MIMS** — active locally, B2B per-site, "FastTrack" API mapped to hospital formulary.
- **First Databank (FDB)**, **Lexicomp** — global, per-bed / per-site enterprise licensing.

## For the demo
One 8B model on one GPU running the CDS hint + medication alert + voice-to-SOAP + NL
summary, **network visibly disconnected**, *is* the tender requirement story. Show the
cable unplugged. No 70B, no fine-tune pipeline needed on stage.

Detail: `scratchpad/agy-research-full.md` Part 2 Topic D. See [[Sources]].
