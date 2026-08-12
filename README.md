# SpecLedger — AI-Powered Industrial Product Intelligence & Catalogue Enrichment

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![React + Vite](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB.svg)](https://vitejs.dev/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%20%2B%20Migration%20007-4169E1.svg)](https://www.postgresql.org/)
[![Tests](https://img.shields.io/badge/Tests-233%20Passed%20(100%25)-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **UniHack Challenge Submission** — Transforming limited, unstructured industrial catalogue data into rich, evidence-backed, commerce-ready product intelligence at a scale of **150,000 to 750,000 SKUs/month**.

---

## Executive Summary

Industrial B2B commerce platforms (such as Unilog CX1 PIM) process hundreds of thousands of raw SKUs from thousands of component manufacturers. Ingested data is frequently fragmented, misspelled, missing units of measure (UOM), or lacking material and pressure specifications.

**SpecLedger** is a production-grade, evidence-backed catalogue enrichment engine. It cleans, normalizes, validates, enriches, and audits industrial product records before they reach sales channels.

### Core Guarantee: Grounded Provenance & Human Governance
- **Zero Hallucination:** Every enriched attribute is backed by an explicit evidence trail (source file, row number, column, transformation, or manufacturer URL).
- **Marketplace Prohibition:** In strict compliance with UniHack requirements, **Amazon, eBay, Alibaba, Walmart, and consumer shopping sites are blocked**. All enrichment data is derived from manufacturer-authoritative sources.
- **Human-in-the-Loop:** High-confidence records are auto-approved, while low-confidence or contradictory records are automatically routed to a priority-ordered review queue.

---

## Key Features & Performance Metrics

### 🎯 Ground-Truth Evaluation Benchmark (200-Row Dataset)
Evaluated against the official 200-row industrial valve ground-truth benchmark (`data/ground_truth/synthetic_200_valves.csv`):

| Metric | Score | Detail |
|--------|-------|--------|
| **Overall Exact Match Accuracy** | **94.64%** | Exact match across all attributes |
| **Average Row Accuracy** | **96.59%** | Average correct attributes per row |
| **Category Accuracy** | **100.0%** | 200 / 200 exact matches |
| **Part Number Accuracy** | **100.0%** | 200 / 200 exact matches |
| **Description Accuracy** | **100.0%** | 200 / 200 exact matches |
| **Material Accuracy** | **94.50%** | 189 / 200 exact matches (via alias & abbreviation matching) |
| **Size & UOM Accuracy** | **95.00%** | 190 / 200 exact matches |
| **Pressure Rating Accuracy** | **93.50%** | 187 / 200 exact matches |

---

## System Architecture

```mermaid
flowchart TD
    A[Raw Input: CSV / TSV / XLSX] --> B[Catalogue Ingestion Engine]
    B --> C[Role Detection & Normalization]
    
    subgraph Enrichment Subsystem
        C --> D1[LOV Controlled Vocabulary Match]
        C --> D2[SKU Prefix Intelligence]
        C --> D3[Description Pattern Parser]
        C --> D4[UOM & Material Normalizer]
    end
    
    D1 & D2 & D3 & D4 --> E[Enriched Batch Assembly]
    
    subgraph Governance & Verification
        E --> F[Deterministic Validation Engine]
        F --> G{Auto-Approve?}
        G -- Yes (Conf >= 80%, 0 Errors) --> H[Auto-Approved Store]
        G -- No (Conf < 80% or Issues) --> I[Priority Review Queue]
        I --> J[Human Review Workspace]
        J -- Approve / Reject / Correct --> K[Audit Trail Logger]
    end
    
    subgraph Commerce Syndication
        H & K --> L1[Enriched CSV Export]
        H & K --> L2[Commerce PIM Export]
        H & K --> L3[Structured JSON Export]
        H & K --> L4[Full Audit JSON Export]
    end
```

---

## 📦 Core Subsystems

### 1. Ingestion & Role Detection (`catalogue_ingestion.py`, `enrichment.py`)
- Ingests CSV, TSV, and XLSX spreadsheets up to 10 MB.
- Automatically detects semantic column roles (`manufacturer`, `brand`, `category`, `part_number`, `material`, `size`, `uom`, `pressure`, `connection_type`, `description`).
- Computes SHA-256 source fingerprints for row-level idempotency and change tracking.

### 2. Controlled Vocabularies & SKU Intelligence (`reference_data.py`, `uom.py`)
- **Reference Store:** 20 canonical industrial manufacturers (Parker Hannifin, Emerson Electric, Honeywell, Flowserve, Crane Co., Watts, Apollo, Nibco, Milwaukee Valve, Kitz, Velan, Swagelok, Victaulic, etc.), 14 brands, and 18 product categories.
- **Material Normalization:** Maps 30+ material variants and abbreviations (`CI` → Cast Iron, `DI` → Ductile Iron, `CS` → Carbon Steel, `SS316` → Stainless Steel 316, `PTFE` → Teflon).
- **SKU Prefix Intelligence:** Automatically infers canonical manufacturer names from 3-letter part number prefixes (`APO-` → Apollo Valves, `PAR-` → Parker Hannifin, `VIC-` → Victaulic).
- **Description Extraction:** Parses raw unstructured description text when attribute columns are missing or blank.

### 3. Validation & Auto-Approval Engine (`validation_engine.py`)
Executes 6 rule categories against every enriched record:
1. **Required Fields by Category:** Category-specific schema validation (e.g. Ball Valves require `material`, `size`, `pressure_rating`).
2. **LOV Membership:** Flags unrecognized manufacturers or materials.
3. **Cross-Field Consistency:** Checks material ↔ pressure compatibility (e.g. PVC incompatible with >600 psi).
4. **Completeness Scoring:** Calculates fraction of schema fields populated.
5. **Batch Anomaly Detection:** Detects duplicate part numbers across batch rows.
6. **Character Limits:** Enforces maximum character lengths for PIM/ERP export compatibility.

### 4. Human Review & Audit Queue (`human_review.py`)
- Priority-ordered queue prioritizing rows with errors or low confidence.
- State machine: `pending_review` → `auto_approved` | `approved` | `rejected` | `corrected`.
- Logs an immutable `AuditEvent` for every reviewer decision (who reviewed, timestamp, previous vs. new state, corrections applied).

### 5. Source Discovery & Marketplace Blocker (`source_discovery.py`)
- Discovers authoritative product pages and datasheets from official manufacturer domains.
- **Marketplace Blocker:** Explicitly rejects Amazon, eBay, Alibaba, Walmart, Home Depot, Zoro, Grainger, and consumer shopping URLs.

### 6. Batch Infrastructure & Cost Tracking (`batch_processor.py`)
- Chunked processing with source memoization cache.
- Tracks execution metrics: throughput (rows/sec), latencies (p50, p95, p99), failure rate.
- Real-time cost modeling: computes per-row cost and projects monthly operational costs at **150,000 SKUs/month** and **750,000 SKUs/month**.

### 7. Multi-Format Exporters (`export.py`)
- **Enriched CSV:** Includes raw, canonical, confidence score, and verification status for every field.
- **Commerce-Ready CSV:** Flat structure with canonical attributes formatted for direct import into PIM/ERP systems.
- **Structured JSON:** Full attribute graph with evidence citations.
- **Audit JSON:** Complete lineage showing supplier raw value → transformation applied → evidence source → review decision.

---

## API Reference

The FastAPI backend exposes comprehensive endpoints under `/catalogue`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/catalogue/ingest` | Upload CSV/TSV/XLSX file, enrich, validate, and route |
| `GET` | `/catalogue/batches/{id}` | Retrieve batch details, review summary, metrics, and cost |
| `GET` | `/catalogue/batches/{id}/rows/{num}` | Retrieve single row with field details, evidence, and review history |
| `GET` | `/catalogue/batches/{id}/review/pending` | List pending review rows ordered by priority |
| `POST` | `/catalogue/batches/{id}/rows/{num}/review` | Submit review action (`approve`, `reject`, `correct`) |
| `GET` | `/catalogue/batches/{id}/sources` | Retrieve manufacturer sources discovered for batch |
| `GET` | `/catalogue/batches/{id}/export?format=...` | Export batch as `csv`, `commerce_csv`, `json`, or `audit` |
| `POST` | `/catalogue/batches/{id}/evaluate` | Run ground-truth evaluation against reference CSV |
| `GET` | `/catalogue/reference/manufacturers` | List canonical manufacturers in reference store |
| `GET` | `/catalogue/reference/brands` | List canonical brands in reference store |
| `POST` | `/catalogue/reference/normalize/uom` | Normalize a raw UOM string |

---

## 🖥️ Web Dashboard (React + Vite)

The frontend application provides a modern, dark-mode, glassmorphic review workspace for catalogue engineers:

- **Live Processing Pipeline:** Ingest → Extract → Validate → Approve progress indicator.
- **Evidence Review Workspace:** Side-by-side view comparing raw supplier values, normalized values, confidence scores, and source evidence citations.
- **Toast Notifications:** Real-time updates for batch uploads, task status, and review approvals.

### Running the Application Locally

#### 1. Backend (FastAPI)
```bash
# Clone the repository
git clone https://github.com/Yashasm18/specledger.git
cd specledger

# Set up virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest httpx

# Run the FastAPI server
uvicorn backend.specledger.http_api:app --reload --port 8000
```

#### 2. Frontend (React + Vite)
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5174 or http://localhost:5173
```

#### 3. Run Automated Tests
```bash
.venv/bin/python -m pytest tests/ -v
# 233 passed in ~1.2 seconds
```

---

## 📊 Database & Deployment

SpecLedger supports two persistence modes:
1. **In-Memory Store:** Ideal for local testing, rapid prototyping, and CI pipelines without database dependencies.
2. **PostgreSQL Store (`migrations/007_catalogue_reference.sql`):** Migration 007 defines production tables:
   - `catalogue_batches`: Batch metadata, source fingerprint, row count, verified rate.
   - `catalogue_rows`: Row-level JSONB raw & enriched values, overall status, review state (`pending_review`, `approved`, etc.), reviewer ID, and timestamps.
   - `reference_manufacturers`, `reference_brands`, `reference_uom`: Controlled vocabulary tables.
   - `evaluation_runs`: Historical ground-truth evaluation reports.

To enable PostgreSQL, set the environment variable:
```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/specledger"
```

---

## 📁 Repository Structure

```
specledger/
├── backend/specledger/
│   ├── catalogue_api.py        # FastAPI router for catalogue endpoints
│   ├── catalogue_ingestion.py  # Ingestion & normalization primitives
│   ├── enrichment.py           # Field-level enrichment pipeline & description extraction
│   ├── validation_engine.py    # Deterministic validation rules & auto-approval logic
│   ├── human_review.py         # Priority review queue, state machine & audit trail
│   ├── source_discovery.py     # Manufacturer source discovery & marketplace blocker
│   ├── batch_processor.py      # Chunked processing, source cache, metrics & cost model
│   ├── export.py               # Enriched CSV, Commerce CSV, JSON & Audit JSON exporters
│   ├── catalogue_persistence.py# PostgreSQL (migration 007) & in-memory persistence
│   ├── reference_data.py       # Controlled vocabulary reference store (20 mfrs, 14 brands)
│   ├── uom.py                  # UOM normalization & material canonical dictionary
│   ├── evaluator.py            # Ground-truth evaluation scoring engine
│   ├── http_api.py             # Main FastAPI application entry point
│   ├── postgres_repository.py  # Product & version PostgreSQL repository
│   └── models.py               # Core typed domain primitives
├── data/
│   ├── ground_truth/           # Synthetic 200-row industrial valve benchmark dataset
│   └── reference/              # Private reference data overrides
├── frontend/                   # React + Vite dashboard web application
│   ├── src/                    # Components, workspace views & CSS styles
│   └── package.json            # Vite & React dependencies
├── migrations/
│   └── 007_catalogue_reference.sql # PostgreSQL schema for catalogue & reference data
├── tests/                      # 233 comprehensive unit & integration tests
│   ├── test_catalogue_api.py
│   ├── test_catalogue_persistence.py
│   ├── test_validation_engine.py
│   ├── test_human_review.py
│   ├── test_source_discovery.py
│   ├── test_batch_processor.py
│   ├── test_export.py
│   ├── test_enrichment.py
│   ├── test_evaluator.py
│   └── test_reference_data.py
├── docs/                       # Architecture & deployment documentation
└── README.md                   # Project documentation
```

---

## 🏆 Summary of Accomplishments

- **233 / 233 Unit Tests Passing** (100% pass rate).
- **94.64% Ground-Truth Accuracy** achieved on the 200-row industrial valve benchmark.
- Complete end-to-end pipeline: **Ingest → Enrich → Discover Sources → Validate → Review → Export**.
- Fully integrated React + Vite web interface with real-time FastAPI backend connection.

---

*Built for UniHack 2026 by Yashas M.*
