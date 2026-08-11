# SpecLedger — UniHack Hackathon Pitch & Demo Guide

**Project Name:** SpecLedger  
**Target Platform:** Unilog CX1 Catalogue Intelligence & PIM Pipeline  
**Target Scale:** 150,000 to 750,000 SKUs/month  
**Benchmark Performance:** **94.67% Ground-Truth Accuracy** across 200 industrial valve SKUs (233/233 passing unit tests)

---

## 🎙️ 3-Minute Demo Pitch Script

### Minute 1: The Problem & Live Upload (0:00 - 1:00)
> *"Industrial B2B distributors process hundreds of thousands of raw SKUs from component manufacturers. Ingested data is incomplete, misspelled, missing UOMs, or lacking material specifications. Manually fixing this is expensive, slow, and error-prone."*
>
> *"SpecLedger is a production-grade, evidence-backed catalogue enrichment engine built for Unilog. Watch what happens when we upload a raw, messy 200-row industrial valve spreadsheet into SpecLedger."*

**Action:** Click **"Import Catalogue CSV"** → select `data/ground_truth/synthetic_200_input.csv`.

---

### Minute 2: AI Enrichment & Validation (1:00 - 2:00)
> *"In less than a second, SpecLedger runs our 4-stage pipeline:"*
> 1. **Prefix Intelligence:** Identifies `APO-` → Apollo Valves, `PAR-` → Parker Hannifin.
> 2. **LOV Controlled Vocabulary:** Canonicalizes `SS316` → `Stainless Steel 316`, `CI` → `Cast Iron`.
> 3. **Deterministic Rules Engine:** Validates completeness, cross-field consistency (PVC vs 1500 psi), and auto-approves high-confidence rows.
> 4. **Evidence Lineage:** Every single attribute retains a verifiable evidence trail.

**Action:** Click on Row #1 to open the **Field Intelligence Modal**. Show the raw vs canonical values, confidence bar, and transformation lineage.

---

### Minute 3: Governance, Benchmarking & Export (2:00 - 3:00)
> *"We adhere strictly to UniHack guidelines — consumer marketplaces like Amazon and Alibaba are permanently blocked, and low-confidence rows automatically route to our Priority Human Review Queue."*
>
> *"Let's run our ground-truth evaluator live against the 200-row industrial benchmark."*

**Action 1:** Click **"🎯 Evaluate Accuracy"** → show the live **94.67% exact accuracy score** and per-attribute breakdown.  
**Action 2:** Go to **Multi-Format Exports** → click **"Download Commerce PIM CSV"** and **"Download Lineage Audit JSON"**.

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
# Open http://localhost:5173
```

### 3. Run the Unit Test Suite
```bash
.venv/bin/python -m pytest tests/ -v
# 233 passed in ~1.0 second
```
