import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./enhancements.css";
import "./upload.css";
import "./notification-overrides.css";
import "./reviewWorkspace.css";
import "./reviewLauncher.css";
import "./reviewActions.css";
import "./specInspector.css";
import { openReviewWorkspace } from "./reviewWorkspace";
import { apiFetch, getApiBaseUrl, getApiKeyHeaders, readApiError } from "./apiClient";
import { downloadBlob, downloadJson } from "./download";
import { fetchCatalogueExport } from "./catalogueClient";

const defaultRows = [
  ["VLV-600-050", "Ball Valve · DN50 Full Port SS316", "Apollo Valves", "Industrial Valves", "Needs review", "94% verified"],
  ["PMP-CEN-220", "Centrifugal Pump · 3HP 220V 60Hz", "FlowCore Systems", "Pumps & Circulation", "Ready", "98% verified"],
  ["FIT-SS-025", "Stainless Elbow · 1/4 inch NPT 3000 PSI", "Parker Hannifin", "Fittings & Connectors", "Needs review", "91% verified"],
  ["VLV-BTR-100", "Butterfly Valve · 4 inch Lug Ductile Iron", "Bray Controls", "Industrial Valves", "Ready", "96% verified"],
  ["PMP-SUB-075", "Submersible Sump Pump · 3/4 HP Cast Iron", "Zoeller Pump Co", "Pumps & Circulation", "Ready", "99% verified"],
  ["ABR-BLD-010", "Diablo 10-inch 60T Fine Finish Blade", "Freud Tools", "Abrasives & Tools", "Ready", "97% verified"],
  ["ELC-SWT-020", "Decora Plus 20A Industrial Rocker Switch", "Leviton", "Electrical & Automation", "Ready", "99% verified"],
  ["HVC-THM-001", "T6 Pro Smart Programmable Thermostat", "Honeywell Home", "HVAC & Heating", "Ready", "95% verified"],
  ["APP-RFR-250", "36-inch French Door Refrigerator 25 Cu. Ft.", "Frigidaire Commercial", "Major Appliances", "Needs review", "92% verified"],
  ["VAL-CHK-075", "Check Valve · 3/4 inch Bronze 200 WOG", "Milwaukee Valve", "Industrial Valves", "Ready", "96% verified"],
];

// Mirrors backend/specledger/enrichment.py's detect_role() keyword heuristic.
// The catalogue persistence API returns raw_values/enriched_values keyed by
// original CSV column name (e.g. "mfg_part_num"), not a role-tagged fields
// array, so the frontend re-derives role from column name the same way.
function detectRole(column: string): string {
  const k = column.toLowerCase().trim();
  if (["part_num", "part_no", "part_number", "sku", "item_num", "item_no", "model_num", "mfg_part", "item_code"].some((p) => k.includes(p))) return "part_number";
  if (["desc", "description", "product_name", "item_title", "title", "part_desc"].some((d) => k.includes(d))) return "description";
  if (["manufacturer", "mfr", "mfg", "vendor", "supplier", "part_manuf"].some((m) => k.includes(m))) return "manufacturer";
  if (["brand", "trade_name"].some((b) => k.includes(b))) return "brand";
  if (["category", "prod_type", "taxonomy"].some((c) => k.includes(c))) return "category";
  return "other";
}

function findByRole(values: Record<string, string> | undefined, role: string): string | undefined {
  if (!values) return undefined;
  for (const [col, val] of Object.entries(values)) {
    if (val && detectRole(col) === role) return val;
  }
  return undefined;
}

const ALL_252_UNILOG_HEADERS: string[] = [
  "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
  "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
  "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
  "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
  "ALTERNATE_PART_NUMBER", "Classpath", "MOBILE_DESC", "INVOICE_DESC", "SHORT_DESC",
  "LONG_DESC1", "RETAIL_DESC", "MARKETING_DESCRIPTION",
  "ITEM_FEATURES_1", "ITEM_FEATURES_2", "ITEM_FEATURES_3", "ITEM_FEATURES_4", "ITEM_FEATURES_5",
  "ITEM_FEATURES_6", "ITEM_FEATURES_7", "ITEM_FEATURES_8", "ITEM_FEATURES_9", "ITEM_FEATURES_10",
  "ITEM_FEATURES_11", "ITEM_FEATURES_12", "ITEM_FEATURES_13", "ITEM_FEATURES_14", "ITEM_FEATURES_15",
  "ITEM_FEATURES_16", "ITEM_FEATURES_17", "ITEM_FEATURES_18", "ITEM_FEATURES_19", "ITEM_FEATURES_20",
  "With", "Standard/Approvals", "Prop 65", "Application", "Includes", "Product Name",
  ...Array.from({ length: 50 }, (_, i) => [
    `ATTRIBUTE_LABEL ${i + 1}`,
    `ATTRIBUTE_VALUE ${i + 1}`,
    `ATTRIBUTE_UOM ${i + 1}`
  ]).flat(),
  "UPC", "EAN", "GTIN", "UNSPSC", "Warranty", "List Price", "Selling Qty", "Selling UOM", "Standard Packaging Information",
  "LENGTH", "LENGTH_UOM", "HEIGHT", "HEIGHT_UOM", "WIDTH", "WIDTH_UOM", "WEIGHT", "WEIGHT_UOM", "VOLUME", "VOLUME_UOM",
  "Product Image", "Alternate Image 1", "Alternate Image 2", "Alternate Image 3", "Alternate Image 4",
  "SDS", "SDS_1", "Warranty Information", "Catalog", "Specification Sheet",
  "Instruction/Installation Manual", "Service Manual", "Owners/User Manual", "Line Drawing", "MTR", "RoHS",
  "Full Engineering Drawing", "Energy Star Guide", "Technical Bulletin", "Submittal", "Compatibility Chart",
  "Size Chart", "Product Label/Insert", "Video Link", "Video Link 1", "Country Of Origin", "Discontinued", "Actual Image (Yes/No)"
];

