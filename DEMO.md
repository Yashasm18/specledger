# SpecLedger — UniHack Hackathon Pitch & Demo Guide

**Project Name:** SpecLedger  
**Target Platform:** Unilog CX1 Catalogue Intelligence & PIM Pipeline  
**Target Scale:** 150,000 to 750,000 SKUs/month  
**Benchmark Performance:** **94.64% Ground-Truth Accuracy** across 200 industrial SKUs (**238/238 passing unit tests**)  
**Delivery Format:** Official Unilog **252-Column Template Format** (`Unihack_ Expected Output - Delivery Format.csv`)

---

## 🎙️ 3-Minute Demo Pitch Script

### Minute 1: The Problem & Live Upload (0:00 - 1:00)
> *"Industrial B2B distributors process hundreds of thousands of raw SKUs from component manufacturers. Ingested data is incomplete, misspelled, missing UOMs, or lacking material and pressure specifications. Manually fixing this is expensive, slow, and error-prone."*
>
> *"SpecLedger is a production-grade, evidence-backed catalogue enrichment engine built specifically for Unilog. Watch what happens when we upload a raw, un-enriched industrial catalogue spreadsheet into SpecLedger."*

**Action:** Click **"Import documents"** → select `Unihack_ Sample Dataset - Input.csv` or sample CSV.

---

### Minute 2: AI Enrichment & Validation (1:00 - 2:00)
> *"In less than a second, SpecLedger executes our domain-agnostic 4-stage pipeline:"*
> 1. **Prefix & LOV Intelligence:** Normalizes manufacturers and controlled materials (e.g. `Freud Inc (2435)` → `Freud Inc`, `SS316` → `Stainless Steel 316`).
> 2. **Domain-Agnostic Web Extraction:** Generates 6 description levels, 20 feature bullets, and 50 dynamic key-value-unit attribute triplets.
> 3. **Deterministic Validation Engine:** Runs 6 validation rule suites and auto-approves records meeting $\ge 80\%$ confidence and 0 errors.
> 4. **Strict Source Lineage:** Every attribute retains a verifiable evidence trail citing official manufacturer URLs, while marketplace sites (Amazon, eBay, Alibaba) are strictly blocked.

**Action:** Click on any SKU row to open the **Evidence Review Workspace**. Show the raw vs canonical values, confidence badges, and source evidence citations.

---

### Minute 3: Governance, Scale Telemetry & 252-Column Export (2:00 - 3:00)
> *"For governance, low-confidence or contradictory rows route automatically to our Priority Review Queue (`⌘ 3`) with inline human approve/reject actions."*
>
> *"Our Batch Telemetry (`⌘ 4`) measures real-world throughput (380+ rows/sec) and projects our cost at just $30 for 750,000 SKUs/month."*
>
> *"Finally, we export the enriched catalogue in Unilog's exact 252-column template format with one click."*

**Action 1:** Switch to **Review Queue (`⌘ 3`)** → show pending items and one-click inline review actions.  
**Action 2:** Click **"Unilog 252-Col CSV ↓"** → open the exported CSV matching Unilog's official delivery format.

> *"SpecLedger turns messy supplier data into commerce-ready product intelligence backed by total lineage proof. Thank you!"*

---

## 🛠️ Step-by-Step Local Running Guide for Judges

### 1. Start the FastAPI Backend
```bash
cd /Users/yashas/Documents/UniHack
source .venv/bin/activate
uvicorn backend.specledger.http_api:app --reload --port 8000
```

### 2. Start the React Frontend
```bash
cd /Users/yashas/Documents/UniHack/frontend
npm run dev
# Open http://localhost:5174
```

### 3. Run the Unit Test Suite
```bash
.venv/bin/python -m pytest tests/ -v
# 238 passed in ~1.3 seconds (100%)
```
