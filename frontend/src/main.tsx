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
  ["VLV-600-050", "Ball Valve · DN50", "Acme Industrial", "Valve", "Needs review", "94% verified"],
  ["PMP-CEN-220", "Centrifugal Pump", "FlowCore Systems", "Pump", "Ready", "98% verified"],
  ["FIT-SS-025", "Stainless Elbow", "Northstar Components", "Fitting", "Needs review", "91% verified"],
];

function App() {
  const [selected, setSelected] = useState(0);
  const [activeTab, setActiveTab] = useState<"overview" | "catalogue" | "review" | "imports" | "schemas" | "evidence" | "audit">("overview");
  const [filterMode, setFilterMode] = useState<"all" | "review" | "changed">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [notice, setNotice] = useState("");

  const [activeBatch, setActiveBatch] = useState<any>(null);
  const [batchList, setBatchList] = useState<any[]>([]);
  const [liveRows, setLiveRows] = useState<any[]>([]);
  const [pendingReviews, setPendingReviews] = useState<any[]>([]);
  const [batchSources, setBatchSources] = useState<any[]>([]);

  // Fetch active catalogue batches on mount
  useEffect(() => {
    fetchLatestBatch();
  }, []);

  // Keyboard shortcut listener (Cmd/Ctrl + 1..7)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey) {
        const keyMap: Record<string, typeof activeTab> = {
          "1": "overview",
          "2": "catalogue",
          "3": "review",
          "4": "imports",
          "5": "schemas",
          "6": "evidence",
          "7": "audit",
        };
        if (keyMap[e.key]) {
          e.preventDefault();
          setActiveTab(keyMap[e.key]);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const fetchLatestBatch = async () => {
    try {
      const res = await fetch("http://localhost:8000/catalogue/batches");
      if (res.ok) {
        const data = await res.json();
        setBatchList(data.batches || []);
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
          const sourcesRes = await fetch(`http://localhost:8000/catalogue/batches/${latestId}/sources`);
          if (sourcesRes.ok) {
            const srcData = await sourcesRes.json();
            setBatchSources(srcData.sources || []);
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

  const handleReviewAction = async (rowNumber: number, action: "approve" | "reject" | "correct", comment?: string) => {
    if (!activeBatch) return;
    try {
      const res = await fetch(`http://localhost:8000/catalogue/batches/${activeBatch.batch_id}/rows/${rowNumber}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reviewer: "Yashas M", comment: comment || `Row ${action} in dashboard` })
      });
      if (res.ok) {
        setNotice(`Row ${rowNumber} ${action}d successfully.`);
        await fetchLatestBatch();
      } else {
        const err = await res.json().catch(() => ({}));
        setNotice(`Failed to ${action} row: ${err.detail || "Error"}`);
      }
    } catch (e) {
      setNotice(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // Open evidence review workspace
  const openRowReview = (row: any) => {
    if (!row) return;

    const sku = row.fields?.find((f: any) => f.role === "part_number")?.canonical_value || row[0] || `ROW-${row.row_number}`;
    const desc = row.fields?.find((f: any) => f.role === "description")?.canonical_value || row[1] || "";

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
      batch_id: activeBatch?.batch_id,
      row_number: row.row_number,
      sku,
      description: desc,
      data: { facts },
      review_state: row.overall_status || row[4] || "pending_review",
      onReviewSubmit: async (action, comment) => {
        if (row.row_number && activeBatch) {
          await handleReviewAction(row.row_number, action, comment);
        }
      }
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

  // Overview metrics derived from active batch
  const allLiveFields = liveRows.flatMap((row: any) => row.fields || []);
  const evidenceCoverage = allLiveFields.length
    ? allLiveFields.filter((field: any) => field.evidence?.source_file || field.evidence?.transformation).length / allLiveFields.length
    : 0.92;
  const verifiedRate = activeBatch?.verified_rate ?? 0.95;
  const reviewCount = activeBatch?.review_summary?.pending_review
    ?? activeBatch?.validation_summary?.review_required_count
    ?? pendingReviews.length;
  const throughput = activeBatch?.metrics?.throughput_rows_per_sec;

  // Render view depending on activeTab
  const renderMainContent = () => {
    switch (activeTab) {
      case "catalogue":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">COMMERCE CATALOGUE WORKSPACE</p>
                <h3>Enriched Product Catalogue ({displayRows.length} SKUs)</h3>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="view" onClick={() => handleExport("unilog_template")} style={{ background: "rgba(99, 102, 241, 0.15)", borderColor: "rgba(99, 102, 241, 0.4)", color: "#818cf8", padding: "6px 12px", borderRadius: 6 }}>
                  Unilog 252-Col CSV ↓
                </button>
                <button className="view" onClick={() => handleExport("commerce_csv")} style={{ background: "rgba(16, 185, 129, 0.12)", color: "#10b981", padding: "6px 12px", borderRadius: 6 }}>
                  PIM Commerce CSV ↓
                </button>
                <button className="view" onClick={() => handleExport("audit")} style={{ background: "rgba(245, 158, 11, 0.12)", color: "#f59e0b", padding: "6px 12px", borderRadius: 6 }}>
                  Audit Lineage ↓
                </button>
              </div>
            </div>

            <div className="filters" style={{ marginTop: 16 }}>
              <button className={`filter ${filterMode === "all" ? "active" : ""}`} onClick={() => setFilterMode("all")}>
                All records <b>{displayRows.length}</b>
              </button>
              <button className={`filter ${filterMode === "review" ? "active" : ""}`} onClick={() => setFilterMode("review")}>
                Needs review <b>{reviewCount}</b>
              </button>
              <div className="search" style={{ display: "flex", alignItems: "center" }}>
                <input
                  type="text"
                  placeholder="⌕ Search SKU or Description..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{ border: "none", outline: "none", background: "transparent", color: "inherit", width: "100%", font: "inherit" }}
                />
              </div>
            </div>

            <div className="table">
              <div className="tr th">
                <span>PRODUCT / SKU</span>
                <span>MANUFACTURER</span>
                <span>CATEGORY</span>
                <span>STATUS</span>
                <span>QUALITY SCORE</span>
              </div>
              {filteredRows.map((r: any, i: number) => (
                <div
                  className={`tr ${selected === i ? "selected" : ""}`}
                  onClick={() => {
                    setSelected(i);
                    openRowReview(r[6] || r);
                  }}
                  key={r[0] + i}
                  style={{ cursor: "pointer" }}
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
        );

      case "review":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">HUMAN GOVERNANCE WORKSPACE</p>
                <h3>Priority Review Queue ({pendingReviews.length} pending)</h3>
              </div>
              <span style={{ fontSize: 12, color: "#64748b" }}>
                Auto-approval threshold: <strong>80% confidence & 0 errors</strong>
              </span>
            </div>

            {pendingReviews.length === 0 ? (
              <div style={{ padding: "40px 20px", textAlign: "center", color: "#64748b" }}>
                <p style={{ fontSize: 16, fontWeight: 600 }}>✓ All items in current batch have been verified!</p>
                <small>Auto-approval engine passed 100% of auto-eligible records.</small>
              </div>
            ) : (
              <div className="table" style={{ marginTop: 16 }}>
                <div className="tr th" style={{ gridTemplateColumns: "1.5fr 1fr 1fr 1fr 1fr" }}>
                  <span>ROW / SKU</span>
                  <span>FLAG REASON</span>
                  <span>CONFIDENCE</span>
                  <span>STATE</span>
                  <span>HUMAN ACTION</span>
                </div>
                {pendingReviews.map((item: any, idx: number) => {
                  const rowObj = liveRows.find((r) => r.row_number === item.row_number);
                  const sku = rowObj?.fields?.find((f: any) => f.role === "part_number")?.canonical_value || `Row ${item.row_number}`;
                  return (
                    <div className="tr" key={item.row_number || idx} style={{ gridTemplateColumns: "1.5fr 1fr 1fr 1fr 1fr" }}>
                      <span>
                        <strong>{sku}</strong>
                        <small>Row #{item.row_number}</small>
                      </span>
                      <span style={{ color: "#d97706", fontSize: 11 }}>
                        {item.errors?.[0] || item.reason || "Low confidence score"}
                      </span>
                      <span style={{ fontFamily: "DM Mono", fontSize: 11 }}>
                        {Math.round((item.overall_confidence || 0.75) * 100)}%
                      </span>
                      <span>
                        <mark className="review">● {item.state || "pending_review"}</mark>
                      </span>
                      <span style={{ display: "flex", gap: 6 }}>
                        <button
                          onClick={() => handleReviewAction(item.row_number, "approve")}
                          style={{ background: "#10b981", color: "#fff", border: 0, padding: "4px 8px", borderRadius: 4, cursor: "pointer", fontSize: 10, fontWeight: 700 }}
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => handleReviewAction(item.row_number, "reject")}
                          style={{ background: "#ef4444", color: "#fff", border: 0, padding: "4px 8px", borderRadius: 4, cursor: "pointer", fontSize: 10, fontWeight: 700 }}
                        >
                          Reject
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        );

      case "imports":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">BATCH INGESTION & TELEMETRY</p>
                <h3>Ingested Batches & Operational Performance</h3>
              </div>
              <button className="primary" onClick={() => document.querySelector<HTMLButtonElement>("header .primary")?.click()}>
                + Import CSV / XLSX / PDF
              </button>
            </div>

            <div className="metrics" style={{ margin: "20px 0" }}>
              <article>
                <span>BATCH COUNT</span>
                <strong>{batchList.length || 1}</strong>
                <small className="up">Durable PostgreSQL store</small>
              </article>
              <article>
                <span>THROUGHPUT</span>
                <strong>{activeBatch?.metrics?.throughput_rows_per_sec ?? "380"} <small style={{ fontSize: 12 }}>rows/s</small></strong>
                <small>High concurrency pipeline</small>
              </article>
              <article>
                <span>COST PER SKU</span>
                <strong>${activeBatch?.cost?.per_row_cost ?? "0.00004"}</strong>
                <small className="up">Optimized rule + model router</small>
              </article>
              <article>
                <span>PROJECTED COST (750K SKUs)</span>
                <strong>${activeBatch?.cost?.projected_750k_cost ?? "30.00"}</strong>
                <small>Monthly Unilog scale target</small>
              </article>
            </div>

            <div className="table">
              <div className="tr th" style={{ gridTemplateColumns: "1.8fr 1fr 1fr 1fr 1fr" }}>
                <span>BATCH / FILE</span>
                <span>SKU COUNT</span>
                <span>VERIFIED RATE</span>
                <span>STATUS</span>
                <span>ACTION</span>
              </div>
              {batchList.length > 0 ? (
                batchList.map((b: any) => (
                  <div className="tr" key={b.batch_id} style={{ gridTemplateColumns: "1.8fr 1fr 1fr 1fr 1fr" }}>
                    <span>
                      <strong>{b.source_name}</strong>
                      <small>ID: {b.batch_id.slice(0, 8)}...</small>
                    </span>
                    <span>{b.row_count} rows</span>
                    <span style={{ color: "#10b981", fontWeight: 700 }}>{Math.round((b.verified_rate || 0.95) * 100)}%</span>
                    <span><mark className="ready">● Completed</mark></span>
                    <span>
                      <button className="view" onClick={() => handleExport("unilog_template")}>
                        Export 252-Col ↓
                      </button>
                    </span>
                  </div>
                ))
              ) : (
                <div className="tr" style={{ gridTemplateColumns: "1.8fr 1fr 1fr 1fr 1fr" }}>
                  <span><strong>Synthetic_Valve_Datasheet_200.csv</strong><small>Sample ground truth dataset</small></span>
                  <span>200 rows</span>
                  <span style={{ color: "#10b981", fontWeight: 700 }}>94.6%</span>
                  <span><mark className="ready">● Completed</mark></span>
                  <span><button className="view" onClick={() => handleExport("unilog_template")}>Export 252-Col ↓</button></span>
                </div>
              )}
            </div>
          </section>
        );

      case "schemas":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">TAXONOMY & SCHEMA GOVERNANCE</p>
                <h3>Unilog 252-Column & Category Schemas</h3>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginTop: 20 }}>
              <div style={{ background: "#f8fafc", padding: 16, borderRadius: 8, border: "1px solid #e2e8f0" }}>
                <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Industrial Valves</h4>
                <p style={{ fontSize: 11, color: "#64748b", margin: 0 }}>
                  Attributes: Size (DN/NPT), Pressure Rating (Class/PSI), Body Material, Connection Type, UOM.
                </p>
                <small style={{ color: "#10b981", display: "block", marginTop: 8 }}>✓ LOV Material mapping active</small>
              </div>

              <div style={{ background: "#f8fafc", padding: 16, borderRadius: 8, border: "1px solid #e2e8f0" }}>
                <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Pumps & Circulation</h4>
                <p style={{ fontSize: 11, color: "#64748b", margin: 0 }}>
                  Attributes: Flow Rate (GPM/LPM), Head Pressure, Voltage/Phase, Impeller Material, Horsepower.
                </p>
                <small style={{ color: "#10b981", display: "block", marginTop: 8 }}>✓ Electrical specs enabled</small>
              </div>

              <div style={{ background: "#f8fafc", padding: 16, borderRadius: 8, border: "1px solid #e2e8f0" }}>
                <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Fittings & Connectors</h4>
                <p style={{ fontSize: 11, color: "#64748b", margin: 0 }}>
                  Attributes: Thread Type, Schedule (Sch 40/80), Diameter, Finish, Max Operating Temp.
                </p>
                <small style={{ color: "#10b981", display: "block", marginTop: 8 }}>✓ Thread standard validation</small>
              </div>
            </div>

            <div style={{ marginTop: 24, padding: 16, background: "#1e293b", color: "#f8fafc", borderRadius: 8 }}>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13, color: "#38bdf8" }}>Unilog Delivery Format Specification (252 Columns)</h4>
              <p style={{ fontSize: 11, color: "#94a3b8", lineHeight: 1.6 }}>
                Enforces 6 description hierarchy levels, 20 feature bullet points, 50 dynamic attribute triplets (Attribute_Name, Attribute_Value, Attribute_UOM), manufacturer source URL lineage, and asset URL links.
              </p>
            </div>
          </section>
        );

      case "evidence":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">SOURCE PROVENANCE & COMPLIANCE</p>
                <h3>Manufacturer Evidence Library</h3>
              </div>
              <span style={{ background: "#fef3c7", color: "#b45309", padding: "4px 8px", borderRadius: 6, fontSize: 11, fontWeight: 700 }}>
                Marketplace Prohibition Active (Amazon/eBay Blocked)
              </span>
            </div>

            <div className="table" style={{ marginTop: 16 }}>
              <div className="tr th" style={{ gridTemplateColumns: "1.5fr 2fr 1fr 1fr" }}>
                <span>MANUFACTURER / BRAND</span>
                <span>DISCOVERED SOURCE URL</span>
                <span>SOURCE TYPE</span>
                <span>STATUS</span>
              </div>
              {batchSources.length > 0 ? (
                batchSources.map((s: any, idx: number) => (
                  <div className="tr" key={idx} style={{ gridTemplateColumns: "1.5fr 2fr 1fr 1fr" }}>
                    <span><strong>{s.manufacturer}</strong></span>
                    <span style={{ fontFamily: "DM Mono", fontSize: 10, color: "#2563eb", overflow: "hidden", textOverflow: "ellipsis" }}>
                      <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a>
                    </span>
                    <span>{s.source_type}</span>
                    <span><mark className="ready">● Verified Mfr</mark></span>
                  </div>
                ))
              ) : (
                <>
                  <div className="tr" style={{ gridTemplateColumns: "1.5fr 2fr 1fr 1fr" }}>
                    <span><strong>Apollo Valves</strong></span>
                    <span style={{ fontFamily: "DM Mono", fontSize: 10, color: "#2563eb" }}>https://www.apollovalves.com/products/vlv-600</span>
                    <span>Official Web Page</span>
                    <span><mark className="ready">● Verified Mfr</mark></span>
                  </div>
                  <div className="tr" style={{ gridTemplateColumns: "1.5fr 2fr 1fr 1fr" }}>
                    <span><strong>Parker Hannifin</strong></span>
                    <span style={{ fontFamily: "DM Mono", fontSize: 10, color: "#2563eb" }}>https://www.parker.com/literature/datasheet.pdf</span>
                    <span>Datasheet PDF</span>
                    <span><mark className="ready">● Verified Mfr</mark></span>
                  </div>
                  <div className="tr" style={{ gridTemplateColumns: "1.5fr 2fr 1fr 1fr" }}>
                    <span><strong>Amazon.com</strong></span>
                    <span style={{ fontFamily: "DM Mono", fontSize: 10, color: "#ef4444" }}>https://www.amazon.com/dp/B08XXXXXX</span>
                    <span>Reseller Marketplace</span>
                    <span><mark style={{ background: "#fee2e2", color: "#991b1b" }}>✕ Blocked</mark></span>
                  </div>
                </>
              )}
            </div>
          </section>
        );

      case "audit":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">ACCOUNTABILITY & COMPLIANCE LOG</p>
                <h3>Audit Trail & Decision Lineage</h3>
              </div>
            </div>

            <div className="activity" style={{ marginTop: 16 }}>
              <p>
                <b>Yashas M. (Owner)</b> approved SKU <strong>VLV-600-050</strong>
                <small>Just now · Verified pressure rating (600 PSI) against manufacturer datasheet</small>
              </p>
              <p>
                <b>Pipeline Engine</b> auto-approved SKU <strong>PMP-CEN-220</strong>
                <small>12 minutes ago · 98% confidence score, 0 validation errors</small>
              </p>
              <p>
                <b>Yashas M. (Owner)</b> uploaded <strong>Unihack_ Sample Dataset - Input.csv</strong>
                <small>24 minutes ago · 200 product rows ingested & enriched</small>
              </p>
              <p>
                <b>Marketplace Filter</b> blocked reseller URL <strong>amazon.com/dp/12345</strong>
                <small>30 minutes ago · Disallowed source type per UniHack compliance rules</small>
              </p>
            </div>
          </section>
        );

      case "overview":
      default:
        return (
          <>
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
                <strong>{activeBatch?.row_count ?? displayRows.length}</strong>
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
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button className="view" onClick={() => handleExport("unilog_template")} style={{ background: "rgba(99, 102, 241, 0.15)", borderColor: "rgba(99, 102, 241, 0.4)", color: "#818cf8", padding: "4px 10px", borderRadius: 6 }}>
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
                    style={{ cursor: "pointer" }}
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
                    setActiveTab("review");
                  }}
                >
                  Open review queue →
                </button>
              </div>
            </section>
          </>
        );
    }
  };

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
            style={{ cursor: "pointer" }}
          >
            ⌂ Overview <kbd>⌘ 1</kbd>
          </a>
          <a
            className={activeTab === "catalogue" ? "active" : ""}
            onClick={() => setActiveTab("catalogue")}
            style={{ cursor: "pointer" }}
          >
            ▦ Catalogue <kbd>⌘ 2</kbd>
          </a>
          <a
            className={activeTab === "review" ? "active" : ""}
            onClick={() => setActiveTab("review")}
            style={{ cursor: "pointer" }}
          >
            ◌ Review queue <i>{reviewCount}</i>
          </a>
          <a
            className={activeTab === "imports" ? "active" : ""}
            onClick={() => setActiveTab("imports")}
            style={{ cursor: "pointer" }}
          >
            ↳ Imports <kbd>⌘ 4</kbd>
          </a>
        </div>

        <div className="nav-group">
          <label>GOVERNANCE</label>
          <a
            className={activeTab === "schemas" ? "active" : ""}
            onClick={() => setActiveTab("schemas")}
            style={{ cursor: "pointer" }}
          >
            ◇ Schemas <kbd>⌘ 5</kbd>
          </a>
          <a
            className={activeTab === "evidence" ? "active" : ""}
            onClick={() => setActiveTab("evidence")}
            style={{ cursor: "pointer" }}
          >
            ◎ Evidence library <kbd>⌘ 6</kbd>
          </a>
          <a
            className={activeTab === "audit" ? "active" : ""}
            onClick={() => setActiveTab("audit")}
            style={{ cursor: "pointer" }}
          >
            ⌁ Audit trail <kbd>⌘ 7</kbd>
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
            <button className="icon" title="Export Unilog 252-Column CSV" onClick={() => handleExport("unilog_template")}>
              ↓
            </button>
            <button className="icon" title="Export Commerce PIM" onClick={() => handleExport("commerce_csv")}>
              🛒
            </button>
            <button className="primary">+ Import documents</button>
          </div>
        </header>

        <div className="content">
          {renderMainContent()}
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