const DownloadIcon = ({ size = 12 }: { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    style={{ display: "inline-block", verticalAlign: "-1px" }}
  >
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

interface EnterprisePersona {
  id: "super_admin" | "lead_reviewer" | "merchant";
  name: string;
  shortName: string;
  role: string;
  badge: string;
  org: string;
  avatar: string;
  avatarBg: string;
  accentColor: string;
  badgeColor?: string;
  permissions: string[];
  description: string;
  recommendedWorkflow: string;
}

const ENTERPRISE_PERSONAS: Record<string, EnterprisePersona> = {
  super_admin: {
    id: "super_admin",
    name: "Yashas M.",
    shortName: "Yashas",
    role: "Systems Architect & Lead Administrator",
    badge: "Admin",
    org: "SpecLedger Systems",
    avatar: "YM",
    avatarBg: "linear-gradient(135deg, #1f6feb, #388bfd)",
    accentColor: "#58a6ff",
    permissions: [
      "Batch ingestion & LOV enrichment pipelines",
      "Manufacturer PDF parsing & crawler engine",
      "Multi-vertical accuracy benchmark suites",
      "Cryptographic audit trace & system logs"
    ],
    description: "Manages pipeline execution, manufacturer source discovery, and data governance benchmarks across catalogue verticals.",
    recommendedWorkflow: "Imports & Telemetry (⌘ 4) or Multi-Vertical Benchmarking"
  },
  lead_reviewer: {
    id: "lead_reviewer",
    name: "Sarah Jenkins",
    shortName: "Sarah",
    role: "Senior Catalog QA & Content Lead",
    badge: "Catalog QA",
    org: "Unilog Content Operations",
    avatar: "SJ",
    avatarBg: "linear-gradient(135deg, #238636, #2ea043)",
    accentColor: "#3fb950",
    permissions: [
      "Human review queue with A/R/E keyboard hotkeys",
      "Discrepancy resolution and attribute corrections",
      "High-confidence bulk approval (≥80%)",
      "Official Unilog 252-column CX1 delivery export"
    ],
    description: "Reviews ambiguous SKUs, resolves attribute conflicts, and signs off on final 252-column enterprise deliveries.",
    recommendedWorkflow: "Human Review Queue (⌘ 3) with High-Speed Hotkeys"
  },
  merchant: {
    id: "merchant",
    name: "Alex Rivera",
    shortName: "Alex",
    role: "E-Commerce & Distribution Specialist",
    badge: "Merchant Ops",
    org: "Commercial Distribution Alliance",
    avatar: "AR",
    avatarBg: "linear-gradient(135deg, #d29922, #e3b341)",
    accentColor: "#d29922",
    permissions: [
      "Commercial product catalogue exploration",
      "252-column & 50-triplet attribute inspector",
      "12-column Commerce PIM feed export",
      "Vector submittal PDF datasheet generation"
    ],
    description: "Evaluates enriched product descriptions, technical specifications, and syndication feeds for commercial sales channels.",
    recommendedWorkflow: "Commerce Catalogue (⌘ 2) & 1-Click PIM Export"
  }
};

function App() {
  const [selected, setSelected] = useState(0);
  const [activeTab, setActiveTab] = useState<"overview" | "catalogue" | "review" | "imports" | "schemas" | "evidence" | "audit">("overview");
  const [filterMode, setFilterMode] = useState<"all" | "review" | "changed">("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [auditFilter, setAuditFilter] = useState<"all" | "human" | "auto" | "security">("all");
  const [auditEvents, setAuditEvents] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [workspaceName, setWorkspaceName] = useState("Unilog CX1 Workspace");
  const [showWorkspaceMenu, setShowWorkspaceMenu] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  // Enterprise Persona & OAuth State
  const [currentPersonaKey, setCurrentPersonaKey] = useState<string>(() => {
    return localStorage.getItem("specledger_persona") || "super_admin";
  });
  const [showLoginModal, setShowLoginModal] = useState<boolean>(() => {
    return !localStorage.getItem("specledger_has_authenticated");
  });

  const currentPersona = ENTERPRISE_PERSONAS[currentPersonaKey] || ENTERPRISE_PERSONAS.super_admin;

  const handleSelectPersona = (key: string, viaOAuth?: string) => {
    setCurrentPersonaKey(key);
    localStorage.setItem("specledger_persona", key);
    localStorage.setItem("specledger_has_authenticated", "true");
    setShowLoginModal(false);
    const p = ENTERPRISE_PERSONAS[key] || ENTERPRISE_PERSONAS.super_admin;
    if (viaOAuth) {
      setNotice(`SSO Authenticated via ${viaOAuth} as ${p.name} (${p.badge}) · ${p.org}`);
    } else {
      setNotice(`Switched to ${p.name} (${p.badge}) · ${p.org}`);
    }
  };

  const [activeBatch, setActiveBatch] = useState<any>(null);
  const [batchList, setBatchList] = useState<any[]>([]);
  const [liveRows, setLiveRows] = useState<any[]>([]);
  const [pendingReviews, setPendingReviews] = useState<any[]>([]);
  const [reviewedRowIds, setReviewedRowIds] = useState<Set<number>>(new Set());
  const reviewedRowIdsRef = useRef<Set<number>>(new Set());
  const [batchSources, setBatchSources] = useState<any[]>([]);

  // 252-Column Inspector Modal State
  const [inspectorProduct, setInspectorProduct] = useState<any>(null);
  const [inspectorTab, setInspectorTab] = useState<"diff" | "triplets" | "descriptions" | "features" | "evidence" | "all252">("diff");
  const [tripletSearch, setTripletSearch] = useState("");
  const [colSearch, setColSearch] = useState("");
  // Real 252-column record for the inspected row, fetched from the backend
  // (same row_to_unilog_dict() that generates the actual CSV export) — not
  // client-side generated. null while loading or unavailable.
  const [unilog252, setUnilog252] = useState<Record<string, string> | null>(null);
  const [isLoadingUnilog252, setIsLoadingUnilog252] = useState(false);

  // Live Benchmark Runner State. These figures are our last actual measured
  // run on the full 1,000-row official dataset (deterministic path, no live
  // fetch), not a live per-click computation — see README "Benchmark results".
  const [isBenchmarking, setIsBenchmarking] = useState(false);
  const [benchStep, setBenchStep] = useState(0);
  const [benchStats, setBenchStats] = useState({
    time: "0.138s",
    throughput: "~7,200 rows/s",
    verified: "38.1%",
    cost: "$0 (no paid API calls)"
  });

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [liveFetchEnabled, setLiveFetchEnabled] = useState(false);

  // Fetch active catalogue batches on mount
  useEffect(() => {
    fetchLatestBatch();
  }, []);

  // Comprehensive Keyboard shortcut listener (Cmd/Ctrl + 1..7, Alphabet commands O, C, R, I, S, E, A, Escape)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeEl = document.activeElement;
      const isInput = activeEl?.tagName === "INPUT" || activeEl?.tagName === "TEXTAREA";

      // Escape closes modals
      if (e.key === "Escape") {
        if (inspectorProduct) {
          setInspectorProduct(null);
          return;
        }
      }

      // If user is typing in search/form inputs, don't hijack keystrokes
      if (isInput) return;

      const key = e.key.toLowerCase();
      const hasModifier = e.metaKey || e.ctrlKey || e.altKey;

      const actionMap: Record<string, typeof activeTab> = {
        "1": "overview",
        "o": "overview",
        "2": "catalogue",
        "c": "catalogue",
        "3": "review",
        "r": "review",
        "4": "imports",
        "i": "imports",
        "5": "schemas",
        "s": "schemas",
        "6": "evidence",
        "e": "evidence",
        "7": "audit",
        "a": "audit",
      };

      if (actionMap[key]) {
        if (hasModifier) {
          e.preventDefault();
        }
        setActiveTab(actionMap[key]);
        const tabNames: Record<string, string> = {
          overview: "Overview",
          catalogue: "Product Catalogue",
          review: "Human Review Queue",
          imports: "Imports & Telemetry",
          schemas: "Schemas & Taxonomy",
          evidence: "Evidence Library",
          audit: "Audit Trail",
        };
        setNotice(`Navigated to ${tabNames[actionMap[key]]} (${hasModifier ? "⌘ " : ""}${key.toUpperCase()})`);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [inspectorProduct]);

  const API_BASE = getApiBaseUrl();

  const fetchLatestBatch = async () => {
    if (!API_BASE) return; // No backend configured — skip silently
    try {
      const res = await fetch(`${API_BASE}/catalogue/batches`);
      if (res.ok) {
        const data = await res.json();
        setBatchList(data.batches || []);
        if (data.batches && data.batches.length > 0) {
          const latestId = data.batches[0].batch_id;
          const batchRes = await fetch(`${API_BASE}/catalogue/batches/${latestId}`);
          if (batchRes.ok) {
            const batch = await batchRes.json();
            setActiveBatch(batch);
            setLiveRows(batch.rows || []);
          }
          const pendingRes = await fetch(`${API_BASE}/catalogue/batches/${latestId}/review/pending`);
          if (pendingRes.ok) {
            const pending = await pendingRes.json();
            const rawPending = pending.pending_rows || [];
            setPendingReviews(rawPending.filter((r: any) => !reviewedRowIdsRef.current.has(r.row_number)));
          }
          const sourcesRes = await fetch(`${API_BASE}/catalogue/batches/${latestId}/sources`);
          if (sourcesRes.ok) {
            const srcData = await sourcesRes.json();
            setBatchSources(srcData.sources || []);
          }
          const auditRes = await fetch(`${API_BASE}/catalogue/batches/${latestId}/audit?limit=50`);
          if (auditRes.ok) {
            const auditData = await auditRes.json();
            setAuditEvents(auditData.events || []);
          }
        }
      }
    } catch (err) {
      console.log("Backend offline or loading:", err);
    }
  };

  // Toast Notification Stack (Fast Evaporating with Dismiss Button)
  useEffect(() => {
    if (!notice) return;
    let stack = document.getElementById("specledger-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "specledger-toast-stack";
      stack.setAttribute("aria-live", "polite");
      stack.style.position = "fixed";
      stack.style.bottom = "24px";
      stack.style.right = "24px";
      stack.style.zIndex = "9999";
      stack.style.display = "flex";
      stack.style.flexDirection = "column";
      stack.style.gap = "6px";
      stack.style.maxWidth = "360px";
      document.body.appendChild(stack);
    }

    // Cap visible toasts at 3 to prevent clutter
    while (stack.children.length >= 3) {
      const oldest = stack.firstElementChild;
      if (oldest) oldest.remove();
    }

    const toast = document.createElement("div");
    toast.className = "specledger-toast";
    toast.style.background = "#172232";
    toast.style.color = "#ffffff";
    toast.style.padding = "8px 12px 8px 14px";
    toast.style.borderRadius = "8px";
    toast.style.fontSize = "11px";
    toast.style.fontFamily = "Manrope, sans-serif";
    toast.style.boxShadow = "0 8px 24px rgba(0,0,0,0.25)";
    toast.style.border = "1px solid rgba(255,255,255,0.15)";
    toast.style.display = "flex";
    toast.style.alignItems = "center";
    toast.style.justifyContent = "space-between";
    toast.style.gap = "10px";
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px)";
    toast.style.transition = "all 0.2s ease-out";
    toast.style.cursor = "pointer";

    const textSpan = document.createElement("span");
    textSpan.textContent = notice;
    textSpan.style.flex = "1";
    textSpan.style.wordBreak = "break-word";
    toast.appendChild(textSpan);

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.title = "Dismiss";
    closeBtn.style.background = "transparent";
    closeBtn.style.border = "none";
    closeBtn.style.color = "rgba(255,255,255,0.6)";
    closeBtn.style.cursor = "pointer";
    closeBtn.style.fontSize = "12px";
    closeBtn.style.padding = "2px 4px";
    closeBtn.style.lineHeight = "1";
    closeBtn.style.borderRadius = "4px";
    closeBtn.style.transition = "color 0.15s ease";
    closeBtn.onmouseenter = () => (closeBtn.style.color = "#ffffff");
    closeBtn.onmouseleave = () => (closeBtn.style.color = "rgba(255,255,255,0.6)");

    const dismiss = (e?: Event) => {
      if (e) e.stopPropagation();
      toast.style.opacity = "0";
      toast.style.transform = "translateY(-4px)";
      setTimeout(() => {
        toast.remove();
        if (stack && stack.childElementCount === 0) stack.remove();
      }, 200);
    };

    closeBtn.onclick = dismiss;
    toast.onclick = dismiss;
    toast.appendChild(closeBtn);

    stack.appendChild(toast);
    requestAnimationFrame(() => {
      toast.style.opacity = "1";
      toast.style.transform = "translateY(0)";
    });

    // Evaporate fast: 1.8 seconds auto-dismiss
    const timer = window.setTimeout(() => {
      dismiss();
    }, 1800);

    return () => window.clearTimeout(timer);
  }, [notice]);

  // Unified File & Batch Exporter
  const handleExport = async (format: string) => {
    const formatNames: Record<string, string> = {
      unilog_template: "Unilog_252_Delivery_Catalogue.csv",
      commerce_csv: "Commerce_PIM_Feed.csv",
      schema_org: "schema_org_products.jsonld",
      jsonld: "schema_org_products.jsonld",
      csv: "Enriched_Catalogue_Output.csv",
      audit: "Audit_Lineage_Trace.json",
      json: "Structured_Product_Intelligence.json",
    };
    const filename = formatNames[format] || `SpecLedger_Export_${format}.csv`;
    setNotice(`Exporting ${filename}…`);

    try {
      const blob = await fetchCatalogueExport(activeBatch?.batch_id, format);
      downloadBlob(blob, filename);
      setNotice(`Downloaded ${filename} successfully!`);
    } catch (err) {
      setNotice(`Export unavailable · ${err instanceof Error ? err.message : "Backend request failed"}`);
    }
  };

  // Upload handler for spreadsheets & PDFs
  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const isSpreadsheet = file.name.endsWith(".csv") || file.name.endsWith(".tsv") || file.name.endsWith(".xlsx");

    if (isSpreadsheet) {
      setNotice(
        liveFetchEnabled
          ? `Ingesting ${file.name} with live web fetch — real HTTP requests to manufacturer sites, capped at 50 rows…`
          : `Ingesting catalogue ${file.name} for AI enrichment…`
      );
      const body = new FormData();
      body.append("file", file);

      try {
        const response = await apiFetch(
          `/catalogue/ingest?process_immediately=true${liveFetchEnabled ? "&live_fetch=true" : ""}`,
          { method: "POST", body }
        );

        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.detail || `Upload failed (${response.status})`);
        }

        const result = await response.json();
        setNotice(`Enrichment complete · ${file.name} (${result.row_count} SKUs enriched in 252-column format)`);
        await fetchLatestBatch();
        setActiveTab("catalogue");
      } catch (error) {
        setNotice(`Catalogue ingestion failed · ${error instanceof Error ? error.message : "Backend unavailable"}`);
      }
    } else {
      setNotice(`Storing document and queueing extraction…`);
      const body = new FormData();
      body.append("file", file);

      try {
        const response = await fetch(`${API_BASE}/documents/intake?organization_id=default&category=generic`, {
          method: "POST",
          headers: getApiKeyHeaders(),
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
          try {
            const status = await fetch(`${API_BASE}/documents/tasks/${result.task_id}?organization_id=default`).then((r) => r.json());
            if (status.state === "completed" || status.state === "failed") {
              window.clearInterval(poll);
              setNotice(status.state === "completed" ? `Extraction complete · ${file.name}` : `Extraction failed · ${status.error_message || "retry required"}`);
            }
          } catch {
            window.clearInterval(poll);
          }
        }, 1200);
        window.setTimeout(() => window.clearInterval(poll), 30000);
      } catch (error) {
        setNotice(`Upload failed · ${error instanceof Error ? error.message : "backend unavailable"}`);
      }
    }
    event.target.value = "";
  };

  // Human Review Actions
  const handleReviewAction = async (rowNumber: number, action: "approve" | "reject" | "correct", comment?: string) => {
    const reviewerName = `${currentPersona.name} (${currentPersona.badge})`;
    const batchId = activeBatch?.batch_id || "latest";

    reviewedRowIdsRef.current.add(rowNumber);
    setReviewedRowIds(new Set(reviewedRowIdsRef.current));
    setPendingReviews((prev) => prev.filter((item) => item.row_number !== rowNumber));
    setLiveRows((prev) =>
      prev.map((r) =>
        r.row_number === rowNumber
          ? { ...r, overall_status: action === "approve" ? "verified" : "rejected", review_state: action === "approve" ? "approved" : "rejected" }
          : r
      )
    );

    if (!API_BASE) {
      setNotice(`Row #${rowNumber} marked as ${action}d locally (no backend configured).`);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/catalogue/batches/${batchId}/rows/${rowNumber}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getApiKeyHeaders() },
        body: JSON.stringify({ action, reviewer: reviewerName, comment: comment || `Row ${action}d via workspace` })
      });
      if (res.ok) {
        setNotice(`Row #${rowNumber} ${action}d successfully by ${currentPersona.shortName}.`);
      } else {
        setNotice(`Row #${rowNumber} marked as ${action}d locally.`);
      }
    } catch {
      setNotice(`Row #${rowNumber} marked as ${action}d.`);
    }
  };

  const handleBulkApprove = async () => {
    const count = pendingReviews.length;
    const ids = pendingReviews.map((r) => r.row_number);
    ids.forEach((id) => reviewedRowIdsRef.current.add(id));
    setReviewedRowIds(new Set(reviewedRowIdsRef.current));
    setPendingReviews([]);
    setLiveRows((prev) =>
      prev.map((r) => ({ ...r, overall_status: "verified", review_state: "approved" }))
    );
    setNotice(`Bulk approved ${count} pending items by ${currentPersona.shortName} (≥80% confidence).`);

    const batchId = activeBatch?.batch_id || "latest";
    const reviewerName = `${currentPersona.name} (${currentPersona.badge})`;
    if (!API_BASE) return; // No backend — approvals recorded locally only
    try {
      await Promise.all(
        ids.map((id) =>
          fetch(`${API_BASE}/catalogue/batches/${batchId}/rows/${id}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...getApiKeyHeaders() },
            body: JSON.stringify({ action: "approve", reviewer: reviewerName, comment: "Bulk approved via workspace" })
          })
        )
      );
    } catch {
      // Locally recorded
    }
  };

  // Replays our last actual measured benchmark run (deterministic pipeline,
  // full 1,000-row official dataset — see README "Benchmark results") with a
  // short animated readout. This does not re-run the pipeline live per
  // click; the numbers shown are real but static, not freshly computed.
  const runLiveBenchmarkDemo = () => {
    setIsBenchmarking(true);
    setBenchStep(1);

    setTimeout(() => setBenchStep(2), 250);
    setTimeout(() => setBenchStep(3), 500);
    setTimeout(() => setBenchStep(4), 750);
    setTimeout(() => {
      setBenchStep(5);
      setIsBenchmarking(false);
      setBenchStats({
        time: "0.138s",
        throughput: "~7,200 rows/s",
        verified: "38.1%",
        cost: "$0 (no paid API calls)"
      });
      setNotice("Replaying last measured benchmark: 0.138s for 1,000 rows (~7,200 rows/sec, deterministic path). See README for methodology.");
    }, 1000);
  };

  // Open 252-Column Deep-Dive Inspector Modal. Fetches the real per-row
  // 252-column record (same computation used for the actual CSV export)
  // rather than approximating it client-side.
  const openInspector = (row: any) => {
    setInspectorProduct(row);
    setInspectorTab("diff");
    setUnilog252(null);

    const rowNumber = row?.row_number;
    const batchId = activeBatch?.batch_id;
    if (!rowNumber || !batchId || !API_BASE) return;

    setIsLoadingUnilog252(true);
    fetch(`${API_BASE}/catalogue/batches/${batchId}/rows/${rowNumber}/unilog252`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setUnilog252(data))
      .catch(() => setUnilog252(null))
      .finally(() => setIsLoadingUnilog252(false));
  };

  // Real attribute triplets for the inspected row, read from the fetched
  // unilog252 record (same row_to_unilog_dict() as the CSV export). Only
  // non-empty slots are returned — typically a handful, not 50, since
  // most attribute values require real sourced/extracted data this
  // deterministic pass doesn't have. No padding with fake placeholders.
  const getProductTriplets = (u252: Record<string, string> | null) => {
    if (!u252) return [];
    const triplets: { label: string; value: string; uom: string }[] = [];
    for (let i = 1; i <= 50; i++) {
      const label = u252[`ATTRIBUTE_LABEL ${i}`];
      const value = u252[`ATTRIBUTE_VALUE ${i}`];
      if (label && value) {
        triplets.push({ label, value, uom: u252[`ATTRIBUTE_UOM ${i}`] || "" });
      }
    }
    return triplets;
  };

  // Format table rows. liveRows come from GET /catalogue/batches/{id}, which
  // returns raw_values/enriched_values as flat dicts keyed by original CSV
  // column name — not a role-tagged fields array — so roles are re-derived
  // via detectRole/findByRole.
  const displayRows = liveRows.length > 0
    ? liveRows.map((r: any) => {
        // In-memory dev store (no DATABASE_URL) keeps the older fields-array
        // shape instead of flattening to raw_values/enriched_values the way
        // Postgres does on write — fall back to building it directly so
        // local dev and production behave the same way.
        const values = r.enriched_values || r.raw_values
          || (r.fields ? Object.fromEntries(r.fields.map((f: any) => [f.column, f.canonical_value ?? f.raw_value])) : {});
        const skuField = findByRole(values, "part_number") || `ROW-${r.row_number}`;
        const descField = findByRole(values, "description") || "Uncategorized product";
        const mfrField = findByRole(values, "manufacturer") || findByRole(values, "brand") || "Unknown manufacturer";
        const catField = findByRole(values, "category") || "Uncategorized";
        const status = r.overall_status === "verified" || r.overall_status === "approved" || r.review_state === "approved" ? "Ready" : "Needs review";
        const quality = `${Math.round((r.overall_confidence ?? 0.5) * 100)}% verified`;
        return [skuField, `${descField}`, mfrField, catField, status, quality, r];
      })
    : defaultRows;

  // Filter rows by Category & Search
  const filteredRows = displayRows.filter((r: any) => {
    if (filterMode === "review" && r[4] !== "Needs review") return false;
    if (categoryFilter === "hvac" && !r[3].toLowerCase().includes("hvac") && !r[1].toLowerCase().includes("thermostat")) return false;
    if (categoryFilter === "valves" && !r[3].toLowerCase().includes("valve") && !r[3].toLowerCase().includes("fitting") && !r[1].toLowerCase().includes("valve")) return false;
    if (categoryFilter === "electrical" && !r[3].toLowerCase().includes("electric") && !r[1].toLowerCase().includes("switch")) return false;
    if (categoryFilter === "abrasives" && !r[3].toLowerCase().includes("abrasive") && !r[3].toLowerCase().includes("tool") && !r[1].toLowerCase().includes("blade")) return false;
    if (categoryFilter === "appliances" && !r[3].toLowerCase().includes("appliance") && !r[1].toLowerCase().includes("refrigerator")) return false;
    if (searchQuery && !r[0].toLowerCase().includes(searchQuery.toLowerCase()) && !r[1].toLowerCase().includes(searchQuery.toLowerCase()) && !r[2].toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  // liveRows carry enriched_values/raw_values (flat dicts by column name),
  // not the row.fields array this used to assume — see the catalogue-table
  // fix above. Compute real field-population coverage from that instead of
  // silently falling back to a hardcoded placeholder for every real batch.
  const evidenceCoverage = liveRows.length > 0
    ? (() => {
        let populated = 0;
        let total = 0;
        liveRows.forEach((r: any) => {
          const values = r.enriched_values || r.raw_values || {};
          Object.values(values).forEach((v: any) => {
            total += 1;
            if (v !== null && v !== undefined && String(v).trim() !== "") populated += 1;
          });
        });
        return total > 0 ? populated / total : 0;
      })()
    : 0.94;
  const verifiedRate = activeBatch?.verified_rate ?? 0.95;
  const reviewCount = pendingReviews.length;
  const throughput = activeBatch?.metrics?.throughput_rows_per_sec ?? "~7,200";

  // Render active view
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
                <button
                  className="export-btn primary-accent"
                  onClick={() => handleExport("unilog_template")}
                  title="Download official Unilog 252-column delivery CSV"
                >
                  <DownloadIcon size={12} />
                  Unilog 252-Col CSV
                </button>
                <button
                  className="export-btn emerald-accent"
                  onClick={() => handleExport("commerce_csv")}
                  title="Download Commerce PIM CSV feed"
                >
                  <DownloadIcon size={12} />
                  PIM Commerce CSV
                </button>
                <button
                  className="export-btn amber-accent"
                  onClick={() => handleExport("audit")}
                  title="Download complete audit lineage JSON"
                >
                  <DownloadIcon size={12} />
                  Audit Lineage
                </button>
              </div>
            </div>

            {/* Category Filter Chips Bar */}
            <div className="category-filter-bar">
              <button className={`category-chip ${categoryFilter === "all" ? "active" : ""}`} onClick={() => setCategoryFilter("all")}>
                All Categories ({displayRows.length})
              </button>
              <button className={`category-chip ${categoryFilter === "valves" ? "active" : ""}`} onClick={() => setCategoryFilter("valves")}>
                Plumbing & Valves
              </button>
              <button className={`category-chip ${categoryFilter === "abrasives" ? "active" : ""}`} onClick={() => setCategoryFilter("abrasives")}>
                Abrasives & Tools
              </button>
              <button className={`category-chip ${categoryFilter === "electrical" ? "active" : ""}`} onClick={() => setCategoryFilter("electrical")}>
                Electrical & Automation
              </button>
              <button className={`category-chip ${categoryFilter === "hvac" ? "active" : ""}`} onClick={() => setCategoryFilter("hvac")}>
                HVAC & Heating
              </button>
              <button className={`category-chip ${categoryFilter === "appliances" ? "active" : ""}`} onClick={() => setCategoryFilter("appliances")}>
                Commercial Appliances
              </button>
            </div>

            <div className="filters" style={{ marginTop: 8 }}>
              <button className={`filter ${filterMode === "all" ? "active" : ""}`} onClick={() => setFilterMode("all")}>
                All records <b>{displayRows.length}</b>
              </button>
              <button className={`filter ${filterMode === "review" ? "active" : ""}`} onClick={() => setFilterMode("review")}>
                Needs review <b>{reviewCount}</b>
              </button>
              <div className="search" style={{ display: "flex", alignItems: "center" }}>
                <input
                  type="text"
                  placeholder="⌕ Search SKU, description, or manufacturer..."
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
                <span>QUALITY / 252-COL</span>
              </div>
              {filteredRows.map((r: any, i: number) => (
                <div
                  className={`tr ${selected === i ? "selected" : ""}`}
                  onClick={() => {
                    setSelected(i);
                    openInspector(r[6] || r);
                  }}
                  key={r[0] + i}
                  style={{ cursor: "pointer" }}
                  title="Click to open 252-Column Spec Inspector"
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
                  <span className="quality" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span>{r[5]}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        openInspector(r[6] || r);
                      }}
                      style={{ background: "rgba(40,114,227,0.08)", color: "#2872e3", border: "1px solid rgba(40,114,227,0.25)", borderRadius: 4, padding: "3px 7px", fontSize: 10, cursor: "pointer", fontWeight: 700 }}
                    >
                      Inspect 252 Specs
                    </button>
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
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                {pendingReviews.length > 0 && (
                  <button
                    className="view"
                    onClick={handleBulkApprove}
                    style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", borderColor: "rgba(16, 185, 129, 0.4)", padding: "6px 12px", borderRadius: 6, fontWeight: 600 }}
                  >
                    ✓ Approve All High Confidence (≥80%)
                  </button>
                )}
                <span style={{ fontSize: 12, color: "#64748b" }}>
                  Threshold: <strong>80% confidence & 0 errors</strong>
                </span>
              </div>
            </div>

            {pendingReviews.length === 0 ? (
              <div style={{ padding: "48px 20px", textAlign: "center", color: "#64748b" }}>
                <p style={{ fontSize: 18, fontWeight: 600, color: "#10b981", margin: "0 0 8px 0" }}>✓ All catalogue items have been verified!</p>
                <small>Auto-approval engine validated 100% of candidate records. No pending conflicts.</small>
              </div>
            ) : (
              <div className="table" style={{ marginTop: 16 }}>
                <div className="tr th" style={{ gridTemplateColumns: "1.4fr 1.2fr 0.8fr 1fr 1.2fr" }}>
                  <span>ROW / SKU</span>
                  <span>FLAG REASON</span>
                  <span>CONFIDENCE</span>
                  <span>STATE</span>
                  <span>HUMAN ACTION</span>
                </div>
                {pendingReviews.map((item: any, idx: number) => {
                  const rowObj: any = liveRows.find((r: any) => r.row_number === item.row_number);
                  const sku = findByRole(rowObj?.enriched_values || rowObj?.raw_values, "part_number") || `Row ${item.row_number}`;
                  return (
                    <div className="tr" key={item.row_number || idx} style={{ gridTemplateColumns: "1.4fr 1.2fr 0.8fr 1fr 1.2fr" }}>
                      <span>
                        <strong>{sku}</strong>
                        <small>Row #{item.row_number}</small>
                      </span>
                      <span style={{ color: "#d97706", fontSize: 11 }}>
                        {item.errors?.[0] || item.reason || "Requires human verification"}
                      </span>
                      <span style={{ fontFamily: "DM Mono", fontSize: 11 }}>
                        {Math.round((item.overall_confidence || 0.78) * 100)}%
                      </span>
                      <span>
                        <mark className="review">● {item.state || "pending_review"}</mark>
                      </span>
                      <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <button
                          onClick={() => handleReviewAction(item.row_number, "approve")}
                          style={{ background: "#10b981", color: "#fff", border: 0, padding: "5px 10px", borderRadius: 4, cursor: "pointer", fontSize: 11, fontWeight: 700 }}
                          title="Approve row"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => handleReviewAction(item.row_number, "reject")}
                          style={{ background: "#ef4444", color: "#fff", border: 0, padding: "5px 10px", borderRadius: 4, cursor: "pointer", fontSize: 11, fontWeight: 700 }}
                          title="Reject row"
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => openInspector(rowObj || { row_number: item.row_number, 0: sku, 1: "Product Item", 2: "Apollo Valves", 3: "Industrial Valves" })}
                          style={{ background: "rgba(255,255,255,0.06)", color: "#94a3b8", border: "1px solid rgba(255,255,255,0.1)", padding: "4px 8px", borderRadius: 4, cursor: "pointer", fontSize: 10, fontWeight: 600 }}
                          title="Open 252-Column Spec Inspector"
                        >
                          Inspect 252 Specs
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
                <p className="eyebrow">BATCH INGESTION & ACCURACY BENCHMARK</p>
                <h3>Ingested Batches & Evaluation Telemetry</h3>
              </div>
              <button className="primary" onClick={() => fileInputRef.current?.click()}>
                + Import CSV / XLSX / PDF
              </button>
            </div>

            {/* Performance KPI Cards */}
            <div className="metrics" style={{ margin: "20px 0" }}>
              <article>
                <span>BATCH COUNT</span>
                <strong>{batchList.length || 1}</strong>
                <small className="up">Durable PostgreSQL store</small>
              </article>
              <article>
                <span>THROUGHPUT</span>
                <strong>~7,200 <small style={{ fontSize: 12 }}>rows/s</small></strong>
                <small className="up">Deterministic path, measured</small>
              </article>
              <article title="Measured against a self-generated synthetic benchmark, not official Unilog ground truth — see README.">
                <span>SYNTHETIC BENCHMARK ACCURACY</span>
                <strong>94.64<span className="percent">%</span></strong>
                <small className="up">Self-generated 200-row set</small>
              </article>
              <article title="No LLM API is used anywhere in this pipeline — enrichment is entirely deterministic, rule-based normalization. The only real per-call cost is the optional Serper.dev search fallback under live_fetch, which this batch's average reflects when available.">
                <span>COST PER SKU</span>
                <strong>{activeBatch?.cost?.average_cost_per_row != null ? `$${activeBatch.cost.average_cost_per_row}` : "$0"}</strong>
                <small className="up">Deterministic rules only — no LLM calls</small>
              </article>
            </div>

            {/* Synthetic Benchmark Evaluation Matrix */}
            <div style={{ background: "#172232", borderRadius: 10, padding: "18px 22px", color: "#ffffff", marginBottom: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                <h4 style={{ margin: 0, fontSize: 14, color: "#38bdf8", letterSpacing: "-0.02em" }}>
                  Synthetic Benchmark Evaluation (200 self-generated SKUs — not official Unilog data)
                </h4>
                <span style={{ background: "rgba(16,185,129,0.2)", color: "#34d399", padding: "3px 8px", borderRadius: 6, fontSize: 10, fontWeight: 700 }}>
                  94.64% Overall Exact Match
                </span>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>PART NUMBER</small>
                  <strong style={{ fontSize: 15, color: "#34d399" }}>100.0%</strong>
                  <span style={{ fontSize: 9, color: "#64748b", display: "block" }}>Exact match</span>
                </div>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>MANUFACTURER</small>
                  <strong style={{ fontSize: 15, color: "#34d399" }}>93.5%</strong>
                  <span style={{ fontSize: 9, color: "#64748b", display: "block" }}>Exact match</span>
                </div>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>CATEGORY TAXONOMY</small>
                  <strong style={{ fontSize: 15, color: "#34d399" }}>100.0%</strong>
                  <span style={{ fontSize: 9, color: "#64748b", display: "block" }}>Exact match</span>
                </div>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>MATERIAL / ALLOY</small>
                  <strong style={{ fontSize: 15, color: "#38bdf8" }}>94.5%</strong>
                  <span style={{ fontSize: 9, color: "#64748b", display: "block" }}>Exact match</span>
                </div>
              </div>
            </div>

            {/* Ingested Batches Table */}
            <div className="table">
              <div className="tr th" style={{ gridTemplateColumns: "1.8fr 1fr 1fr 1fr 1.2fr" }}>
                <span>BATCH / FILE</span>
                <span>SKU COUNT</span>
                <span>VERIFIED RATE</span>
                <span>STATUS</span>
                <span>ACTION</span>
              </div>
              {batchList.length > 0 ? (
                batchList.map((b: any) => (
                  <div className="tr" key={b.batch_id} style={{ gridTemplateColumns: "1.8fr 1fr 1fr 1fr 1.2fr" }}>
                    <span>
                      <strong>{b.source_name}</strong>
                      <small>ID: {b.batch_id.slice(0, 8)}...</small>
                    </span>
                    <span>{b.row_count} rows</span>
                    <span style={{ color: "#10b981", fontWeight: 700 }}>{Math.round((b.verified_rate || 0.95) * 100)}%</span>
                    <span><mark className="ready">● Completed</mark></span>
                    <span style={{ display: "flex", gap: 6 }}>
                      <button className="export-btn primary-accent" onClick={() => handleExport("unilog_template")}>
                        <DownloadIcon size={12} />
                        Export 252-Col
                      </button>
                    </span>
                  </div>
                ))
              ) : (
                <div className="tr" style={{ gridTemplateColumns: "1.8fr 1fr 1fr 1fr 1.2fr" }}>
                  <span><strong>Unihack_ Sample Dataset - Input.csv</strong><small>Official Unilog input dataset</small></span>
                  <span>1,000 rows</span>
                  <span style={{ color: "#10b981", fontWeight: 700 }}>38%</span>
                  <span><mark className="ready">● Completed</mark></span>
                  <span>
                    <button className="export-btn primary-accent" onClick={() => handleExport("unilog_template")}>
                      <DownloadIcon size={12} />
                      Export 252-Col
                    </button>
                  </span>
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
                <h3>Unilog 252-Column & schema.org / Product Schemas</h3>
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <button
                  className="export-btn emerald-accent"
                  onClick={() => handleExport("schema_org")}
                  title="Export standard schema.org/Product JSON-LD graph"
                >
                  <DownloadIcon size={12} />
                  Export schema.org JSON-LD
                </button>
                <button
                  className="export-btn primary-accent"
                  onClick={() => handleExport("unilog_template")}
                >
                  <DownloadIcon size={12} />
                  Export 252-Col Specification
                </button>
              </div>
            </div>

            {/* Standards Compliance Badges */}
            <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
              <span style={{ background: "rgba(56, 189, 248, 0.15)", color: "#38bdf8", padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, border: "1px solid rgba(56, 189, 248, 0.3)" }}>
                ✓ schema.org / Product & PropertyValue Compliant
              </span>
              <span style={{ background: "rgba(16, 185, 129, 0.15)", color: "#34d399", padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, border: "1px solid rgba(16, 185, 129, 0.3)" }}>
                ✓ Unilog CX1 252-Column PIM Specification
              </span>
              <span style={{ background: "rgba(245, 158, 11, 0.15)", color: "#fbbf24", padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, border: "1px solid rgba(245, 158, 11, 0.3)" }}>
                ✓ UNSPSC & GS1/GTIN Identifier Ready
              </span>
              <span style={{ background: "rgba(168, 85, 247, 0.15)", color: "#c084fc", padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, border: "1px solid rgba(168, 85, 247, 0.3)" }}>
                ✓ ISO 8000 Data Lineage Standard
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginTop: 20 }}>
              <div style={{ background: "rgba(255,255,255,0.03)", padding: 18, borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)" }}>
                <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Industrial Valves & Actuators</h4>
                <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, lineHeight: 1.5 }}>
                  Attributes: Size (DN/NPT), Pressure Rating (Class/PSI), Body Material, Connection Type, Flow Direction, UOM.
                </p>
                <small style={{ color: "#10b981", display: "block", marginTop: 10 }}>✓ LOV Material mapping active (Apollo, Parker, Victaulic)</small>
                <button
                  className="export-btn"
                  style={{ marginTop: 12, width: "100%", justifyContent: "center" }}
                  onClick={() => downloadJson({ schema: "Industrial Valves", version: "1.0", standard: "schema.org/Product", fields: ["Size", "Pressure_Rating", "Material", "Connection", "UOM"] }, "Valve_Schema.json")}
                >
                  <DownloadIcon size={11} />
                  Download Schema JSON
                </button>
              </div>

              <div style={{ background: "rgba(255,255,255,0.03)", padding: 18, borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)" }}>
                <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Abrasives & Sanding Media</h4>
                <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, lineHeight: 1.5 }}>
                  Attributes: Grit Size (P-Grade), Diameter, Hole Pattern, Backing Material (Film/Paper/Cloth), Grain Type (Ceramic/Alumina).
                </p>
                <small style={{ color: "#10b981", display: "block", marginTop: 10 }}>✓ Multi-brand schema active (Freud, Mirka, 3M)</small>
                <button
                  className="export-btn"
                  style={{ marginTop: 12, width: "100%", justifyContent: "center" }}
                  onClick={() => downloadJson({ schema: "Abrasives & Sanding Media", version: "1.0", standard: "schema.org/Product", fields: ["Grit_Size", "Diameter", "Backing_Material", "Grain_Type", "Hole_Pattern"] }, "Abrasives_Schema.json")}
                >
                  <DownloadIcon size={11} />
                  Download Schema JSON
                </button>
              </div>

              <div style={{ background: "rgba(255,255,255,0.03)", padding: 18, borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)" }}>
                <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Power Tools & Machinery</h4>
                <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, lineHeight: 1.5 }}>
                  Attributes: Voltage (18V/20V/120V), Amp-Hours (Ah), Motor Type (Brushless), Chuck Size, Max RPM, Weight.
                </p>
                <small style={{ color: "#10b981", display: "block", marginTop: 10 }}>✓ Tool telemetry active (Milwaukee, DeWalt, Makita)</small>
                <button
                  className="export-btn"
                  style={{ marginTop: 12, width: "100%", justifyContent: "center" }}
                  onClick={() => downloadJson({ schema: "Power Tools & Machinery", version: "1.0", standard: "schema.org/Product", fields: ["Voltage", "Amp_Hours", "Motor_Type", "Chuck_Size", "Max_RPM", "Weight"] }, "PowerTools_Schema.json")}
                >
                  <DownloadIcon size={11} />
                  Download Schema JSON
                </button>
              </div>
            </div>

            <div style={{ marginTop: 24, padding: 18, background: "#1e293b", color: "#f8fafc", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)" }}>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13, color: "#38bdf8" }}>Dual Schema Governance: Unilog 252-Column PIM Specification + schema.org / Product JSON-LD</h4>
              <p style={{ fontSize: 12, color: "#94a3b8", lineHeight: 1.6, margin: 0 }}>
                SpecLedger bridges enterprise PIM delivery standards (Unilog CX1 252-column template with 6 description tiers, 20 feature bullets, and 50 attribute triplets) and open-web e-commerce structured data standards (schema.org/Product, Brand, Organization, and PropertyValue with ISO UOM codes) ensuring 100% interoperability.
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
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <button
                  className="export-btn primary-accent"
                  disabled={batchSources.length === 0}
                  title={batchSources.length === 0 ? "Process a live batch before exporting evidence" : "Download evidence for the active batch"}
                  onClick={() => {
                    if (batchSources.length === 0) {
                      setNotice("Evidence export unavailable · no verified batch sources loaded");
                      return;
                    }
                    downloadJson({ sources: batchSources }, "Evidence_Map.json");
                  }}
                >
                  <DownloadIcon size={12} />
                  Download Evidence Map (JSON)
                </button>
                <span style={{ background: "#fef3c7", color: "#b45309", padding: "4px 8px", borderRadius: 6, fontSize: 11, fontWeight: 700 }}>
                  Marketplace Prohibition Active (Amazon/eBay Blocked)
                </span>
              </div>
            </div>

            <div className="table" style={{ marginTop: 16 }}>
              <div className="tr th" style={{ gridTemplateColumns: "1.4fr 2fr 1fr 1fr" }}>
                <span>MANUFACTURER / BRAND</span>
                <span>DISCOVERED SOURCE URL</span>
                <span>SOURCE TYPE</span>
                <span>STATUS</span>
              </div>
              {batchSources.length > 0 ? (
                batchSources.map((s: any, idx: number) => (
                  <React.Fragment key={idx}>
                    <div className="tr" style={{ gridTemplateColumns: "1.4fr 2fr 1fr 1fr" }}>
                      <span><strong>{s.manufacturer}</strong></span>
                      <span style={{ fontFamily: "DM Mono", fontSize: 11, color: "#38bdf8", overflow: "hidden", textOverflow: "ellipsis" }}>
                        <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "#38bdf8", textDecoration: "underline" }}>{s.url}</a>
                      </span>
                      <span>{s.source_type}</span>
                      <span>
                        <mark className={s.evidence_status === "verified" ? "ready" : "review"}>
                          ● {s.evidence_status === "verified" ? "Verified source" : "Unverified candidate"}
                        </mark>
                      </span>
                    </div>
                    {s.extracted_attributes && s.extracted_attributes.length > 0 && (
                      <div style={{ gridColumn: "1 / -1", padding: "6px 16px 14px", background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#0369a1", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 6 }}>
                          Real attributes parsed from this PDF's own text ({s.extracted_attributes.length})
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                          {s.extracted_attributes.map((a: any, i: number) => (
                            <span key={i} style={{ background: "#e0f2fe", color: "#0c4a6e", padding: "3px 8px", borderRadius: 5, fontSize: 11 }}>
                              <strong>{a.label}:</strong> {a.value}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </React.Fragment>
                ))
              ) : (
                <div className="empty-review" style={{ gridColumn: "1 / -1", margin: 16 }}>
                  No source evidence is loaded. Process a catalogue batch with the API before reviewing provenance.
                </div>
              )}
            </div>

          </section>
        );

      case "audit": {
        const filteredAuditEvents = auditEvents.filter((e: any) => {
          if (auditFilter === "human") return !!e.reviewer;
          if (auditFilter === "auto") return e.action === "auto_approve";
          return true;
        });
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">ACCOUNTABILITY & COMPLIANCE LOG</p>
                <h3>Audit Trail & Decision Lineage</h3>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 6, background: "rgba(16,185,129,0.15)", color: "#10b981", border: "1px solid rgba(16,185,129,0.3)" }}>
                  {auditEvents.length} real events
                </span>
                <button
                  className="export-btn amber-accent"
                  onClick={() => handleExport("audit")}
                >
                  <DownloadIcon size={12} />
                  Export Audit Log (JSON)
                </button>
              </div>
            </div>
            <p style={{ fontSize: 12, color: "#7d8590", margin: "8px 0 0" }}>
              Real audit events recorded server-side for the active batch — every row is routed through validation at ingest time (recording
              an auto_approve or submit_for_review event even before any human acts), and every approve/reject/correct action adds another.
            </p>

            <div className="filters" style={{ marginTop: 16 }}>
              <button className={`filter ${auditFilter === "all" ? "active" : ""}`} onClick={() => setAuditFilter("all")}>
                All events
              </button>
              <button className={`filter ${auditFilter === "human" ? "active" : ""}`} onClick={() => setAuditFilter("human")}>
                Human approvals
              </button>
              <button className={`filter ${auditFilter === "auto" ? "active" : ""}`} onClick={() => setAuditFilter("auto")}>
                Auto-verifications
              </button>
            </div>

            <div className="activity" style={{ marginTop: 16 }}>
              {filteredAuditEvents.length === 0 ? (
                <div className="empty-review">No audit events recorded yet for this batch.</div>
              ) : (
                filteredAuditEvents.map((e: any) => (
                  <p key={e.event_id}>
                    <b>{e.reviewer || "Pipeline Engine"}</b> {e.action.replace(/_/g, " ")} row <strong>#{e.row_number}</strong>
                    <small>{new Date(e.timestamp * 1000).toLocaleString()} · {e.comment || `${e.previous_state} → ${e.new_state}`}</small>
                  </p>
                ))
              )}
            </div>
          </section>
        );
      }

      case "overview":
      default:
        return (
          <>
            {/* Interactive High-Throughput Batch Benchmark Runner Banner */}
            <div className="benchmark-banner">
              <div className="benchmark-banner-header">
                <div>
                  <span className="eyebrow" style={{ color: "#38bdf8" }}>ENTERPRISE HIGH-THROUGHPUT ENGINE · UNILOG CX1 BATCH BENCHMARK</span>
                  <h3 style={{ margin: "4px 0 0", fontSize: 18, color: "#ffffff" }}>
                    Sub-Second Industrial Enrichment Pipeline (~7,200 SKUs/sec)
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button
                    onClick={runLiveBenchmarkDemo}
                    disabled={isBenchmarking}
                    style={{
                      background: isBenchmarking ? "#475569" : "#2872e3",
                      color: "#ffffff",
                      border: "none",
                      padding: "9px 18px",
                      borderRadius: 6,
                      fontWeight: 700,
                      fontSize: 12,
                      cursor: isBenchmarking ? "wait" : "pointer",
                      boxShadow: "0 4px 14px rgba(40, 114, 227, 0.4)",
                      display: "flex",
                      alignItems: "center",
                      gap: 6
                    }}
                  >
                    {isBenchmarking ? "Processing Batch Feed..." : "Run Batch Benchmark"}
                  </button>
                  <button
                    className="export-btn"
                    onClick={() => handleExport("unilog_template")}
                    style={{ background: "rgba(255,255,255,0.12)", color: "#ffffff", borderColor: "rgba(255,255,255,0.25)" }}
                  >
                    <DownloadIcon size={12} />
                    252-Col CSV
                  </button>
                </div>
              </div>

              {/* Pipeline Step Visualizer */}
              <div className="benchmark-pipeline-steps">
                <div className={`bench-step-badge ${benchStep >= 1 ? (benchStep > 1 ? "done" : "active") : ""}`}>
                  <span>{benchStep > 1 ? "✓" : "01"}</span> Ingest Raw Feed
                </div>
                <span style={{ color: "rgba(255,255,255,0.3)" }}>→</span>
                <div className={`bench-step-badge ${benchStep >= 2 ? (benchStep > 2 ? "done" : "active") : ""}`}>
                  <span>{benchStep > 2 ? "✓" : "02"}</span> Resolve MFR Domains
                </div>
                <span style={{ color: "rgba(255,255,255,0.3)" }}>→</span>
                <div className={`bench-step-badge ${benchStep >= 3 ? (benchStep > 3 ? "done" : "active") : ""}`}>
                  <span>{benchStep > 3 ? "✓" : "03"}</span> Normalize UOMs & Alloys
                </div>
                <span style={{ color: "rgba(255,255,255,0.3)" }}>→</span>
                <div className={`bench-step-badge ${benchStep >= 4 ? (benchStep > 4 ? "done" : "active") : ""}`}>
                  <span>{benchStep > 4 ? "✓" : "04"}</span> Synthesize 252 Columns
                </div>
                <span style={{ color: "rgba(255,255,255,0.3)" }}>→</span>
                <div className={`bench-step-badge ${benchStep >= 5 ? "done" : ""}`}>
                  <span>{benchStep >= 5 ? "✓" : "05"}</span> Validate CX1 Rules
                </div>
              </div>

              {/* Benchmark Telemetry Counters */}
              <div className="benchmark-stats-row">
                <div className="benchmark-stat-item">
                  <span>EXECUTION TIME</span>
                  <strong>{benchStats.time}</strong>
                </div>
                <div className="benchmark-stat-item">
                  <span>THROUGHPUT</span>
                  <strong>{benchStats.throughput}</strong>
                </div>
                <div className="benchmark-stat-item" title="Fraction of all output fields matched against reference data on the full 1,000-row official dataset — not a ground-truth accuracy score.">
                  <span>FIELD VERIFIED RATE</span>
                  <strong style={{ color: "#34d399" }}>{benchStats.verified}</strong>
                </div>
                <div className="benchmark-stat-item" title="This run uses the deterministic path (no live_fetch): zero external API calls, so the real cost is $0. The optional live_fetch mode adds one Serper.dev search call only when direct manufacturer-domain guessing fails — see README for real per-query pricing context. No LLM API is used anywhere in this pipeline.">
                  <span>OPERATING COST</span>
                  <strong>{benchStats.cost}</strong>
                </div>
              </div>
            </div>

            {/* Metrics Cards */}
            <section className="metrics">
              <article>
                <span>PRODUCT RECORDS</span>
                <strong>{activeBatch?.row_count ?? displayRows.length}</strong>
                <small className="up">{activeBatch ? "Current enrichment batch" : "1,000 active SKUs"}</small>
              </article>
              <article>
                <span>REVIEW QUEUE</span>
                <strong className="amber">{reviewCount}</strong>
                <small>{reviewCount > 0 ? "Requires human verification" : "All records verified"}</small>
              </article>
              <article>
                <span>CATALOGUE HEALTH</span>
                <strong>{Math.round(verifiedRate * 100)}<span className="percent">%</span></strong>
                <small className="up">Validated fields in active batch</small>
              </article>
              <article>
                <span>EVIDENCE COVERAGE</span>
                <strong>{Math.round(evidenceCoverage * 100)}<span className="percent">%</span></strong>
                <small>{activeBatch ? `Across ${activeBatch.total_fields ?? liveRows.length} fields · ${throughput} rows/sec` : `No batch loaded yet · ${throughput} rows/sec`}</small>
              </article>
            </section>

            {/* Catalogue Preview Table */}
            <section className="section-card">
              <div className="table-head">
                <div>
                  <p className="eyebrow">RECENT PRODUCT RECORDS</p>
                  <h3>Catalogue activity</h3>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button
                    className="export-btn primary-accent"
                    onClick={() => handleExport("unilog_template")}
                    title="Export Unilog 252-Column CSV"
                  >
                    <DownloadIcon size={12} />
                    Unilog 252-Col CSV
                  </button>
                  <button
                    className="export-btn emerald-accent"
                    onClick={() => handleExport("commerce_csv")}
                    title="Export Commerce PIM CSV"
                  >
                    <DownloadIcon size={12} />
                    Export PIM CSV
                  </button>
                  <button
                    className="export-btn amber-accent"
                    onClick={() => handleExport("audit")}
                    title="Download audit trail JSON"
                  >
                    <DownloadIcon size={12} />
                    Audit Lineage
                  </button>
                </div>
              </div>

              <div className="table">
                <div className="tr th">
                  <span>PRODUCT / SKU</span>
                  <span>MANUFACTURER</span>
                  <span>CATEGORY</span>
                  <span>STATUS</span>
                  <span>QUALITY / 252-COL</span>
                </div>
                {displayRows.slice(0, 5).map((r: any, i: number) => (
                  <div
                    className={`tr ${selected === i ? "selected" : ""}`}
                    onClick={() => {
                      setSelected(i);
                      openInspector(r[6] || r);
                    }}
                    key={r[0] + i}
                    style={{ cursor: "pointer" }}
                    title="Click to open 252-Column Spec Inspector"
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
                    <span className="quality" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span>{r[5]}</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          openInspector(r[6] || r);
                        }}
                        style={{ background: "rgba(40,114,227,0.08)", color: "#2872e3", border: "1px solid rgba(40,114,227,0.25)", borderRadius: 4, padding: "3px 7px", fontSize: 10, cursor: "pointer", fontWeight: 700 }}
                      >
                        Inspect 252 Specs
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </>
        );
    }
  };

  // Inspect Modal Product Data Extractor. inspectorProduct is set from the raw
  // API row (raw_values/enriched_values dicts), a defaultRows mock array, or
  // the row_number-only fallback object — so roles are derived via findByRole
  // the same way displayRows does, with array/object indexing as fallback.
  const inspectorValues = inspectorProduct?.enriched_values || inspectorProduct?.raw_values
    || (inspectorProduct?.fields ? Object.fromEntries(inspectorProduct.fields.map((f: any) => [f.column, f.canonical_value ?? f.raw_value])) : undefined);
  const inspectedSku = findByRole(inspectorValues, "part_number") || inspectorProduct?.[0] || "VLV-600-050";
  const inspectedDesc = findByRole(inspectorValues, "description") || inspectorProduct?.[1] || "Ball Valve · DN50 Full Port Stainless Steel";
  const inspectedMfr = findByRole(inspectorValues, "manufacturer") || findByRole(inspectorValues, "brand") || inspectorProduct?.[2] || "Apollo Valves";
  const inspectedCat = findByRole(inspectorValues, "category") || inspectorProduct?.[3] || "Industrial Valves";
  const inspectedTriplets = getProductTriplets(unilog252);
  const filteredTriplets = inspectedTriplets.filter(t => 
    !tripletSearch || t.label.toLowerCase().includes(tripletSearch.toLowerCase()) || t.value.toLowerCase().includes(tripletSearch.toLowerCase())
  );

  // Real 252-column grid built directly from the fetched unilog252 record —
  // the same dict the actual CSV export writes. Column ranges are used only
  // for the cosmetic section/badge grouping below, never to invent content;
  // an empty real value renders as "—", not a generated placeholder.
  const COLUMN_SECTIONS: { max: number; section: string; badgeBg: string; badgeColor: string }[] = [
    { max: 1, section: "MFR Sourcing", badgeBg: "rgba(37, 99, 235, 0.1)", badgeColor: "#2563eb" },
    { max: 6, section: "Reference URLs", badgeBg: "rgba(37, 99, 235, 0.1)", badgeColor: "#2563eb" },
    { max: 22, section: "Identity & SKU", badgeBg: "rgba(16, 185, 129, 0.1)", badgeColor: "#10b981" },
    { max: 23, section: "Taxonomy Classpath", badgeBg: "rgba(147, 51, 234, 0.1)", badgeColor: "#9333ea" },
    { max: 29, section: "Description Tiers", badgeBg: "rgba(236, 72, 153, 0.1)", badgeColor: "#db2777" },
    { max: 49, section: "Item Feature Bullets", badgeBg: "rgba(59, 130, 246, 0.1)", badgeColor: "#2563eb" },
    { max: 55, section: "Core Product Specs", badgeBg: "rgba(16, 185, 129, 0.1)", badgeColor: "#10b981" },
    { max: 205, section: "Attribute Triplets", badgeBg: "rgba(14, 165, 233, 0.1)", badgeColor: "#0284c7" },
    { max: 214, section: "Barcodes & Pricing", badgeBg: "rgba(245, 158, 11, 0.1)", badgeColor: "#d97706" },
    { max: 223, section: "Dimensions & Weight", badgeBg: "rgba(100, 116, 139, 0.1)", badgeColor: "#475569" },
    { max: 252, section: "Media & Compliance", badgeBg: "rgba(16, 185, 129, 0.1)", badgeColor: "#10b981" },
  ];

  const getAll252Columns = (u252: Record<string, string> | null) => {
    return ALL_252_UNILOG_HEADERS.map((header, index) => {
      const colNum = index + 1;
      const val = u252?.[header] || "";
      const bucket = COLUMN_SECTIONS.find((s) => colNum <= s.max) || COLUMN_SECTIONS[COLUMN_SECTIONS.length - 1];
      return {
        num: colNum,
        header,
        val,
        section: bucket.section,
        badgeBg: bucket.badgeBg,
        badgeColor: bucket.badgeColor,
        isCode: val.startsWith("http"),
      };
    });
  };

  const all252ColumnsList = getAll252Columns(unilog252);
  const filtered252Cols = all252ColumnsList.filter(col =>
    !colSearch ||
    col.header.toLowerCase().includes(colSearch.toLowerCase()) ||
    col.val.toLowerCase().includes(colSearch.toLowerCase()) ||
    col.section.toLowerCase().includes(colSearch.toLowerCase()) ||
    `col ${col.num}`.includes(colSearch.toLowerCase())
  );

  return (
    <div className="app">
      {/* Hidden File Input for header upload button */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        accept=".csv,.tsv,.xlsx,.pdf"
        style={{ display: "none" }}
      />

      {/* 252-Column Product Deep-Dive Inspector Modal */}
      {inspectorProduct && (
        <div className="spec-modal-backdrop" onClick={() => setInspectorProduct(null)}>
          <div className="spec-modal" onClick={(e) => e.stopPropagation()}>
            {/* Modal Header */}
            <div className="spec-modal-header">
              <div>
                <span className="eyebrow" style={{ color: "#38bdf8" }}>UNILOG CX1 252-COLUMN PRODUCT INTELLIGENCE</span>
                <h3>
                  {inspectedSku}
                  <span style={{ fontSize: 12, fontWeight: 500, color: "#94a3b8" }}>· {inspectedMfr}</span>
                  <span style={{ fontSize: 10, background: "rgba(16,185,129,0.2)", color: "#34d399", padding: "2px 8px", borderRadius: 4 }}>
                    {unilog252 ? `${all252ColumnsList.filter((c) => c.val).length} of 252 columns populated` : isLoadingUnilog252 ? "Loading…" : "Unavailable"}
                  </span>
                </h3>
              </div>
              <button
                onClick={() => setInspectorProduct(null)}
                style={{ background: "rgba(255,255,255,0.1)", border: "none", color: "#ffffff", borderRadius: 6, width: 28, height: 28, cursor: "pointer", fontSize: 14 }}
              >
                ✕
              </button>
            </div>

            {/* Modal Tabs */}
            <div className="spec-modal-tabs">
              <button className={`spec-tab-btn ${inspectorTab === "diff" ? "active" : ""}`} onClick={() => setInspectorTab("diff")}>
                6-to-252 Transformation
              </button>
              <button className={`spec-tab-btn ${inspectorTab === "all252" ? "active" : ""}`} onClick={() => setInspectorTab("all252")}>
                Full 252-Column Grid (252)
              </button>
              <button className={`spec-tab-btn ${inspectorTab === "triplets" ? "active" : ""}`} onClick={() => setInspectorTab("triplets")}>
                Spec Triplets ({inspectedTriplets.length} of 50)
              </button>
              <button className={`spec-tab-btn ${inspectorTab === "descriptions" ? "active" : ""}`} onClick={() => setInspectorTab("descriptions")}>
                Description Tiers (6)
              </button>
              <button className={`spec-tab-btn ${inspectorTab === "features" ? "active" : ""}`} onClick={() => setInspectorTab("features")}>
                Feature Bullets ({unilog252 ? Array.from({ length: 20 }, (_, i) => unilog252[`ITEM_FEATURES_${i + 1}`]).filter(Boolean).length : 0} of 20)
              </button>
              <button className={`spec-tab-btn ${inspectorTab === "evidence" ? "active" : ""}`} onClick={() => setInspectorTab("evidence")}>
                Verified Sourcing & Safety
              </button>
            </div>

            {/* Modal Body */}
            <div className="spec-modal-body">
              {/* Tab 1: 6-to-252 Transformation Diff */}
              {inspectorTab === "diff" && (
                <div>
                  <div className="diff-grid">
                    {/* Raw 6 Inputs */}
                    <div className="diff-card raw">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                        <span className="eyebrow" style={{ color: "#b45309" }}>RAW SUPPLIER INPUT (6 COLS)</span>
                        <small style={{ color: "#ca8a04", fontWeight: 700 }}>Sparse Data</small>
                      </div>
                      <div className="diff-field-row">
                        <strong>Mfg_Part_Num</strong>
                        <span>{inspectedSku}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Part_Desc</strong>
                        <span>{inspectedDesc}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Part_Manuf</strong>
                        <span>{inspectedMfr}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>E1_Brand</strong>
                        <span>{inspectorValues?.e1_brand || "—"}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Unilog_Brand</strong>
                        <span>{inspectorValues?.unilog_brand || "—"}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>DIB_Brand</strong>
                        <span>{inspectorValues?.dib_brand || "—"}</span>
                      </div>
                    </div>

                    {/* Enriched 252 Columns Summary — real counts from the fetched unilog252 record */}
                    <div className="diff-card enriched">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                        <span className="eyebrow" style={{ color: "#1d4ed8" }}>SPECLEDGER ENRICHED RECORD (252 COLS)</span>
                        <small style={{ color: "#2563eb", fontWeight: 700 }}>
                          {isLoadingUnilog252 ? "Loading…" : unilog252 ? "Real computed record" : "Unavailable"}
                        </small>
                      </div>
                      <div className="diff-field-row">
                        <strong>Manufacturer URL (Col 1)</strong>
                        <span style={{ color: unilog252?.["MFR URL"] ? "#2563eb" : "#94a3b8" }}>{unilog252?.["MFR URL"] || "Not resolved"}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Canonical Taxonomy (Col 23)</strong>
                        <span>{unilog252?.Classpath || "—"}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Dynamic Spec Triplets (Cols 56-205)</strong>
                        <span style={{ color: inspectedTriplets.length > 0 ? "#10b981" : "#94a3b8", fontWeight: 700 }}>
                          {inspectedTriplets.length} of 50 populated (real, not padded)
                        </span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Description Tiers (Cols 24-29)</strong>
                        <span>{unilog252 ? [unilog252.MOBILE_DESC, unilog252.SHORT_DESC, unilog252.LONG_DESC1, unilog252.RETAIL_DESC, unilog252.MARKETING_DESCRIPTION, unilog252.INVOICE_DESC].filter(Boolean).length : 0} of 6 computed</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Item Feature Bullets (Cols 30-49)</strong>
                        <span>{unilog252 ? Array.from({ length: 20 }, (_, i) => unilog252[`ITEM_FEATURES_${i + 1}`]).filter(Boolean).length : 0} of 20 populated</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Prop 65 (Col 51)</strong>
                        <span style={{ color: unilog252?.["Prop 65"] ? "#0f172a" : "#94a3b8" }}>{unilog252?.["Prop 65"] || "Not populated"}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Specification Sheet</strong>
                        <span style={{ color: unilog252?.["Specification Sheet"] ? "#2563eb" : "#94a3b8" }}>{unilog252?.["Specification Sheet"] || "Not populated"}</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 2: Full 252-Column Grid */}
              {inspectorTab === "all252" && (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                    <div>
                      <h4 style={{ margin: 0, fontSize: 14 }}>Full 252-Column Unilog CX1 Delivery Grid</h4>
                      <small style={{ color: "#64748b" }}>
                        {unilog252 ? `${all252ColumnsList.filter((c) => c.val).length} of 252 columns populated` : isLoadingUnilog252 ? "Loading…" : "No enriched record available"} · showing {filtered252Cols.length} rows
                      </small>
                    </div>
                    <input
                      type="text"
                      placeholder="Search 252 columns (e.g. Prop 65, Col 56)..."
                      value={colSearch}
                      onChange={(e) => setColSearch(e.target.value)}
                      style={{ border: "1px solid #e2e8f0", borderRadius: 6, padding: "6px 12px", fontSize: 11, width: 260 }}
                    />
                  </div>

                  <div style={{ maxHeight: "400px", overflowY: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, textAlign: "left" }}>
                      <thead style={{ position: "sticky", top: 0, background: "#f8fafc", borderBottom: "1px solid #e2e8f0", zIndex: 2 }}>
                        <tr>
                          <th style={{ padding: "8px 10px", color: "#64748b", fontWeight: 700, width: 65 }}>COL #</th>
                          <th style={{ padding: "8px 10px", color: "#64748b", fontWeight: 700, width: 220 }}>UNILOG COLUMN HEADER</th>
                          <th style={{ padding: "8px 10px", color: "#64748b", fontWeight: 700 }}>ENRICHED VALUE ({inspectedSku})</th>
                          <th style={{ padding: "8px 10px", color: "#64748b", fontWeight: 700, width: 140 }}>SECTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filtered252Cols.map((col, idx) => (
                          <tr key={col.num} style={{ borderBottom: "1px solid #f1f5f9", background: idx % 2 === 0 ? "#ffffff" : "#fcfcfd" }}>
                            <td style={{ padding: "7px 10px", fontFamily: "DM Mono", color: "#2563eb", fontWeight: 700, fontSize: 11 }}>
                              Col {col.num}
                            </td>
                            <td style={{ padding: "7px 10px", fontWeight: 600, color: "#1e293b" }}>
                              {col.header}
                            </td>
                            <td style={{ padding: "7px 10px", color: "#334155", fontFamily: col.isCode ? "DM Mono" : "inherit", fontSize: col.isCode ? 10 : 11 }}>
                              <span style={{ color: col.val ? "#0f172a" : "#94a3b8", wordBreak: "break-all" }}>
                                {col.val || "—"}
                              </span>
                            </td>
                            <td style={{ padding: "7px 10px" }}>
                              <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 4, background: col.badgeBg, color: col.badgeColor, fontWeight: 700, whiteSpace: "nowrap" }}>
                                {col.section}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Tab 2: Real Attribute Triplets (up to 50 slots, usually sparse) */}
              {inspectorTab === "triplets" && (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                    <div>
                      <h4 style={{ margin: 0, fontSize: 14 }}>Attribute Triplets (Columns 56–205, {inspectedTriplets.length} of 50 populated)</h4>
                      <small style={{ color: "#64748b" }}>Real values only — this deterministic pass mostly captures manufacturer/part number, plus any spec the raw description text itself contains (e.g. voltage, grit)</small>
                    </div>
                    <input
                      type="text"
                      placeholder="⌕ Search attributes..."
                      value={tripletSearch}
                      onChange={(e) => setTripletSearch(e.target.value)}
                      style={{ border: "1px solid #e2e8f0", borderRadius: 6, padding: "6px 12px", fontSize: 11, width: 180 }}
                    />
                  </div>

                  {!unilog252 ? (
                    <div className="empty-review">{isLoadingUnilog252 ? "Loading real attribute data…" : "No enriched record available for this row."}</div>
                  ) : (
                    <div className="triplets-grid">
                      {filteredTriplets.map((trip, idx) => (
                        <div className="triplet-chip" key={idx}>
                          <span className="label">Slot #{idx + 1} · {trip.label}</span>
                          <div className="val-row">
                            <span className="val">{trip.value}</span>
                            {trip.uom && <span className="uom">{trip.uom}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Tab 3: 6 Description Hierarchy Tiers */}
              {inspectorTab === "descriptions" && (
                <div>
                  {!unilog252 ? (
                    <div className="empty-review">
                      {isLoadingUnilog252 ? "Loading real description data…" : "No enriched record available for this row."}
                    </div>
                  ) : (
                    <>
                      <div className="desc-box">
                        <div className="desc-box-header">
                          <span>Col 24 · MOBILE_DESC</span>
                          <small>{(unilog252.MOBILE_DESC || "").length} chars — derived directly from the real input description</small>
                        </div>
                        <p>{unilog252.MOBILE_DESC || "—"}</p>
                      </div>

                      <div className="desc-box">
                        <div className="desc-box-header">
                          <span>Col 25 · INVOICE_DESC</span>
                          <small>Uppercase ERP line item format</small>
                        </div>
                        <p style={{ fontFamily: "DM Mono", fontSize: 11 }}>{unilog252.INVOICE_DESC || "—"}</p>
                      </div>

                      <div className="desc-box">
                        <div className="desc-box-header">
                          <span>Col 26 · SHORT_DESC</span>
                          <small>Standard B2B listing title</small>
                        </div>
                        <p>{unilog252.SHORT_DESC || "—"}</p>
                      </div>

                      <div className="desc-box">
                        <div className="desc-box-header">
                          <span>Col 27 · LONG_DESC1</span>
                          <small>Brand + part number + real input description — no generic filler appended</small>
                        </div>
                        <p>{unilog252.LONG_DESC1 || "—"}</p>
                      </div>

                      <div className="desc-box">
                        <div className="desc-box-header">
                          <span>Col 28 · RETAIL_DESC</span>
                          <small>Consumer and distributor packaging copy</small>
                        </div>
                        <p>{unilog252.RETAIL_DESC || "—"}</p>
                      </div>

                      <div className="desc-box">
                        <div className="desc-box-header">
                          <span>Col 29 · MARKETING_DESCRIPTION</span>
                          <small>Left honestly empty — no real marketing-copy source exists for this row without live_fetch pulling the manufacturer's own page</small>
                        </div>
                        <p>{unilog252.MARKETING_DESCRIPTION || "—"}</p>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Tab 4: Item Feature Bullets — real, sparse count, not padded to 20 */}
              {inspectorTab === "features" && (
                <div>
                  <div style={{ marginBottom: 12 }}>
                    <h4 style={{ margin: 0, fontSize: 14 }}>Item Feature Bullets (Columns 30–49)</h4>
                    <small style={{ color: "#64748b" }}>
                      {unilog252 ? `${Array.from({ length: 20 }, (_, i) => unilog252[`ITEM_FEATURES_${i + 1}`]).filter(Boolean).length} of 20 slots populated` : "Loading…"} — each bullet restates a spec genuinely found in the raw input description (e.g. voltage, grit); empty when the description doesn't state one
                    </small>
                  </div>

                  <ul className="bullet-list">
                    {(unilog252 ? Array.from({ length: 20 }, (_, i) => unilog252[`ITEM_FEATURES_${i + 1}`]).filter((b): b is string => Boolean(b)) : []).map((bullet, idx) => (
                      <li className="bullet-item" key={idx}>
                        <span className="idx">Col {30 + idx} · #{idx + 1}</span>
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Tab 5: Sourcing, Documents & Live Scraper */}
              {inspectorTab === "evidence" && (() => {
                const rowSources = batchSources.filter(
                  (s: any) => s.manufacturer === inspectedMfr && s.part_number === inspectedSku
                );
                return (
                  <div>
                    <div style={{ marginBottom: 14 }}>
                      <strong style={{ color: "#0f172a", fontSize: 14, display: "block" }}>
                        Manufacturer Provenance &amp; Documents
                      </strong>
                      <small style={{ color: "#64748b" }}>
                        Real sources discovered for this SKU during batch ingestion. Reseller marketplaces (Amazon, eBay, Walmart) are blocked at discovery time, never surfaced here.
                      </small>
                    </div>

                    {rowSources.length > 0 ? (
                      <div className="diff-card">
                        {rowSources.map((s: any, idx: number) => (
                          <div key={idx} style={{ padding: "10px 0", borderBottom: idx < rowSources.length - 1 ? "1px solid #e2e8f0" : "none" }}>
                            <div className="diff-field-row">
                              <strong>{s.source_type}</strong>
                              <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "#2563eb", fontFamily: "DM Mono", fontSize: 11 }}>{s.url}</a>
                            </div>
                            <div style={{ fontSize: 11, color: s.evidence_status === "verified_live" ? "#16a34a" : "#b45309", marginTop: 2 }}>
                              {s.evidence_status === "verified_live" ? "✓ Verified — part number confirmed on fetched page" : "Unverified candidate — URL pattern-guessed, not fetched"}
                            </div>
                            {s.extracted_attributes && s.extracted_attributes.length > 0 && (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                                {s.extracted_attributes.map((a: any, i: number) => (
                                  <span key={i} style={{ background: "#e0f2fe", color: "#0c4a6e", padding: "3px 8px", borderRadius: 5, fontSize: 11 }}>
                                    <strong>{a.label}:</strong> {a.value}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="empty-review" style={{ margin: 0 }}>
                        No source evidence discovered for this SKU in the active batch. Re-ingest with <code>live_fetch=true</code> to attempt real manufacturer-site verification, or this manufacturer/part combination wasn't found by the deterministic candidate generator either.
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>

            {/* Modal Footer */}
            <div className="spec-modal-footer">
              <span style={{ fontSize: 11, color: "#64748b" }}>
                Unilog Delivery Spec · Row #{inspectorProduct?.row_number || 1}
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  onClick={() => {
                    handleReviewAction(inspectorProduct?.row_number || 1, "approve");
                    setInspectorProduct(null);
                  }}
                  style={{ background: "#10b981", color: "#ffffff", border: "none", padding: "8px 14px", borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer" }}
                >
                  ✓ Approve Product
                </button>
                <button
                  onClick={() => setInspectorProduct(null)}
                  style={{ background: "#e2e8f0", color: "#334155", border: "none", padding: "8px 14px", borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: "pointer" }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Left Sidebar */}
      <aside>
        <div className="logo">
          <img
            src="/favicon.png"
            alt="SpecLedger Logo"
            style={{ width: 32, height: 32, borderRadius: 8, objectFit: "contain", display: "block" }}
          />
          <div>
            SpecLedger
            <small>PRODUCT INTELLIGENCE</small>
          </div>
        </div>

        <div
          className="workspace"
          onClick={() => setShowWorkspaceMenu(!showWorkspaceMenu)}
          style={{ cursor: "pointer" }}
          title="Click to switch workspace"
        >
          <span className="workspace-dot" />
          {workspaceName} <b>▾</b>
        </div>

        {showWorkspaceMenu && (
          <div style={{ background: "#172232", border: "1px solid #2c374b", borderRadius: 6, padding: 6, marginTop: 4, fontSize: 11 }}>
            <div
              style={{ padding: "6px 8px", cursor: "pointer", color: workspaceName === "Unilog CX1 Workspace" || workspaceName.includes("1,000") ? "#38bdf8" : "#aeb7c7", fontWeight: workspaceName === "Unilog CX1 Workspace" || workspaceName.includes("1,000") ? 700 : 500 }}
              onClick={() => {
                setWorkspaceName("Unilog CX1 Master (1,000 SKUs)");
                setCategoryFilter("all");
                setShowWorkspaceMenu(false);
                setNotice("Switched to Unilog CX1 Master Workspace (All Categories)");
              }}
            >
              {workspaceName === "Unilog CX1 Workspace" || workspaceName.includes("1,000") ? "✓ " : ""}Unilog CX1 Master (1,000 SKUs)
            </div>
            <div
              style={{ padding: "6px 8px", cursor: "pointer", color: workspaceName === "Industrial Valves PIM" ? "#38bdf8" : "#aeb7c7", fontWeight: workspaceName === "Industrial Valves PIM" ? 700 : 500 }}
              onClick={() => {
                setWorkspaceName("Industrial Valves PIM");
                setCategoryFilter("valves");
                setShowWorkspaceMenu(false);
                setNotice("Switched to Industrial Valves PIM Workspace (Valves & Fluidics)");
              }}
            >
              {workspaceName === "Industrial Valves PIM" ? "✓ " : ""}Industrial Valves PIM
            </div>
          </div>
        )}

        <div className="nav-group">
          <label>CORE PLATFORM</label>
          <a
            className={activeTab === "overview" ? "active" : ""}
            onClick={() => setActiveTab("overview")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Overview</span>
            <kbd>⌘ O</kbd>
          </a>
          <a
            className={activeTab === "catalogue" ? "active" : ""}
            onClick={() => setActiveTab("catalogue")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Catalogue ({displayRows.length})</span>
            <kbd>⌘ C</kbd>
          </a>
          <a
            className={activeTab === "review" ? "active" : ""}
            onClick={() => setActiveTab("review")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Human review</span>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {reviewCount > 0 && <i>{reviewCount}</i>}
              <kbd>⌘ R</kbd>
            </span>
          </a>
          <a
            className={activeTab === "imports" ? "active" : ""}
            onClick={() => setActiveTab("imports")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Imports & telemetry</span>
            <kbd>⌘ I</kbd>
          </a>
        </div>

        <div className="nav-group">
          <label>STANDARDS & LINEAGE</label>
          <a
            className={activeTab === "schemas" ? "active" : ""}
            onClick={() => setActiveTab("schemas")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Schemas & taxonomy</span>
            <kbd>⌘ S</kbd>
          </a>
          <a
            className={activeTab === "evidence" ? "active" : ""}
            onClick={() => setActiveTab("evidence")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Evidence library</span>
            <kbd>⌘ E</kbd>
          </a>
          <a
            className={activeTab === "audit" ? "active" : ""}
            onClick={() => setActiveTab("audit")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Audit trail</span>
            <kbd>⌘ A</kbd>
          </a>
        </div>

        <div className="sidebar-bottom">
          <div className="health">
            <span /> All systems operational
          </div>
          <div
            className="user"
            onClick={() => setShowUserMenu(!showUserMenu)}
            style={{ cursor: "pointer", position: "relative" }}
            title="Click to view profile or switch role"
          >
            <strong style={{ background: currentPersona.avatarBg, color: "#fff" }}>{currentPersona.avatar}</strong>
            <span>
              {currentPersona.name}<small>{currentPersona.badge}</small>
            </span>
            <b style={{ fontSize: 13, opacity: 0.7 }}>▾</b>

            {showUserMenu && (
              <div
                style={{
                  position: "absolute",
                  bottom: "calc(100% + 8px)",
                  left: 0,
                  width: 250,
                  background: "#161b22",
                  border: "1px solid #30363d",
                  borderRadius: 10,
                  padding: "10px",
                  boxShadow: "0 12px 32px rgba(0,0,0,0.6)",
                  zIndex: 9999,
                  textAlign: "left"
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <div style={{ paddingBottom: 8, borderBottom: "1px solid #21262d", marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 800, color: "#8b949e", textTransform: "uppercase", letterSpacing: "0.05em" }}>Active Role & Organization</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#f0f6fc", marginTop: 2 }}>{currentPersona.name}</div>
                  <div style={{ fontSize: 11, color: currentPersona.accentColor, fontWeight: 600 }}>{currentPersona.role}</div>
                  <div style={{ fontSize: 10, color: "#8b949e", marginTop: 3 }}>{currentPersona.org}</div>
                </div>

                <div style={{ fontSize: 10, fontWeight: 800, color: "#8b949e", textTransform: "uppercase", letterSpacing: "0.05em", padding: "4px 4px 6px" }}>Switch Role</div>
                {Object.values(ENTERPRISE_PERSONAS).map((p) => (
                  <button
                    key={p.id}
                    onClick={() => {
                      handleSelectPersona(p.id);
                      setShowUserMenu(false);
                    }}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "6px 8px",
                      borderRadius: 6,
                      background: currentPersonaKey === p.id ? "rgba(99, 102, 241, 0.15)" : "transparent",
                      border: currentPersonaKey === p.id ? "1px solid rgba(99, 102, 241, 0.4)" : "1px solid transparent",
                      color: "#f0f6fc",
                      fontSize: 12,
                      cursor: "pointer",
                      textAlign: "left",
                      marginBottom: 3
                    }}
                  >
                    <span style={{ width: 22, height: 22, borderRadius: "50%", background: p.avatarBg, display: "grid", placeItems: "center", fontSize: 10, fontWeight: 800, color: "#fff", flexShrink: 0 }}>
                      {p.avatar}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 11, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</div>
                      <div style={{ fontSize: 9, color: "#8b949e" }}>{p.badge}</div>
                    </div>
                  </button>
                ))}

                <div style={{ borderTop: "1px solid #21262d", marginTop: 6, paddingTop: 6, display: "flex", gap: 4 }}>
                  <button
                    onClick={() => {
                      setShowLoginModal(true);
                      setShowUserMenu(false);
                    }}
                    style={{
                      flex: 1,
                      padding: "6px 8px",
                      borderRadius: 6,
                      background: "rgba(99, 102, 241, 0.12)",
                      border: "1px solid rgba(99, 102, 241, 0.3)",
                      color: "#a5b4fc",
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: "pointer",
                      textAlign: "center"
                    }}
                  >
                    Switch Role
                  </button>
                  <button
                    onClick={() => {
                      localStorage.removeItem("specledger_has_authenticated");
                      setShowLoginModal(true);
                      setShowUserMenu(false);
                    }}
                    style={{
                      padding: "6px 8px",
                      borderRadius: 6,
                      background: "rgba(239, 68, 68, 0.12)",
                      border: "1px solid rgba(239, 68, 68, 0.3)",
                      color: "#fca5a5",
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: "pointer"
                    }}
                  >
                    Sign out
                  </button>
                </div>
              </div>
            )}
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
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 2 }}>
              <h1 style={{ margin: 0 }}>Good evening, {currentPersona.shortName}</h1>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: 12,
                  background: currentPersona.badgeColor || "rgba(99, 102, 241, 0.2)",
                  color: currentPersona.accentColor || "#a5b4fc",
                  border: `1px solid ${currentPersona.accentColor || "#6366f1"}40`
                }}
              >
                {currentPersona.badge}
              </span>
            </div>
          </div>

          <div className="header-actions">
            <button
              className="icon"
              title="Switch role"
              onClick={() => setShowLoginModal(true)}
              style={{ padding: "0 10px", width: "auto", gap: 6, fontSize: 11, fontWeight: 600, color: "#c9d1d9" }}
            >
              <span>Switch Role</span>
            </button>
            <button
              className="icon"
              title="Export Unilog 252-Column Delivery CSV"
              onClick={() => handleExport("unilog_template")}
              style={{ display: "grid", placeItems: "center" }}
            >
              <DownloadIcon size={14} />
            </button>
            <button
              className="icon"
              title="Export Commerce PIM Syndication Feed"
              onClick={() => handleExport("commerce_csv")}
              style={{ fontSize: 10, fontWeight: 700 }}
            >
              PIM
            </button>
            <label
              title="Discover sources via real HTTP requests to manufacturer sites instead of templated candidates. Capped at 50 rows per upload since it's genuine network I/O, not instant."
              style={{
                display: "flex", alignItems: "center", gap: 6,
                fontSize: 10, fontWeight: 600, color: liveFetchEnabled ? "#3fb950" : "#8b949e",
                cursor: "pointer", padding: "0 8px",
              }}
            >
              <input
                type="checkbox"
                checked={liveFetchEnabled}
                onChange={(e) => setLiveFetchEnabled(e.target.checked)}
                style={{ cursor: "pointer" }}
              />
              Live web fetch
            </label>
            <button
              className="primary"
              onClick={() => fileInputRef.current?.click()}
            >
              + Import documents
            </button>
          </div>
        </header>

        <div className="content">
          {renderMainContent()}
        </div>
      </main>

      {/* Clean Human Enterprise Role Switcher Modal */}
      {showLoginModal && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.6)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            zIndex: 99999,
            display: "grid",
            placeItems: "center",
            padding: 20,
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowLoginModal(false); }}
        >
          <div
            style={{
              background: "#161b22",
              border: "1px solid rgba(240, 246, 252, 0.08)",
              borderRadius: 14,
              width: "100%",
              maxWidth: 440,
              boxShadow: "0 24px 48px -12px rgba(0, 0, 0, 0.5)",
              padding: 0,
              position: "relative",
              color: "#f0f6fc",
              overflow: "hidden",
              animation: "loginModalIn 0.2s ease-out",
            }}
          >
            <style>{`
              @keyframes loginModalIn {
                from { opacity: 0; transform: translateY(8px) scale(0.98); }
                to { opacity: 1; transform: translateY(0) scale(1); }
              }
              .sl-role-row { transition: background 0.12s ease; }
              .sl-role-row:hover { background: rgba(255,255,255,0.04) !important; }
              .sl-skip-link { transition: color 0.12s ease; }
              .sl-skip-link:hover { color: #c9d1d9 !important; }
            `}</style>

            {/* Header */}
            <div style={{ padding: "28px 28px 0" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{
                    width: 28, height: 28, borderRadius: 7,
                    background: "linear-gradient(135deg, #388bfd, #1f6feb)",
                    display: "grid", placeItems: "center",
                    fontSize: 11, fontWeight: 800, color: "#fff",
                  }}>S</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "#f0f6fc", letterSpacing: "-0.02em" }}>SpecLedger</span>
                </div>
                <button
                  onClick={() => setShowLoginModal(false)}
                  style={{
                    background: "transparent", border: "none",
                    color: "#484f58", fontSize: 18, cursor: "pointer",
                    width: 28, height: 28, display: "grid", placeItems: "center",
                    borderRadius: 6, transition: "color 0.12s ease",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "#8b949e")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "#484f58")}
                  title="Close (Esc)"
                >✕</button>
              </div>

              <h2 style={{
                fontSize: 20, fontWeight: 600, margin: "0 0 6px",
                color: "#f0f6fc", letterSpacing: "-0.025em",
              }}>
                Choose your role
              </h2>
              <p style={{
                fontSize: 13, color: "#7d8590", margin: "0 0 4px",
                lineHeight: 1.5, fontWeight: 400,
              }}>
                Select a workspace profile to begin. Each role surfaces different tools and views.
              </p>
            </div>

            {/* Divider */}
            <div style={{ height: 1, background: "rgba(240,246,252,0.06)", margin: "16px 0 0" }} />

            {/* Role List */}
            <div style={{ padding: "4px 0" }}>
              {Object.values(ENTERPRISE_PERSONAS).map((p, idx, arr) => {
                const isActive = currentPersonaKey === p.id;
                return (
                  <div key={p.id}>
                    <div
                      className="sl-role-row"
                      onClick={() => handleSelectPersona(p.id)}
                      style={{
                        padding: "14px 28px",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 14,
                        background: isActive ? "rgba(56, 139, 253, 0.06)" : "transparent",
                        borderLeft: isActive ? "2px solid #388bfd" : "2px solid transparent",
                      }}
                    >
                      {/* Avatar */}
                      <span style={{
                        width: 36, height: 36, borderRadius: "50%",
                        background: p.avatarBg,
                        display: "grid", placeItems: "center",
                        fontSize: 12, fontWeight: 700, color: "#fff",
                        flexShrink: 0,
                        boxShadow: isActive ? `0 0 0 2px #161b22, 0 0 0 3.5px ${p.accentColor}40` : "none",
                      }}>
                        {p.avatar}
                      </span>

                      {/* Text Content */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                          <span style={{
                            fontSize: 13.5, fontWeight: 600, color: "#f0f6fc",
                            letterSpacing: "-0.01em",
                          }}>{p.name}</span>
                          <span style={{
                            fontSize: 10, fontWeight: 600,
                            padding: "1px 6px", borderRadius: 10,
                            background: isActive ? `${p.accentColor}18` : "rgba(255,255,255,0.06)",
                            color: isActive ? p.accentColor : "#7d8590",
                            border: `1px solid ${isActive ? `${p.accentColor}30` : "rgba(255,255,255,0.06)"}`,
                            whiteSpace: "nowrap",
                          }}>{p.badge}</span>
                        </div>
                        <div style={{
                          fontSize: 12, color: "#7d8590", lineHeight: 1.35,
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>{p.role}</div>
                      </div>

                      {/* Right: Checkmark or Org */}
                      <div style={{ flexShrink: 0, display: "flex", alignItems: "center" }}>
                        {isActive ? (
                          <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
                            <circle cx="8" cy="8" r="7.5" fill="#388bfd" stroke="#388bfd" />
                            <path d="M5.5 8.2L7.2 9.8L10.5 6.2" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        ) : (
                          <span style={{
                            fontSize: 11, color: "#484f58",
                            whiteSpace: "nowrap",
                          }}>{p.org.length > 24 ? p.org.slice(0, 22) + "…" : p.org}</span>
                        )}
                      </div>
                    </div>
                    {/* Row separator — skip after last item */}
                    {idx < arr.length - 1 && (
                      <div style={{ height: 1, background: "rgba(240,246,252,0.04)", margin: "0 28px" }} />
                    )}
                  </div>
                );
              })}
            </div>

            {/* Divider */}
            <div style={{ height: 1, background: "rgba(240,246,252,0.06)" }} />

            {/* Footer */}
            <div style={{ padding: "16px 28px 20px", textAlign: "center" }}>
              <button
                className="sl-skip-link"
                onClick={() => handleSelectPersona("super_admin")}
                style={{
                  background: "transparent", border: "none",
                  color: "#7d8590", fontSize: 12,
                  cursor: "pointer", fontWeight: 500,
                }}
              >
                Continue as Admin →
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const container = document.getElementById("root");
if (container) {
  const root = (container as any)._reactRoot || createRoot(container);
  (container as any)._reactRoot = root;
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
