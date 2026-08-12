import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./enhancements.css";
import "./upload.css";
import "./notification-overrides.css";
import "./reviewWorkspace.css";
import "./reviewLauncher.css";
import "./reviewActions.css";
import { openReviewWorkspace } from "./reviewWorkspace";

const defaultRows = [
  ["VLV-600-050", "Ball Valve · DN50", "Acme Industrial", "Valve", "Needs review", "2 conflicts"],
  ["PMP-CEN-220", "Centrifugal Pump", "FlowCore Systems", "Pump", "Ready", "98% complete"],
  ["FIT-SS-025", "Stainless Elbow", "Northstar Components", "Fitting", "Needs review", "1 missing field"],
];

function App() {
  const [selected, setSelected] = useState(0);
  const [activeTab, setActiveTab] = useState<"overview" | "catalogue" | "review" | "imports" | "schemas" | "evidence" | "audit">("overview");
  const [filterMode, setFilterMode] = useState<"all" | "review" | "changed">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [notice, setNotice] = useState("");

  const [activeBatch, setActiveBatch] = useState<any>(null);
  const [liveRows, setLiveRows] = useState<any[]>([]);
  const [pendingReviews, setPendingReviews] = useState<any[]>([]);

  // Fetch active catalogue batches on mount
  useEffect(() => {
    fetchLatestBatch();
  }, []);

  const fetchLatestBatch = async () => {
    try {
      const res = await fetch("http://localhost:8000/catalogue/batches");
      if (res.ok) {
        const data = await res.json();
        if (data.batches && data.batches.length > 0) {
          const latestId = data.batches[0].batch_id;
          const batchRes = await fetch(`http://localhost:8000/catalogue/batches/${latestId}`);
          if (batchRes.ok) {
            const batch = await batchRes.json();
            setActiveBatch(batch);
            setLiveRows(batch.rows || []);
          }
          const pendingRes = await fetch(`http://localhost:8000/catalogue/batches/${latestId}/review/pending`);
          if (pendingRes.ok) {
            const pending = await pendingRes.json();
            setPendingReviews(pending.pending_rows || []);
          }
        }
      }
    } catch (err) {
      console.log("Backend offline or not yet reachable");
    }
  };

  // Setup Document & Catalogue Intake Button listener
  useEffect(() => {
    const button = document.querySelector("header .primary");
    if (!button) return;

    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/pdf,.csv,.tsv,.xlsx";
    input.hidden = true;

    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;

      const isSpreadsheet = file.name.endsWith(".csv") || file.name.endsWith(".tsv") || file.name.endsWith(".xlsx");

      if (isSpreadsheet) {
        setNotice(`Ingesting catalogue ${file.name} for AI enrichment…`);
        const body = new FormData();
        body.append("file", file);

        try {
          const response = await fetch("http://localhost:8000/catalogue/ingest?process_immediately=true", {
            method: "POST",
            body,
          });

          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `Upload failed (${response.status})`);
          }

          const result = await response.json();
          setNotice(`Enrichment complete · ${file.name} (${result.row_count} SKUs)`);
          await fetchLatestBatch();
        } catch (error) {
          setNotice(`Ingestion failed · ${error instanceof Error ? error.message : "backend unavailable"}`);
        }
      } else {
        // PDF intake flow (durable extraction worker)
        setNotice(`Storing document and queueing extraction…`);
        const body = new FormData();
        body.append("file", file);

        try {
          const response = await fetch("http://localhost:8000/documents/intake?organization_id=default&category=generic", {
            method: "POST",
            body,
          });

          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `Upload failed (${response.status})`);
          }

          const result = await response.json();
          if (result.state === "already_registered") {
            setNotice(`Already registered · ${file.name}`);
            return;
          }

          setNotice(`Queued ${file.name} · task ${result.task_id.slice(0, 8)}`);
          const poll = window.setInterval(async () => {
            const status = await fetch(`http://localhost:8000/documents/tasks/${result.task_id}?organization_id=default`).then((r) => r.json());
            if (status.state === "completed" || status.state === "failed") {
              window.clearInterval(poll);
              setNotice(status.state === "completed" ? `Extraction complete · ${file.name}` : `Extraction failed · ${status.error_message || "retry required"}`);
            }
          }, 1200);
          window.setTimeout(() => window.clearInterval(poll), 30000);
        } catch (error) {
          setNotice(`Upload failed · ${error instanceof Error ? error.message : "backend unavailable"}`);
        }
      }
    };

    document.body.appendChild(input);
    const click = () => input.click();
    button.addEventListener("click", click);

    return () => {
      button.removeEventListener("click", click);
      input.remove();
    };
  }, []);

  // Toast Notification Stack
  useEffect(() => {
    if (!notice) return;
    let stack = document.getElementById("specledger-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "specledger-toast-stack";
      stack.setAttribute("role", "status");
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }

    const node = document.createElement("div");
    node.className = "specledger-toast-item";
    const complete = notice.toLowerCase().includes("complete");
    const queued = notice.toLowerCase().includes("queued") || notice.toLowerCase().includes("ingesting");

    node.innerHTML = `<span class="toast-check ${complete ? "success" : "queued"}">${complete ? "✓" : queued ? "↗" : "↑"}</span><span class="toast-copy"><strong>${complete ? "Pipeline complete" : queued ? "Extraction queued" : "Document stored"}</strong><small>${notice}</small></span><button class="toast-close" aria-label="Dismiss notification">×</button><div class="toast-progress"></div>`;
    stack.appendChild(node);

    const timer = window.setTimeout(() => {
      node.classList.add("toast-exit");
      window.setTimeout(() => {
        node.remove();
        if (!stack?.children.length) stack?.remove();
      }, 300);
    }, complete ? 6500 : 8500);

    node.querySelector(".toast-close")?.addEventListener("click", () => {
      window.clearTimeout(timer);
      node.classList.add("toast-exit");
      window.setTimeout(() => {
        node.remove();
        if (!stack?.children.length) stack?.remove();
      }, 300);
    }, { once: true });
  }, [notice]);

  // Open evidence review workspace
  const openRowReview = (row: any) => {
    if (!row) return;

    // Convert enriched row fields into Fact format for Evidence Review Workspace
    const facts = row.fields
      ? row.fields.map((f: any) => ({
          name: f.column,
          value: f.canonical_value || f.raw_value || "—",
          normalized_value: f.canonical_value || "",
          normalized_unit: f.normalized_unit || "",
          page: f.evidence?.source_row || 1,
          confidence: f.confidence || 0.85,
          evidence: f.evidence?.transformation ? `Transformation: ${f.evidence.transformation}` : `Field: ${f.column}`,
        }))
      : [
          { name: "Product SKU", value: row[0], confidence: 0.98, page: 1, evidence: `Part number ${row[0]}` },
          { name: "Description", value: row[1], confidence: 0.95, page: 1, evidence: `Description text ${row[1]}` },
          { name: "Source Manufacturer", value: row[2], confidence: 0.92, page: 1, evidence: `Manufacturer ${row[2]}` },
        ];

    openReviewWorkspace({
      data: { facts },
      review_state: row.overall_status || row[4] || "pending_review",
    });
  };

  const handleExport = (format: string) => {
    if (activeBatch) {
      window.open(`http://localhost:8000/catalogue/batches/${activeBatch.batch_id}/export?format=${format}`, "_blank");
      setNotice(`Exporting catalogue batch in ${format.toUpperCase()} format…`);
    } else {
      setNotice(`Exporting sample catalogue dataset in ${format.toUpperCase()} format…`);
    }
  };

  // Compute table rows based on active batch vs fallback
  const displayRows = liveRows.length > 0
    ? liveRows.map((r: any) => {
        const skuField = r.fields?.find((f: any) => f.role === "part_number")?.canonical_value || `ROW-${r.row_number}`;
        const descField = r.fields?.find((f: any) => f.role === "description")?.canonical_value || `Item #${r.row_number}`;
        const mfrField = r.fields?.find((f: any) => f.role === "manufacturer")?.canonical_value || "Industrial Mfr";
        const catField = r.fields?.find((f: any) => f.role === "category")?.canonical_value || "Component";
        const status = r.overall_status === "verified" || r.overall_status === "approved" ? "Ready" : "Needs review";
        const quality = `${Math.round((r.overall_confidence || 0.94) * 100)}% verified`;
        return [skuField, `${descField}`, mfrField, catField, status, quality, r];
      })
    : defaultRows;

  // Filter rows
  const filteredRows = displayRows.filter((r: any) => {
    if (filterMode === "review" && r[4] !== "Needs review") return false;
    if (searchQuery && !r[0].toLowerCase().includes(searchQuery.toLowerCase()) && !r[1].toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  // Overview metrics are derived from the active batch rather than demo values.
  const allLiveFields = liveRows.flatMap((row: any) => row.fields || []);
  const evidenceCoverage = allLiveFields.length
    ? allLiveFields.filter((field: any) => field.evidence?.source_file || field.evidence?.transformation).length / allLiveFields.length
    : 0;
  const verifiedRate = activeBatch?.verified_rate ?? 0;
  const reviewCount = activeBatch?.review_summary?.pending_review
    ?? activeBatch?.validation_summary?.review_required_count
    ?? pendingReviews.length;
  const throughput = activeBatch?.metrics?.throughput_rows_per_sec;

  return (
    <div className="app">
      {/* Left Sidebar */}
      <aside>
        <div className="logo">
          <span>SL</span>
          <div>
            SpecLedger
            <small>PRODUCT INTELLIGENCE</small>
          </div>
        </div>

        <div className="workspace">
          <span className="workspace-dot" /> Unilog workspace <b>⌄</b>
        </div>

        <div className="nav-group">
          <label>WORKSPACE</label>
          <a
            className={activeTab === "overview" ? "active" : ""}
            onClick={() => setActiveTab("overview")}
          >
            ⌂ Overview <kbd>⌘ 1</kbd>
          </a>
          <a
            className={activeTab === "catalogue" ? "active" : ""}
            onClick={() => setActiveTab("catalogue")}
          >
            ▦ Catalogue <kbd>⌘ 2</kbd>
          </a>
          <a
            className={activeTab === "review" ? "active" : ""}
            onClick={() => setActiveTab("review")}
          >
            ◌ Review queue <i>{reviewCount}</i>
          </a>
          <a
            className={activeTab === "imports" ? "active" : ""}
            onClick={() => setActiveTab("imports")}
          >
            ↳ Imports
          </a>
        </div>

        <div className="nav-group">
          <label>GOVERNANCE</label>
          <a
            className={activeTab === "schemas" ? "active" : ""}
            onClick={() => setActiveTab("schemas")}
          >
            ◇ Schemas
          </a>
          <a
            className={activeTab === "evidence" ? "active" : ""}
            onClick={() => setActiveTab("evidence")}
          >
            ◎ Evidence library
          </a>
          <a
            className={activeTab === "audit" ? "active" : ""}
            onClick={() => setActiveTab("audit")}
          >
            ⌁ Audit trail
          </a>
        </div>

        <div className="sidebar-bottom">
          <div className="health">
            <span /> All systems operational
          </div>
          <div className="user">
            <strong>YM</strong>
            <span>
              Yashas M<small>Owner</small>
            </span>
            <b>···</b>
          </div>
        </div>
      </aside>

      {/* Main Panel */}
      <main>
        <header>
          <div>
            <span className="crumb">
              Workspace / {activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}
            </span>
            <h1>Good evening, Yashas <span>✦</span></h1>
          </div>

          <div className="header-actions">
            <button className="icon" title="Export CSV" onClick={() => handleExport("csv")}>
              ↓
            </button>
            <button className="icon" title="Export Commerce PIM" onClick={() => handleExport("commerce_csv")}>
              🛒
            </button>
            <button className="primary">+ Import documents</button>
          </div>
        </header>

        <div className="content">
          {/* Hero Banner */}
          <section className="intro">
            <div>
              <p className="eyebrow">CATALOGUE CONTROL CENTER</p>
              <h2>
                Know what changed<br />
                <em>before it ships.</em>
              </h2>
              <p>
                SpecLedger turns fragmented technical documents into evidence-backed product records your commerce team can trust.
              </p>
            </div>
            <div className="pipeline">
              <div className="pipeline-title">
                PROCESSING PIPELINE <span>LIVE</span>
              </div>
              <div className="steps">
                <b>01 <small>INGEST</small></b>
                <i>→</i>
                <b>02 <small>EXTRACT</small></b>
                <i>→</i>
                <b>03 <small>VALIDATE</small></b>
                <i>→</i>
                <b>04 <small>APPROVE</small></b>
              </div>
            </div>
          </section>

          {/* Metrics Cards */}
          <section className="metrics">
            <article>
              <span>PRODUCT RECORDS</span>
              <strong>{activeBatch?.row_count ?? 0}</strong>
              <small className="up">{activeBatch ? "Current enrichment batch" : "Upload a batch to begin"}</small>
            </article>
            <article>
              <span>REVIEW QUEUE</span>
              <strong className="amber">{reviewCount}</strong>
              <small>{activeBatch ? "Requires human verification" : "No active batch"}</small>
            </article>
            <article>
              <span>CATALOGUE HEALTH</span>
              <strong>{Math.round(verifiedRate * 100)}<span className="percent">%</span></strong>
              <small className="up">{activeBatch ? "Validated fields in active batch" : "No verified data yet"}</small>
            </article>
            <article>
              <span>EVIDENCE COVERAGE</span>
              <strong>{Math.round(evidenceCoverage * 100)}<span className="percent">%</span></strong>
              <small>{activeBatch ? `Across ${activeBatch.total_fields ?? allLiveFields.length} attributes${throughput ? ` · ${throughput} rows/sec` : ""}` : "No source evidence yet"}</small>
            </article>
          </section>

          {/* Catalogue Table */}
          <section className="section-card">
            <div className="table-head">
              <div>
                <p className="eyebrow">RECENT PRODUCT RECORDS</p>
                <h3>Catalogue activity</h3>
              </div>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <button className="view" onClick={() => handleExport("unilog_template")} style={{ background: "rgba(99, 102, 241, 0.15)", borderColor: "rgba(99, 102, 241, 0.4)", color: "#818cf8" }}>
                  Unilog 252-Col CSV ↓
                </button>
                <button className="view" onClick={() => handleExport("commerce_csv")}>
                  Export PIM CSV ↓
                </button>
                <button className="view" onClick={() => handleExport("audit")}>
                  Audit Lineage ↓
                </button>
              </div>

            </div>

            <div className="filters">
              <button
                className={`filter ${filterMode === "all" ? "active" : ""}`}
                onClick={() => setFilterMode("all")}
              >
                All records <b>{displayRows.length}</b>
              </button>
              <button
                className={`filter ${filterMode === "review" ? "active" : ""}`}
                onClick={() => setFilterMode("review")}
              >
                Needs review <b>{reviewCount}</b>
              </button>
              <button
                className={`filter ${filterMode === "changed" ? "active" : ""}`}
                onClick={() => setFilterMode("changed")}
              >
                Recently changed
              </button>
              <div className="search" style={{ display: "flex", alignItems: "center" }}>
                <input
                  type="text"
                  placeholder="⌕ Search records..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{ border: "none", outline: "none", background: "transparent", color: "inherit", width: "100%", font: "inherit" }}
                />
              </div>
            </div>

            <div className="table">
              <div className="tr th">
                <span>PRODUCT / SKU</span>
                <span>SOURCE</span>
                <span>CATEGORY</span>
                <span>STATUS</span>
                <span>QUALITY</span>
              </div>
              {filteredRows.map((r: any, i: number) => (
                <div
                  className={`tr ${selected === i ? "selected" : ""}`}
                  onClick={() => {
                    setSelected(i);
                    openRowReview(r[6] || r);
                  }}
                  key={r[0] + i}
                >
                  <span>
                    <strong>{r[0]}</strong>
                    <small>{r[1]}</small>
                  </span>
                  <span>{r[2]}</span>
                  <span className="tag">{r[3]}</span>
                  <span>
                    <mark className={r[4] === "Ready" ? "ready" : "review"}>
                      ● {r[4]}
                    </mark>
                  </span>
                  <span className="quality">
                    {r[5]} <b>›</b>
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Audit Trail & Next Best Action */}
          <section className="bottom-grid">
            <div className="section-card activity">
              <div className="table-head">
                <div>
                  <p className="eyebrow">AUDIT TRAIL</p>
                  <h3>Recent decisions</h3>
                </div>
                <button className="view" onClick={() => setActiveTab("audit")}>View all →</button>
              </div>
              <p>
                <b>Yashas M.</b> approved <strong>PMP-CEN-220</strong>
                <small>8 minutes ago · 14 attributes verified</small>
              </p>
              <p>
                <b>SpecLedger</b> flagged a conflict in <strong>VLV-600-050</strong>
                <small>24 minutes ago · Pressure rating differs on page 4</small>
              </p>
            </div>

            <div className="section-card next">
              <p className="eyebrow">NEXT BEST ACTION</p>
              <h3>Resolve your highest-impact conflict</h3>
              <p>
                Two pressure ratings disagree for <b>VLV-600-050</b>. Review the source evidence before it reaches a sales channel.
              </p>
              <button
                className="primary"
                onClick={() => {
                  openRowReview(displayRows[0]?.[6] || displayRows[0]);
                }}
              >
                Open review queue →
              </button>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
