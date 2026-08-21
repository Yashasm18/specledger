# SpecLedger — AI-Powered Industrial Product Intelligence & Catalogue Enrichment

[![Live Demo](https://img.shields.io/badge/Live%20Demo-yashasm18.github.io-2ea44f.svg?logo=github&logoColor=white)](https://yashasm18.github.io/specledger/)
[![API](https://img.shields.io/badge/API-Railway-0B0D0E.svg?logo=railway&logoColor=white)](https://specledger-production.up.railway.app/docs)
[![CI & Code Quality](https://github.com/Yashasm18/specledger/actions/workflows/pylint.yml/badge.svg)](https://github.com/Yashasm18/specledger/actions/workflows/pylint.yml)
[![Deploy](https://github.com/Yashasm18/specledger/actions/workflows/gh-pages.yml/badge.svg)](https://github.com/Yashasm18/specledger/actions/workflows/gh-pages.yml)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Yashasm18/specledger/blob/main/LICENSE)

[![Tests](https://img.shields.io/badge/Tests-306%20passed%2C%201%20skipped-brightgreen.svg)](https://github.com/Yashasm18/specledger/tree/main/tests)
[![Pylint](https://img.shields.io/badge/Pylint-9.93%2F10-brightgreen.svg)](https://github.com/Yashasm18/specledger/blob/main/.pylintrc)
[![Synthetic Benchmark](https://img.shields.io/badge/Synthetic%20benchmark-94.37%25-blue.svg)](#benchmark-results)
[![Throughput](https://img.shields.io/badge/Throughput-~7%2C000%20rows%2Fsec-blue.svg)](#benchmark-results)
[![Unilog CX1](https://img.shields.io/badge/Unilog%20CX1-252%20columns%2C%20exact%20match-009688.svg)](https://github.com/Yashasm18/specledger/blob/main/backend/specledger/unilog_exporter.py)
[![Live verification](https://img.shields.io/badge/Sources-verified%20on%20demand-16a34a.svg)](#verify-live--the-claim-you-can-check-yourself)

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-required-4169E1.svg?logo=postgresql&logoColor=white)](#running-locally)
[![React](https://img.shields.io/badge/React%20%2B%20Vite-TypeScript-61DAFB.svg?logo=react&logoColor=white)](https://vitejs.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](https://github.com/Yashasm18/specledger/blob/main/docker-compose.yml)
[![Gemini](https://img.shields.io/badge/Gemini-opt--in%20tier-8E75B2.svg?logo=googlegemini&logoColor=white)](#overview)

> **Live demo:** [yashasm18.github.io/specledger](https://yashasm18.github.io/specledger/)
>
> **UniHack 2026 submission** — transforming limited, unstructured industrial catalogue data into rich, evidence-backed, commerce-ready product intelligence, delivered in Unilog's official **252-column template format**, targeting the growth from **150,000 to 750,000 enriched SKUs/month at the same operational capacity** Unilog named as their goal.

---

## Contents
[Overview](#overview) · [How it works](#how-it-works) · [Datasets & provenance](#datasets--provenance) · [Benchmark results](#benchmark-results) · [Evaluation criteria](#evaluation-criteria) · [Verify live](#verify-live--the-claim-you-can-check-yourself) · [Hit rate](#measured-hit-rate-on-real-rows) · [External catalogue test](#tested-against-an-external-manufacturer-catalogue) · [Known limits](#known-limits) · [API reference](#api-reference) · [Web dashboard](#web-dashboard) · [Environment variables](#environment-variables) · [Running locally](#running-locally) · [Repository structure](#repository-structure)

---

## Overview

Industrial B2B commerce platforms (like Unilog CX1 PIM) process hundreds of thousands of raw SKUs from thousands of component manufacturers. Ingested data is frequently fragmented, misspelled, missing units of measure, or lacking material and pressure specifications.

Unilog's platform doesn't perform product enrichment itself — that work is largely manual today, done by distributors and their teams rather than automated. That gap is the actual problem this challenge is about, not a hypothetical one: incomplete or inconsistent product data directly degrades on-site search relevance, drives customer complaints and returns, and burns operational hours that could be spent elsewhere. AI-assisted automation is the lever Unilog is specifically looking for — not to replace human judgment on ambiguous cases, but to remove the repetitive, structured portion of enrichment so people only spend time where it actually needs a human call.

**SpecLedger** cleans, normalizes, validates, enriches, and audits industrial product records before they reach sales channels — as a hackathon prototype, not a production data-verification service. It's built around that division of labor: deterministic, auditable automation for everything with one clearly correct answer, and a fast human review queue for the rest.

**Why 150K → 750K SKUs/month is a review-queue problem, not a compute problem.** Unilog's stated target is a 5x volume increase at the same operational capacity — without proportionally growing headcount. Raw speed was never the bottleneck: the deterministic path runs at ~7,000 rows/sec (see [Benchmark results](#benchmark-results)), far beyond what any realistic monthly volume needs. The real constraint is how many rows require a *person*.

Here is where that actually stands on the official 1,000-row dataset, measured rather than projected:

| | Measured |
|---|---|
| Rows auto-approved with no human touch | **20.0%** (200/1,000) |
| Rows routed to human review | **80.0%** (800/1,000) |
| Category resolved deterministically | **77.6%** (776/1,000) |
| Field-level verified rate | **38.1%** |

**80% still needing review is not a win yet, and the dashboard says so too.** The honest reading is that this dataset is sparse — nearly every row carries `-- Unbranded --`, `-- No Unilog Brand --` and `-- No DIB Brand --` placeholders, and the dominant validation finding is a brand that matches no controlled-vocabulary entry. Auto-approval is gated on exactly that kind of unresolved reference match, which is the correct conservative default when the alternative is publishing unverified data to a customer catalogue.

What would move it: Unilog's real 27,000-row manufacturer/brand list and 161,000-row LOV file, which were never obtained for this build (see [Datasets & provenance](#datasets--provenance)). The reference tables here are self-authored and far smaller, so brand matching fails often — a data gap, not an algorithmic one. Wiring in the real vocabularies is the single highest-impact accuracy improvement available, and the pipeline needs no structural change to accept them.

- **Provenance-first output.** Deterministic transformations retain source file, row, and column lineage. Generated source candidates are explicitly marked unverified, not substitutes for fetched evidence — see [How it works](#how-it-works) for what "generated" means here.
- **Strict marketplace prohibition.** Amazon, eBay, Alibaba, Walmart, Zoro, Grainger, and other resellers are blocked; enrichment data is scoped to manufacturer-authoritative domains only.
- **Human governance.** Rows that pass deterministic validation can auto-approve; conflicts route to a review workspace. Production publication would additionally require verified source evidence.
- **Two deployment modes:** a headless REST API for ETL/PIM integration, and an interactive web dashboard for human review.

**Domain-agnostic by design.** Unilog's own catalogue skews HVAC, plumbing, and electrical (and so does the sample dataset this challenge provides), but nothing in the pipeline is hardcoded to that vertical. Column-to-role detection (`detect_role()` in [`enrichment.py`](backend/specledger/enrichment.py)) is keyword-based, not a fixed schema; the validation framework's 6 rule categories (required fields, LOV membership, cross-field consistency, completeness, duplicates, character limits) apply to any category, and the one example cross-field rule shown in this README (PVC vs. 600 PSI) is a single illustrative rule within that generic framework, not evidence the framework only works for valves. Point it at a different catalogue — electronics, apparel, food service equipment — and the same pipeline runs; only the reference data (`reference_data.py`'s manufacturer/brand/material tables) would need extending with that vertical's own vocabulary.

**On cost — the expensive part is deliberately not where the AI is.** The default path is 100% deterministic, rule-based normalization: **zero LLM calls**, for every row, at any stage. That covers the **77.6%** of the official dataset the keyword classifier resolves outright, at exactly $0.

The remaining **22.4%** is where deterministic matching genuinely fails — sparse, ambiguous descriptions no keyword list resolves. Those rows, and only those, can be sent to an **opt-in LLM tier** (`ai_assist=true`, or the "AI assist" toggle in the dashboard). It is off by default, and a no-op without `GEMINI_API_KEY`.

That tier is bounded by construction rather than by promise:

| Property | How |
|---|---|
| Only sees the residue | Deterministic classification runs first and keeps everything it resolved. |
| Batched | 25 products per request — the 224 unresolved rows cost ~9 calls, not 224. |
| Constrained | Output is restricted to the existing taxonomy via a response schema; anything outside the controlled vocabulary is discarded. `temperature=0` keeps re-runs stable. |
| Never authoritative | Every suggestion is marked `ai_inferred`, carries the model and prompt version, keeps the deterministic answer alongside it, and **cannot auto-approve** — it always routes to human review. |
| Never load-bearing | No key, an HTTP error, a timeout or a malformed response all degrade to "no suggestion". A failing LLM never fails an ingest. |

**Measured cost:** $0.0000231 per enriched row, against the live Gemini API (10 rows, 1 call, 1,206 tokens, `gemini-3.6-flash`). Extrapolated to the 750,000 SKUs/month target with ~22% needing the tier, that is roughly **$3.80/month in model spend**. Token counts come from the API and are reported as measured; the per-token rate is configuration (`SPECLEDGER_LLM_INPUT_RATE`/`_OUTPUT_RATE`) and is labelled as such in the payload rather than presented as a measurement.

The other optional external dependency is `live_fetch`'s Serper.dev search fallback, used only when direct manufacturer-domain URL guessing finds nothing (their free tier alone covers 2,500 queries — see [External sources and services](#datasets--provenance)). The dashboard's benchmark tile reflects all of this honestly: the deterministic run it displays makes no external calls at all, so its real cost is $0.

| | Headless API | Web Dashboard |
|---|---|---|
| **For** | Data engineers, ETL pipelines, PIM/ERP integrations | Catalog managers, QA, compliance |
| **Interface** | `POST /catalogue/ingest` → `GET .../export` | React dashboard with 7 workspace views |
| **Use case** | Automated batch processing, nightly jobs | Reviewing the ~10–15% of rows needing a human call |

---

## How it works

A deterministic pipeline turns sparse supplier spreadsheets into evidence-grounded, commerce-ready records. An optional LLM tier sees only what the deterministic path could not resolve, and can never auto-approve:

```mermaid
flowchart LR
    A["1. Ingest\nCSV/TSV/XLSX/PDF\nSHA-256 fingerprinting"] --> B["2. Source discovery\nManufacturer-domain allowlist\nMarketplace blocker"]
    B --> C["3. Enrichment\nLOV normalization\n6 description tiers\n50 attribute triplets"]
    C --> D{"Category resolved?"}
    D -- "yes (77.6%)" --> E["4. Validation\nCross-field physics\nCompleteness scoring"]
    D -- "no (22.4%)" --> L["3b. LLM tier — opt-in\nBatched, schema-constrained\nMarked ai_inferred"]
    L --> E
    E --> F{"5. Confidence ≥ 80%\nand 0 errors?"}
    F -- yes --> G["Auto-approved"]
    F -- no --> H["Human review queue"]
    L -.->|"never auto-approves"| H
    H --> G
    G --> I["6. Export\n252-col Unilog CSV\nschema.org JSON-LD\nCommerce PIM CSV"]
```

**Stage 2 has two modes, and the difference matters.** By default, source discovery constructs plausible manufacturer URLs from a domain allowlist without fetching them — fast, deterministic, safe for tests. Passing `live_fetch=true` to `POST /catalogue/ingest` switches to real HTTP requests: it fetches the candidate URL, confirms the part number actually appears on the fetched page before marking anything "verified" (a raw substring match on a search-results page that merely echoes your query back is explicitly rejected — only a direct product-page hit counts), and follows a genuine linked PDF datasheet when the page has one. Rows where nothing real is found come back honestly empty rather than a fabricated guess. See [Measured hit rate](#measured-hit-rate-on-real-rows) below for what it actually achieves.

**When a real datasheet PDF is found, its text is actually read — not just linked.** This is the direct answer to the "few parameters given, the rest comes from manuals" scenario Unilog's own team described (e.g. the Samsung spec-sheet example): once `live_fetch` confirms a genuine linked PDF datasheet, [`extract_pdf_attributes()`](backend/specledger/source_discovery.py) opens the real fetched bytes with PyMuPDF, flattens them to text, and pulls out genuine "Label: Value" spec rows (e.g. `Voltage Rating: 120 V`) with a conservative Title-Case pattern — tuned specifically to reject flowing marketing prose (verified against a real third-party manufacturer catalog PDF, which correctly yielded near-zero false positives) rather than a loose match that would turn brochure sentences into fake attributes. A PDF with no clean label/value layout — a photo-heavy brochure, a prose-only manual — honestly yields zero extracted attributes rather than a guess; this is intentionally conservative, not a claim that every manufacturer PDF gets parsed. Surfaced in the dashboard's Evidence Library alongside the source link itself.

When domain guessing finds nothing (very common — the raw input's manufacturer field is frequently a distributor, e.g. "Appliance Dealers Cooperative", not the real manufacturer), `live_fetch` falls back to a real web search (via [Serper.dev](https://serper.dev), optional — set `SERPER_API_KEY`) and accepts a manufacturer only when a returned result links to a domain already in the registry, never inventing a name from search text. Tested against Unilog's own real worked example: correctly identified "Frigidaire" as the true manufacturer of part `PDSH4816AF` from a raw "Appliance Dealers Cooperative" input, matching Unilog's real answer — though the manufacturer's own page then failed to load in time (bot protection on their end), so the resolved name is surfaced honestly as search-identified rather than page-verified in that case. A second real example found no match at all, because the manufacturer's page didn't rank in top search results for that query — real search has real limits.

It's capped at 50 rows per request since it's real network I/O (not instant), and off by default so the automated test suite stays fast and offline. A separate deep-crawl module that only ever synthesized plausible-looking profiles — never fetching anything — was **deleted**, along with the three endpoints that exposed it, rather than left in place behind a disclaimer: its `/scraper/datasheet.pdf` route was still reachable on the public API and would stream an invented "submittal" document. Its marketplace blocklist was genuinely broader than the real one, so those domains were merged into [`source_discovery.py`](backend/specledger/source_discovery.py) first. The per-SKU inspector shows the real computed 252-column record for every row.

**On source breadth — manuals, videos, and beyond a manufacturer's own domain.** The architecture already models this: `SourceType` in [`source_discovery.py`](backend/specledger/source_discovery.py) classifies `PDF_DATASHEET`, `TECHNICAL_MANUAL`, `VIDEO`, and `SPECIFICATION_SHEET` as distinct source kinds, and nothing in the pipeline assumes the source is a manufacturer's own website specifically — only that it isn't a blocked marketplace (see `BLOCKED_DOMAINS`). What's real today is HTML product pages and PDF datasheets, with the PDF path now reading actual text out of the file (previous paragraph) rather than just linking to it. Video transcription and non-manufacturer third-party sources (review sites, forums, social) are anticipated in the type system but not implemented — stated here directly rather than left ambiguous.

### Measured hit rate on real rows

Verification was run against live manufacturer sites for 21 real rows from the official dataset, sampled three per department so the result measures generality rather than one comfortable vertical:

| Department | Verified |
|---|---|
| Tools & Equipment | 3/3 |
| Electrical Supplies | 3/3 |
| Appliances & Consumer Electronics | 1/3 |
| Industrial Supplies | 1/3 |
| Building Supplies | 0/3 |
| Electrical | 0/3 |
| Safety & PPE | 0/3 |
| **Overall** | **8/21 — 38%** |

**38%, not 90%.** Publishing the number that survives checking is the point; a tool claiming near-total success against live manufacturer sites would be describing something other than the open web.

Two findings from that sweep are worth stating, because both were surprises:

**Search is most of the value.** The same sweep scores **24%** without `SERPER_API_KEY` and **38%** with it. Electrical Supplies goes 1/3 → 3/3 purely because search resolves `Square D Con Prod Dv` — a name absent from the registry — to `Square D`. Most failures are not missing registry entries but **URL-pattern mismatches**: the pipeline guesses `/product/{sku}`, while Unilog's own worked example sits at `/en/p/owner-center/product-support/{sku}`, which no pattern list would guess. Search finds the real URL whatever its shape.

**It caught a bug pointed the wrong way.** One row resolved `3 M Co` → `Jam Industrial Supply LLC` — a real manufacturer collapsing into its distributor, the exact inversion this pipeline exists to correct. The distributor's own domain had been listed as authoritative in the registry, so search accepted their page as evidence. Fixed, with tests pinning the invariant.

### Tested against an external manufacturer catalogue

The official Unilog sample is one dataset. To check the pipeline generalises rather than fitting that file, 23 real products were pulled from **Diablo** and **Watts** via their own published sitemaps — `robots.txt` checked first, and **Leviton skipped entirely because theirs disallows crawling** — then degraded to the sparse six-column shape a distributor sends and uploaded to the live app.

It found two real bugs immediately:

**Every Diablo product classified as an abrasive** — saw blades, hole saws, auger bits, chisels, hammer drill bits. `"freud"` and `"diablo"` were abrasives keywords, and the classifier matched description and manufacturer as a single string, so the brand name decided the category for every row carrying it. Classification is now two-pass: **description alone first, manufacturer only as a fallback** when the description places a product nowhere. A manufacturer name is only usable as a category signal when that manufacturer makes one category — Mirka does, Freud does not.

**A row with part number `SC` and description `SC` auto-approved at 100% confidence.** Confidence measures how sure we are about the values present; it says nothing about whether enough is present to sell from. Descriptions carrying nothing beyond the SKU now block auto-approval. On that catalogue the auto-approve rate went from a meaningless **100% to 60.9%**, with the nine bare-SKU rows correctly routed to a human.

Neither bug is visible on the official dataset — its rows have real descriptions, and its manufacturers happen not to collide with category keywords. That is the argument for testing on data you did not choose.

### Core modules

| Stage | Module | Responsibility |
|---|---|---|
| Ingestion | [`catalogue_ingestion.py`](backend/specledger/catalogue_ingestion.py) | Parses CSV/TSV/XLSX/PDF, strips distributor codes (`Freud Inc (2435)` → `Freud Inc`), computes row fingerprints |
| Sourcing | [`source_discovery.py`](backend/specledger/source_discovery.py) | Templated candidates by default; real HTTP fetch + verification via `live_fetch=true`. Blocks reseller marketplaces either way |
| Enrichment | [`web_enricher.py`](backend/specledger/web_enricher.py), [`reference_data.py`](backend/specledger/reference_data.py) | Material/UOM normalization, description synthesis, attribute triplets |
| Validation | [`validation_engine.py`](backend/specledger/validation_engine.py) | 6 rule categories: required fields, LOV membership, cross-field physics, completeness, duplicates, character limits |
| AI tier (opt-in) | [`llm_enricher.py`](backend/specledger/llm_enricher.py) | Batched, schema-constrained Gemini classification of the deterministic residue only. Marked `ai_inferred`; cannot auto-approve |
| Human review | [`human_review.py`](backend/specledger/human_review.py) | Confidence-gated routing, state machine, immutable audit trail |
| Persistence | [`catalogue_persistence.py`](backend/specledger/catalogue_persistence.py), [`database.py`](backend/specledger/database.py) | PostgreSQL system of record, pooled connections, paginated reads. Refuses to start without a database |
| Export | [`export.py`](backend/specledger/export.py), [`unilog_exporter.py`](backend/specledger/unilog_exporter.py) | 252-column Unilog CSV, schema.org JSON-LD, Commerce CSV, audit JSON |

### Reference data
- 20+ canonical manufacturers, 14 brands, 18 product categories
- 30+ material aliases normalized (`CI` → Cast Iron, `SS316` → Stainless Steel 316, `PTFE` → Teflon, …)
- SKU-prefix inference (`APO-` → Apollo Valves, `PAR-` → Parker Hannifin, …)
- Reseller blocklist: `amazon.com`, `ebay.com`, `walmart.com`, `alibaba.com`, `aliexpress.com`, `grainger.com`, `zoro.com`, `homedepot.com`, `lowes.com`

---

## Datasets & provenance

What Unilog actually published for this challenge is three things: a Solution Guide, a 1,000-row sample input, and an Expected Output sheet containing the static 252-column header plus 2 fully-worked real examples (a Frigidaire and a Whirlpool dishwasher). There is no larger officially-labeled ground-truth set available to participants.

| File | Role | Size |
|---|---|---|
| [`data/challenge/Unihack_ Sample Dataset - Input.csv`](data/challenge/Unihack_%20Sample%20Dataset%20-%20Input.csv) | Official challenge input (6 sparse supplier columns) | 1,000 rows |
| [`data/challenge/Unihack_ Expected Output - Delivery Format.csv`](data/challenge/Unihack_%20Expected%20Output%20-%20Delivery%20Format.csv) | Official 252-column header **plus 2 real worked examples** — the only genuine Unilog-labeled ground truth available | 2 rows |
| [`data/challenge/Unihack_ Enriched_Delivery_Output_252.csv`](data/challenge/Unihack_%20Enriched_Delivery_Output_252.csv) | SpecLedger's generated output on the full 1,000-row input | 1,000 rows, 1.49 MB |
| [`data/ground_truth/synthetic_200_valves.csv`](data/ground_truth/synthetic_200_valves.csv) | **Self-generated, fictional** benchmark (invented manufacturers/part numbers) — useful for regression-testing our own pipeline logic, not a claim about real-world or official Unilog accuracy | 200 rows |
| [`data/ground_truth/electrical_automation_100_benchmark.csv`](data/ground_truth/electrical_automation_100_benchmark.csv) | Also self-generated/fictional, same caveat as above | 100 rows |

Reproduce the numbers below yourself:
```bash
.venv/bin/python -m pytest tests/ -v                        # 252 tests, 100% pass
.venv/bin/python -m pytest tests/test_evaluator.py -v        # self-generated 200-row regression benchmark
.venv/bin/python -m pytest tests/test_unilog_pipeline.py -v  # official 1,000-row dataset, structural checks
```

**External sources and services** — everything the enrichment pipeline reaches outside this repo, so the provenance of every number above is traceable:

| Source | Used for | Provenance |
|---|---|---|
| [Serper.dev](https://serper.dev) | Real Google search results, `live_fetch`'s fallback manufacturer-resolution step (§[How it works](#how-it-works)) | Third-party search API, not affiliated with Unilog |
| Manufacturer's own website (dynamic — resolved per-row at request time via `MANUFACTURER_DOMAINS` in [`source_discovery.py`](backend/specledger/source_discovery.py)) | Real HTTP-fetched product pages and PDF datasheets under `live_fetch=true` | Live, not archived — a re-run may see updated manufacturer content |
| `MANUFACTURER_DOMAINS` registry itself (~20 manufacturers) | Maps a canonical manufacturer name to its known official domain(s), so `live_fetch` knows where to look | **Self-curated by us**, not sourced from any official Unilog manufacturer/brand list — the Solution Guide references a much larger one, but it was never made available to participants; ours was built by hand from public manufacturer websites |
| [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`) | Real text extraction from fetched manufacturer PDF datasheets | Open-source library, AGPL-3.0 (with a commercial option from Artifex) — used here as a hackathon prototype dependency |

Nothing in the enrichment path reads from a private or paywalled dataset. If you re-run this against your own catalogue, the only outbound calls are to Serper.dev (optional, requires your own `SERPER_API_KEY`) and whatever manufacturer domains your data resolves to.

---

## Benchmark results

**Against Unilog's own 2 real worked examples** (the only official ground truth available — see table above): SpecLedger correctly extracts the part number for both, but gets manufacturer/brand wrong for both in its default mode, because the raw input's manufacturer field is actually the *distributor* ("Appliance Dealers Cooperative"), not the manufacturer — the real answer ("Frigidaire", "Whirlpool Corporation") isn't derivable from the 6 input columns alone. With real web search enabled (`live_fetch=true`, see [How it works](#how-it-works)), the pipeline correctly identified "Frigidaire" from a genuine Google search hit; it did not find "Whirlpool" because whirlpool.com's own product page didn't rank in the top search results for that query. This is reported as-is, not smoothed over — 2 examples is a very small sample, and this is the honest result on it.

**Self-generated 200-row synthetic benchmark** (fictional data, not Unilog's — see caveat above; useful only for catching regressions in our own normalization logic):

| Metric | Score |
|---|---|
| Overall exact-match accuracy | 94.37% |
| Category classification | 100.0% (200/200) |
| Part number extraction | 100.0% (200/200) |
| Material normalization | 95.0% (190/200) |
| Manufacturer resolution | 90.0% (180/200) |

These are scored on request rather than transcribed — `GET /catalogue/evaluation/synthetic` re-runs the evaluation against the committed input/ground-truth pair and returns what the pipeline currently achieves, and the dashboard reads that endpoint instead of hardcoded constants. An earlier version of this table did hardcode them, and they had quietly drifted from reality (94.64% claimed vs 94.37% actual, 93.5% manufacturer claimed vs 90.0% actual) after changes to the enrichment logic. Reproduce with:

```bash
curl -s https://specledger-production.up.railway.app/catalogue/evaluation/synthetic
```

**These numbers are reproducible on demand, not transcribed.** `POST /catalogue/batches/{batch_id}/benchmark` re-runs enrichment, validation, and 252-column synthesis over a batch's persisted raw values and returns the timings measured during that request, broken down per stage. The dashboard's "Run benchmark" button calls exactly that endpoint against whichever batch is loaded — including one you uploaded yourself — and displays nothing until a real run returns. Run it twice and the figures move, because they're measured rather than replayed:

```bash
curl -X POST https://specledger-production.up.railway.app/catalogue/batches/latest/benchmark
```

**Official 1,000-SKU challenge input**, deterministic pipeline, freshly measured (not a stale/hand-written figure):

```
Rows processed       : 1,000
Wall-clock time       : 0.134s
Throughput            : ~7,500 rows/sec
Field verified_rate   : 38.1% (fraction of all fields matched against reference data)
Auto-approve rate     : 20.0% — 200 of 1,000 rows clear validation without a human
```

These numbers are worth explaining honestly rather than hiding. `verified_rate` is lower than earlier drafts of this README claimed (an unsourced "94.6%" figure that didn't trace back to any actual test run — corrected here).

Auto-approval was previously reported as a flat 0%, and that was a real bug, not a business-rule outcome: three of the six raw columns (`Unilog_Brand`, and most of `E1_Brand`/`DIB_Brand`) encode "no value" as a descriptive placeholder phrase (`-- Unbranded --`, `-- No Unilog Brand --`, `-- No DIB Brand --`) rather than a bare null token like `"n/a"`. The enrichment pipeline's placeholder detector only recognized bare tokens, so it tried to match these phrases against the brand reference list as if they were real values, failed (correctly — they aren't brand names), and that failure was flagged as an unresolved warning that unconditionally blocked auto-approval on nearly every row, regardless of category. A second, compounding bug: fields correctly identified as missing still contributed a 0.0 confidence score into the row's overall-confidence average, dragging every row below the auto-approve threshold even when every other field was solid. Both are now fixed in [`enrichment.py`](backend/specledger/enrichment.py) — the placeholder detector recognizes this dataset's actual null convention, and missing/placeholder fields are excluded from confidence averaging rather than penalized as failed matches.

The remaining 80% that still route to human review do so for a genuine, disclosed reason, not a bug: `part_manuf`, `dib_brand`, and `e1_brand` frequently contain real values (`3M`, `TREX`, `Southwire`, `Jam Industrial Supply LLC (JAMIN)`) that our small, self-authored reference lists simply don't contain — see [Datasets & provenance](#datasets--provenance) on never having obtained Unilog's real 27,000-row manufacturer file. We deliberately did not hardcode matches for these specific values to inflate the auto-approve number; an honest "we don't recognize this manufacturer, route to a human" is the correct behavior for a real controlled-vocabulary gate, and closing that gap for real would mean wiring in Unilog's actual reference data, not pattern-matching this one sample file.

This is a CPU pipeline benchmark on deterministic transformations — not a claim about live web-retrieval latency or production infrastructure throughput.

---

## Evaluation criteria

Per UniHack's own team briefing, judging centers on the **approach**, not the technology choices behind it — specifically: quality of approach, accuracy of data, scalability, and innovation.

| Criterion | How SpecLedger addresses it |
|---|---|
| **Quality of approach** | A deterministic, auditable pipeline: every transformation retains source lineage, ambiguous rows route to a confidence-gated human review queue instead of silently guessing, and known limitations (simulated vs. live modes, the reference-data coverage gap above) are stated rather than hidden. FastAPI/Postgres/React are implementation details in service of that approach, not the pitch itself. |
| **Accuracy of data** | Tested against Unilog's own real worked examples, not just self-generated data (see [Benchmark results](#benchmark-results)) — including reporting where it currently gets the real answer wrong and why. Cross-field physics validation (e.g. rejecting a PVC part rated above 600 PSI) catches errors a naive field-by-field pipeline would miss. |
| **Scalability** | Chunked batch processing with source memoization; Postgres-backed persistence built for horizontal scaling; ~7,000 rows/sec measured on demand via `POST /catalogue/batches/{id}/benchmark`, not transcribed — raw throughput was never the bottleneck, see the [150K→750K math](#overview) above. |
| **Innovation** | A manufacturer-domain allowlist with strict marketplace-sourcing prohibition enforced at the architecture level, plus real search-based manufacturer resolution (`live_fetch=true`) for the common real-world case where the input's manufacturer field is actually a distributor. |

---

## Verify live — the claim you can check yourself

Every enriched value in a catalogue is a claim. The useful question is not whether a pipeline is confident, but whether a reviewer can **check it in one click**.

Open any row's inspector, go to **Verified Sourcing**, and press **⚡ Verify live**. Nothing is replayed — the request happens then:

1. The manufacturer's own site is fetched over real HTTP (marketplaces blocked at discovery time, never fetched)
2. A source counts as verified **only if the part number actually appears on the fetched page** — a search page echoing your query back is explicitly rejected, because that proves the search box works, not that the product exists
3. The **visible page text surrounding the part number** is captured and shown back to you
4. If a linked datasheet PDF is found, its real text is read and label/value specs extracted
5. Where the input named a distributor rather than a manufacturer, the real manufacturer is resolved by live search and confirmed on their own site

That third step is the point. You get the URL *and* the sentence, so you can open the page, search for the words, and confirm the match yourself:

```
✓ VERIFIED AGAINST LIVE MANUFACTURER SOURCE          fetched just now · 15.1s
  Source fetched
  https://diablotools.com/products/D1050X
  Text found on that page — open the link and search for it
  │ D1050X | Circular Saw Blades | Wood Cutting | Combination - Diablo Tools
```

**Failure is a first-class result.** When nothing verifies, the response says exactly that, with an empty source list — no plausible-looking URL is generated to fill the gap:

```
NO VERIFIED SOURCE FOUND
  Nothing could be confirmed for 3MABR-7100075678 right now. No value is invented
  to fill the gap — the row keeps whatever the deterministic pipeline could
  establish, and this stays unverified.
```

On real catalogue data that happens often. Manufacturers retire pages, some parts were never published on the open web, and some sites refuse automated requests. A tool that reported 100% success on this data would be lying.

```bash
curl -X POST -H "X-API-Key: $SPECLEDGER_API_KEY" \
  "https://specledger-production.up.railway.app/catalogue/batches/latest/rows/2/verify"
```

Bounded at 20 seconds. Candidates that cannot verify — search endpoints — are tried last, so the budget goes to URLs that might actually be product pages.

## Known limits

Stated plainly, because a reviewer will find these anyway and a pipeline that hides them is worth less than one that names them.

| Limit | Detail |
|---|---|
| **80% of rows still need human review** | Auto-approval is gated on controlled-vocabulary matches. The sample data is almost entirely `-- Unbranded --` placeholders and the self-authored reference tables are far smaller than Unilog's real ones, so brand matching fails often. A data gap, not an algorithmic one — see [Overview](#overview). |
| **Unilog's real reference files were never obtained** | The 27,000-row manufacturer/brand list and 161,000-row LOV file. Everything here is self-authored and much smaller. Wiring the real vocabularies in is the highest-impact accuracy work available and needs no structural change. |
| **`live_fetch` is capped at 50 rows** | It performs real network I/O, so it is deliberately not the default and not run over the full dataset. |
| **The LLM tier only classifies categories** | It does not extract attributes, write descriptions, or resolve manufacturers. Scope was kept narrow so every suggestion stays checkable against a controlled vocabulary. |
| **Marketing description is left empty** | No honest source exists for it without a live fetch of the manufacturer's own page, so the field is blank rather than generated. |
| **Reviewer identity is not authenticated** | Write endpoints share a single API key and accept any `reviewer` string. Real per-user identity is the main gap between this and a multi-tenant product. |
| **The review queue is process-local** | It rebuilds from Postgres on restart, so decisions are durable, but concurrent reviewers across replicas would need row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`). Single-writer today. |
| **`organization_id` is a query parameter** | It namespaces data but is not bound to an authenticated session, so it is not tenant isolation. |
| **Video and third-party sources are typed but not implemented** | `SourceType` models them; only HTML pages and PDF datasheets are actually read. |

## API reference

REST endpoints under `/catalogue` (FastAPI, OpenAPI docs at `/docs` on any running instance):

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/catalogue/ingest?live_fetch=true` | Upload CSV/TSV/XLSX, enrich, validate, route for review. `live_fetch=true` does real manufacturer-site HTTP verification instead of templated candidates (50-row cap) |
| `GET` | `/catalogue/batches/{id}` | Batch details, review summary, metrics |
| `GET` | `/catalogue/batches/{id}/rows/{num}` | Single row with evidence and review history |
| `GET` | `/catalogue/batches/{id}/review/pending` | Pending review rows, priority-ordered |
| `POST` | `/catalogue/batches/{id}/rows/{num}/review` | Approve / reject / correct a row |
| `GET` | `/catalogue/batches/{id}/sources` | Discovered manufacturer sources |
| `GET` | `/catalogue/batches/{id}/export?format=...` | Export as `unilog_template`, `schema_org`, `jsonld`, `csv`, `commerce_csv`, `json`, `audit` |
| `POST` | `/catalogue/batches/{id}/rows/{num}/verify` | Fetch this row's manufacturer sources live and return the URL, the page snippet containing the part number, and any specs read from a linked datasheet |
| `POST` | `/catalogue/batches/{id}/evaluate` | Ground-truth evaluation against a reference CSV |
| `GET` | `/catalogue/reference/manufacturers`, `/brands` | Canonical reference data |

Write endpoints (`POST`/`PATCH`) require an `X-API-Key` header in production.

---

## Web dashboard

React + TypeScript + Vite, 7 workspace views: Overview, Catalogue, Human Review, Imports & Telemetry, Schemas & Taxonomy, Evidence Library, Audit Trail.

- "Live web fetch" toggle on catalogue upload — real manufacturer-site HTTP verification instead of templated candidates (see [How it works](#how-it-works))
- Interactive 252-column spec inspector per SKU, backed by a dedicated endpoint (`GET /catalogue/batches/{id}/rows/{n}/unilog252`) that returns the real computed record — the same one the CSV export writes, not a separate approximation. Sparse real coverage (e.g. "3 of 50 attributes populated") is shown honestly rather than padded to look complete
- Real per-SKU category classification (`classify_category()`, keyword-based on the description + manufacturer) surfaced in the catalogue table and category filter chips — the raw 6-column input has no category field, so this is the only classification available
- Priority review queue: approve / reject / correct, with one-click bulk-approve at ≥80% confidence; the queue rebuilds itself from Postgres if the in-memory cache is lost on a redeploy, so it never falsely reports "all verified" when it's actually just empty
- Real audit trail (`GET /catalogue/batches/{id}/audit`) — every row's routing decision and every human action, not a static example
- Side-by-side evidence modal comparing raw supplier values against normalized output; unverified (pattern-guessed, never fetched) source URLs render as plain text, not clickable links, so they're never mistaken for verified ones
- Batch telemetry: throughput, latency percentiles, cost-per-SKU
- One-click exports: Unilog 252-column CSV, Commerce PIM CSV

---

## Environment variables

| Variable | Where | Required | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Backend | **Yes** | Postgres connection string. The service refuses to start without it — see [Running locally](#running-locally). |
| `SPECLEDGER_API_KEY` | Backend | No | Gates `POST`/`PATCH` `/catalogue/*` endpoints behind an `X-API-Key` header. Unset → the check is a no-op (local dev/CI only; always set in the deployed instance). |
| `SERPER_API_KEY` | Backend | No | Enables `live_fetch`'s real web-search fallback via [Serper.dev](https://serper.dev). Unset → search fallback is skipped, direct-domain fetching still works. |
| `GEMINI_API_KEY` | Backend | No | Enables the opt-in LLM tier for rows the deterministic classifier leaves unresolved. Unset → `ai_assist=true` is a no-op and the pipeline is unchanged. |
| `SPECLEDGER_LLM_MODEL` | Backend | No | Model for the LLM tier (default `gemini-3.6-flash`). |
| `SPECLEDGER_LLM_BATCH_SIZE` | Backend | No | Products per LLM request (default 25). Higher = fewer calls. |
| `SPECLEDGER_LLM_INPUT_RATE`, `SPECLEDGER_LLM_OUTPUT_RATE` | Backend | No | Per-million-token rates used to derive reported cost. Configuration, not measurement — token counts come from the API. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET` | Backend | No | Object storage for extraction artifacts. Unset → falls back to local disk storage. |
| `VITE_API_URL` | Frontend build | Yes (prod) | Base URL the dashboard calls for the API. Baked in at build time. |
| `VITE_API_KEY` | Frontend build | No | Sent as `X-API-Key` on write requests. **Not a real secret** — GitHub Pages is a static host, so this value ends up readable in the shipped JS bundle. It deters casual/scripted abuse, not a determined reader of the bundle; see [SECURITY.md](SECURITY.md) for the full note. |

---

## Running locally

**PostgreSQL is required.** SpecLedger stores catalogue batches, review decisions and audit history in Postgres and refuses to start without it — a service that silently falls back to ephemeral storage looks healthy while losing every approval on restart. A `docker-compose.yml` is included so this is one command:

```bash
git clone https://github.com/Yashasm18/specledger.git
cd specledger

# 1. PostgreSQL
docker compose up -d
export DATABASE_URL=postgresql://specledger:specledger_dev_only@localhost:5432/specledger

# 2. Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/apply_migrations.py          # idempotent; safe to re-run
uvicorn backend.specledger.http_api:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev   # http://localhost:5174

# 4. Tests — no database needed (see below)
pip install -r requirements-dev.txt
python -m pytest tests/ -v   # 282 passed, 1 skipped
```

Confirm the backend is on Postgres, not something else:

```bash
curl -s localhost:8000/health/features   # -> "database": "postgres"
```

**Tests are the one exception.** They run in milliseconds on any machine without provisioning a database, via an ephemeral in-memory store. That exception is opted into *explicitly* (`SPECLEDGER_ALLOW_EPHEMERAL_STORE=1`, set in [`tests/conftest.py`](tests/conftest.py)) rather than being inferred from an absent `DATABASE_URL` — inferring it is precisely the ambiguity the strict check removes. Nothing outside the test suite may use it.

**To run the full pipeline against your own dataset** rather than the bundled Unilog sample: `POST /catalogue/ingest` with your CSV/TSV/XLSX (see [API reference](#api-reference)) — the pipeline makes no assumption about column names beyond the keyword-based role detection in [`enrichment.py`](backend/specledger/enrichment.py)'s `detect_role()`.


---

## Repository structure

```
specledger/
├── backend/specledger/
│   ├── http_api.py               # FastAPI app entry point, auth, rate limiting
│   ├── catalogue_api.py          # Catalogue ingestion/review/export router
│   ├── catalogue_ingestion.py    # Parsing & normalization primitives
│   ├── source_discovery.py       # Manufacturer source discovery & marketplace blocker
│   ├── web_enricher.py           # Domain-agnostic enrichment & taxonomy
│   ├── validation_engine.py      # Deterministic validation rules
│   ├── human_review.py           # Review queue, state machine, audit trail
│   ├── export.py, unilog_exporter.py  # Multi-format exporters
│   ├── reference_data.py, uom.py # Controlled vocabularies
│   ├── postgres_repository.py, catalogue_persistence.py  # Postgres + in-memory stores
│   ├── object_store.py           # Supabase Storage / local disk object store
│   ├── auth.py, rate_limit.py    # API-key gate, rate limiting
│   └── evaluator.py              # Ground-truth evaluation scoring
├── data/
│   ├── challenge/                 # Official Unilog dataset + expected output
│   ├── ground_truth/              # Evaluation benchmarks
│   └── reference/                 # Reference data overrides
├── frontend/                      # React + Vite dashboard
├── migrations/                    # Postgres schema migrations
├── tests/                         # 252 backend tests + 6 frontend tests
├── Dockerfile                      # Railway deploy config
└── .github/workflows/             # CI + GitHub Pages deploy
```

---

*Built for UniHack 2026 by Yashas M.*
