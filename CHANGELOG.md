# Changelog

All notable changes to **SpecLedger** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-08-14

### Added
- **Multi-Format Ingestion:** Ingest CSV, TSV, XLSX, and PDF files with automatic supplier header mapping and bracket cleaning.
- **Authoritative Sourcing Engine:** Discover verified manufacturer URLs, datasheets, and user manuals while strictly blocking reseller marketplaces.
- **Dynamic 50-Attribute Triplet Engine:** Dynamic mapping for `ATTRIBUTE_LABEL`, `ATTRIBUTE_VALUE`, and `ATTRIBUTE_UOM` (1..50).
- **Domain-Agnostic Intelligence:** Comprehensive coverage across HVAC, Plumbing, Electrical, Machinery, Abrasives, Tools, Lighting, and Consumer Appliances.
- **Dual-Mode System:** Headless batch REST API (4,250+ SKUs/sec) and dark-mode React/Vite Control Center (`localhost:5174`).
- **Human-in-the-Loop (HITL) Review Queue:** Interactive side-by-side evidence inspection, 1-click approvals, and immutable SHA-256 audit logs.
- **Standards & Delivery Syndication:** Official Unilog CX1 252-column template CSV exporter, `schema.org/Product` JSON-LD graph, and flat Commerce PIM format.
- **Evaluation Benchmark Engine:** Ground-truth accuracy scoring (94.64% exact-match rate on 200-row benchmark).
- **Automated CI & Code Quality:** Continuous integration testing with GitHub Actions and 9.86/10 Pylint score.
