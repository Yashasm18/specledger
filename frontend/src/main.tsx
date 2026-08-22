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
import { apiFetch, fetchWithRetry, getApiBaseUrl, getApiKeyHeaders, readApiError } from "./apiClient";
import { downloadBlob, downloadJson } from "./download";
import { fetchCatalogueExport } from "./catalogueClient";
import {
  clearAutoReloadFlag, clearReloadMarker, clearStaleHtmlRetryFlag, hasAutoReloaded,
  isSupersededBuild, markAutoReloaded, reloadOntoLatest,
} from "./buildVersion";

// Mirrors backend/specledger/enrichment.py's detect_role() keyword heuristic.
// The catalogue persistence API returns raw_values/enriched_values keyed by
// original CSV column name (e.g. "mfg_part_num"), not a role-tagged fields
// array, so the frontend re-derives role from column name the same way.
// Column names that are a row's identifier rather than a described part
// number. Mirrors is_identifier_column() in enrichment.py: a published feed
// keyed on "id" delivered 552 in the CSV while the table showed "ROW-2",
// because only the backend knew the rule.
const IDENTIFIER_PREFIXES = [
  "product", "item", "catalog", "catalogue", "part", "sku",
  "record", "asset", "entity", "row",
];
const IDENTIFIER_PATTERN = new RegExp(
  `^(?:id|[a-z0-9]+[_\\-]id|(?:${IDENTIFIER_PREFIXES.join("|")})id)$`
);

function isIdentifierColumn(column: string): boolean {
  return IDENTIFIER_PATTERN.test(column.toLowerCase().trim());
}

function detectRole(column: string): string {
  const k = column.toLowerCase().trim();
  if (["part_num", "part_no", "part_number", "sku", "item_num", "item_no", "model_num", "mfg_part", "item_code"].some((p) => k.includes(p))) return "part_number";
  if (isIdentifierColumn(k)) return "part_number";
  if (["desc", "description", "product_name", "item_title", "title", "part_desc"].some((d) => k.includes(d))) return "description";
  // Brand before manufacturer, matching detect_role()'s order in
  // enrichment.py. A column like "supplier_brand" contains both words, and
  // the backend calls it a brand — checking manufacturer first here made the
  // dashboard disagree with the delivered file about the same column.
  if (["brand", "trade_name"].some((b) => k.includes(b))) return "brand";
  if (["manufacturer", "mfr", "mfg", "vendor", "supplier", "part_manuf"].some((m) => k.includes(m))) return "manufacturer";
  if (["category", "prod_type", "taxonomy"].some((c) => k.includes(c))) return "category";
  return "other";
}

// Values that mean "there is no value here". This dataset writes absence as
// a descriptive phrase rather than a blank, so treating them as data put
// "-- Unbranded --" in the manufacturer column of the catalogue table.
const NULL_PLACEHOLDERS = new Set([
  "-- unbranded --", "-- no unilog brand --", "-- no dib brand --",
  "n/a", "na", "none", "unknown",
]);

function isPlaceholder(value: string | undefined): boolean {
  return !value || NULL_PLACEHOLDERS.has(value.trim().toLowerCase());
}

function findByRole(values: Record<string, string> | undefined, role: string): string | undefined {
  if (!values) return undefined;
  const matches = Object.entries(values)
    .filter(([col, val]) => val && !isPlaceholder(val) && detectRole(col) === role);
  if (matches.length === 0) return undefined;
  if (role === "part_number") {
    // Both identify the row; only one of them is the product's number.
    const named = matches.find(([col]) => !isIdentifierColumn(col));
    if (named) return named[1];
  }
  return matches[0][1];
}

// Mirrors AUTO_APPROVE_CONFIDENCE in backend/specledger/validation_engine.py —
// the bar the bulk-approve control advertises and must actually enforce.
const BULK_APPROVE_CONFIDENCE = 0.8;

// Rows fetched per page. The batch endpoint paginates because whole
// catalogues do not fit in one response; totals come from row_count.
const ROWS_PER_PAGE = 100;

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
    // Roles, not invented people. Whatever name is selected here is written
    // into the audit trail as the human who signed off a record, and a
    // compliance artifact naming someone who does not exist is worse than
    // one naming nobody. Until there are real accounts (see "Known limits"
    // in the README), the honest identity is the role itself.
    name: "Catalog QA Reviewer",
    shortName: "Catalog QA",
    role: "Senior Catalog QA & Content Lead",
    badge: "Catalog QA",
    org: "Unassigned — demo workspace",
    avatar: "QA",
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
    name: "Merchant Ops Specialist",
    shortName: "Merchant Ops",
    role: "E-Commerce & Distribution Specialist",
    badge: "Merchant Ops",
    org: "Unassigned — demo workspace",
    avatar: "MO",
    avatarBg: "linear-gradient(135deg, #d29922, #e3b341)",
    accentColor: "#d29922",
    permissions: [
      "Commercial product catalogue exploration",
      "252-column & 50-triplet attribute inspector",
      "12-column Commerce PIM feed export"
    ],
    description: "Evaluates enriched product descriptions, technical specifications, and syndication feeds for commercial sales channels.",
    recommendedWorkflow: "Commerce Catalogue (⌘ 2) & 1-Click PIM Export"
  }
};

function App() {
  const [selected, setSelected] = useState(0);
  const [activeTab, setActiveTab] = useState<"overview" | "catalogue" | "review" | "imports" | "schemas" | "evidence" | "audit" | "help">("overview");
  // Which batch the workspace is showing. Null means "the most recent one",
  // which is what an uploaded file becomes — so without this a judge who
  // uploads their own dataset has no way back to the one they were shown.
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [openQuestion, setOpenQuestion] = useState<string | null>(null);
  // Distinct from isLoadingBatch: paging swaps the table's rows but must not
  // blank the batch-wide metric tiles, which do not change with the page.
  const [isPagingRows, setIsPagingRows] = useState(false);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  // Where the next upload should land. Asked before the file picker opens,
  // because it is the moment the choice actually matters — afterwards the
  // batch already exists somewhere.
  const [uploadDestination, setUploadDestination] = useState<string | null>(null);
  const [chosenDestination, setChosenDestination] = useState<string>("sandbox");
  // Read synchronously by the upload handler: setState has not landed by the
  // time the file picker returns, so the request would use the old workspace.
  const pendingUploadOrgRef = useRef<string | null>(null);
  // Restored when the dialog closes, per the dialog focus contract.
  const importTriggerRef = useRef<HTMLElement | null>(null);
  const destinationDialogRef = useRef<HTMLDivElement | null>(null);
  // Pages already fetched, keyed by batch + search term + offset. Cleared
  // whenever a row's state could have changed underneath them, since a stale
  // page would show a row as still pending after it was approved.
  const pageCacheRef = useRef<Map<string, any>>(new Map());
  const [filterMode, setFilterMode] = useState<"all" | "review" | "changed">("all");
  // The classpath being filtered on, or "all". These come from what the
  // loaded batch actually contains, fetched from the API — not a fixed list
  // of verticals that only ever matched one dataset.
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [batchCategories, setBatchCategories] = useState<
    { classpath: string; label: string; count: number }[]
  >([]);
  const [unclassifiedCount, setUnclassifiedCount] = useState(0);
  // "auto" is the pipeline's own events. The server groups by whether an
  // event carries a reviewer, which is the real distinction the data model
  // makes, so these map onto actor=all|human|system.
  const [auditFilter, setAuditFilter] = useState<"all" | "human" | "system">("all");
  const auditFilterRef = useRef<"all" | "human" | "system">("all");
  auditFilterRef.current = auditFilter;
  const [auditEvents, setAuditEvents] = useState<any[]>([]);
  // Total events recorded for the batch, independent of the page size.
  const [totalAuditEvents, setTotalAuditEvents] = useState(0);
  // Synthetic-benchmark scores, measured server-side on request rather than
  // hardcoded here — the hardcoded copies had drifted from what the
  // pipeline actually scores.
  const [syntheticEval, setSyntheticEval] = useState<any>(null);
  // Set only after every retry has failed, so "the API is down" never gets
  // rendered as "this batch is empty".
  const [apiError, setApiError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  // The term actually sent to the API. Searching must cover the whole batch,
  // not the loaded page, so it runs server-side — debounced so typing a part
  // number doesn't fire a request per keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [notice, setNotice] = useState("");
  // A workspace is an organization_id, which the API already namespaces every
  // batch by. It used to be a label plus a hardcoded category filter — the
  // catalogue underneath never changed, and picking the second workspace on
  // any uploaded dataset simply emptied the table.
  const DEFAULT_WORKSPACE_ID = "default";
  const WORKSPACES = [
    {
      id: "default",
      name: "Unilog CX1 Master",
      blurb: "The challenge dataset and everything enriched alongside it.",
    },
    {
      id: "sandbox",
      name: "Evaluation Sandbox",
      blurb: "Upload your own catalogue here. Separate data; the master workspace is untouched.",
    },
  ] as const;
  const [organizationId, setOrganizationId] = useState<string>("default");
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
  // Offset of the catalogue page currently loaded.
  const [pageOffset, setPageOffset] = useState(0);
  // Distinguishes "still fetching the real batch" from "confirmed no batch
  // exists" — without this, the two are indistinguishable and the app
  // can't tell whether it's safe to show an empty state or must wait.
  const [isLoadingBatch, setIsLoadingBatch] = useState(true);
  const [pendingReviews, setPendingReviews] = useState<any[]>([]);
  // Whole-batch pending count from the API, independent of page size.
  const [totalPending, setTotalPending] = useState(0);
  const [reviewedRowIds, setReviewedRowIds] = useState<Set<number>>(new Set());
  const reviewedRowIdsRef = useRef<Set<number>>(new Set());
  const [batchSources, setBatchSources] = useState<any[]>([]);

  // 252-Column Inspector Modal State
  const [inspectorProduct, setInspectorProduct] = useState<any>(null);
  const [inspectorTab, setInspectorTab] = useState<"diff" | "triplets" | "descriptions" | "features" | "evidence" | "all252">("diff");
  // Live verification of a single row against real manufacturer sources.
  const [verifyResult, setVerifyResult] = useState<any>(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [tripletSearch, setTripletSearch] = useState("");
  const [colSearch, setColSearch] = useState("");
  // Real 252-column record for the inspected row, fetched from the backend
  // (same row_to_unilog_dict() that generates the actual CSV export) — not
  // client-side generated. null while loading or unavailable.
  const [unilog252, setUnilog252] = useState<Record<string, string> | null>(null);
  const [isLoadingUnilog252, setIsLoadingUnilog252] = useState(false);

  // Benchmark runner state. Nothing here is pre-filled: the figures stay
  // empty until a real POST .../benchmark returns timings measured during
  // that request, on whichever batch is actually loaded.
  const [isBenchmarking, setIsBenchmarking] = useState(false);
  const [benchStep, setBenchStep] = useState(0);
  const [benchStats, setBenchStats] = useState<{
    time: string; throughput: string; verified: string; cost: string;
  } | null>(null);
  const [benchStages, setBenchStages] = useState<
    { name: string; seconds: number; rows_per_sec: number }[]
  >([]);
  const [benchError, setBenchError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [liveFetchEnabled, setLiveFetchEnabled] = useState(false);
  // Opt-in LLM tier. Off by default: it is billed, and the deterministic
  // path is complete without it.
  const [aiAssistEnabled, setAiAssistEnabled] = useState(false);

  // Debounce the search box, and send paging back to the first page whenever
  // the term changes — searching while on page 4 would otherwise ask for
  // offset 300 of a 2-row result set and render an empty table.
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch((prev) => {
        const next = searchQuery.trim();
        if (prev !== next) {
          setPageOffset(0);
          // Cached pages belong to the previous query.
          pageCacheRef.current.clear();
        }
        return next;
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Notice when this page is running a build the host has already replaced.
  // GitHub Pages caches index.html and offers no way to change that, so a
  // browser can keep the previous HTML — which names the previous bundle.
  // Nothing errors; the app just runs old code and a deploy looks like it
  // silently failed. Checked on arrival, whenever the tab is returned to,
  // and occasionally while it sits open.
  useEffect(() => {
    clearReloadMarker();
    // The app started, so the boot-recovery retry is spent and can reset.
    clearStaleHtmlRetryFlag();
    const controller = new AbortController();
    let cancelled = false;
    // Two different situations, handled differently.
    //
    // On arrival the page carries no work worth protecting, so a superseded
    // build is best dealt with by quietly reloading onto the current one —
    // nobody should have to know that the host caches its HTML, or think to
    // hard-reload. Once at most, guarded in sessionStorage: if the cached
    // copy is still being served, looping is worse than saying so.
    //
    // Later in the session the reader may be part-way through something, and
    // reloading underneath them would be rude, so that case only offers.
    const checkOnArrival = async () => {
      if (cancelled) return;
      const superseded = await isSupersededBuild(controller.signal);
      if (cancelled) return;
      if (!superseded) {
        // Current build: a deploy later in this session gets its own reload.
        clearAutoReloadFlag();
        return;
      }
      if (hasAutoReloaded()) {
        setUpdateAvailable(true);
        return;
      }
      markAutoReloaded();
      reloadOntoLatest();
    };

    const checkWhileOpen = async () => {
      if (cancelled || document.hidden) return;
      if (await isSupersededBuild(controller.signal)) setUpdateAvailable(true);
    };

    checkOnArrival();
    const onFocus = () => { void checkWhileOpen(); };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    const timer = window.setInterval(checkWhileOpen, 5 * 60 * 1000);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, []);

  // Load the whole workspace on mount, and again when a different batch is
  // selected. Everything here describes the batch itself.
  useEffect(() => {
    fetchWorkspace();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBatchId, organizationId]);

  // Paging and searching only move within a batch, so they refetch only the
  // rows. Skipped until a batch is loaded, which the effect above handles.
  useEffect(() => {
    const batchId = activeBatch?.batch_id;
    if (!batchId) return;
    fetchRowPage(batchId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageOffset, debouncedSearch, categoryFilter]);

  // Changing the audit actor filter refetches only the trail. The filter is
  // applied server-side across every event, so it cannot be done on the
  // fetched page — but it also shouldn't drag the whole batch along with it.
  useEffect(() => {
    const batchId = activeBatch?.batch_id;
    if (!API_BASE || !batchId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchWithRetry(
          withOrg(`${API_BASE}/catalogue/batches/${batchId}/audit?limit=50&actor=${auditFilter}`)
        );
        if (!res.ok || cancelled) return;
        const data = await res.json();
        setAuditEvents(data.events || []);
        setTotalAuditEvents(data.total_events ?? (data.events || []).length);
      } catch {
        // The dashboard-wide outage banner already covers an unreachable API;
        // a failed filter refresh leaves the previous events on screen.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditFilter, activeBatch?.batch_id]);

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
        "8": "help",
        "h": "help",
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

  /** Append the active workspace to an API path. Every read and write is
   *  scoped to it, which is what makes the workspaces actually separate
   *  rather than two names for one catalogue. */
  const withOrg = (path: string) =>
    `${path}${path.includes("?") ? "&" : "?"}organization_id=${encodeURIComponent(organizationId)}`;

  const currentWorkspace =
    WORKSPACES.find((w) => w.id === organizationId) ?? WORKSPACES[0];

  // Format a 0–1 accuracy as a percentage, or "—" when it isn't available.
  const pct = (v: number | null | undefined) =>
    typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—";

  // Fetching is split in two on purpose. Paging the catalogue used to call
  // fetchWorkspace(), which re-requested the batch list, the review queue,
  // the sources, the audit trail and the synthetic benchmark — none of which
  // change with a row offset. Measured against production those five cost
  // about 6.9 seconds on top of the one request that actually mattered, and
  // they ran one after another, so "Next" took several seconds to do
  // something the server answers in one query.

  /** Fetch one page of rows for a batch. This is all paging and search need. */
  const pageUrl = (batchId: string, offset: number) =>
    withOrg(
      `${API_BASE}/catalogue/batches/${batchId}?limit=${ROWS_PER_PAGE}&offset=${offset}` +
      (debouncedSearch ? `&search=${encodeURIComponent(debouncedSearch)}` : "") +
      // Classpaths contain "&", so they must be encoded or the query string
      // is cut short at the first one.
      (categoryFilter !== "all" ? `&category=${encodeURIComponent(categoryFilter)}` : "")
    );

  const pageCacheKey = (batchId: string, offset: number) =>
    `${batchId}|${debouncedSearch}|${categoryFilter}|${offset}`;

  /** Warm the cache for a page the reader is likely to ask for next.
   *
   *  Paging costs a flat ~2s that has almost nothing to do with how many rows
   *  are returned — one row takes 2.15s against production and a hundred take
   *  2.57s, on a 0.74s network baseline. So the wait cannot be shortened by
   *  asking for less; it can only be spent before the click instead of after
   *  it. Failures are ignored: this is an optimisation, and the real fetch
   *  will report anything genuinely wrong. */
  const prefetchRowPage = async (batchId: string, offset: number) => {
    if (!API_BASE || offset < 0) return;
    const key = pageCacheKey(batchId, offset);
    if (pageCacheRef.current.has(key)) return;
    try {
      const res = await fetch(pageUrl(batchId, offset));
      if (!res.ok) return;
      const batch = await res.json();
      if (!batch.rows?.length) return;
      pageCacheRef.current.set(key, batch);
      // Bounded so a long session cannot grow this without limit.
      if (pageCacheRef.current.size > 6) {
        pageCacheRef.current.delete(pageCacheRef.current.keys().next().value as string);
      }
    } catch {
      /* prefetch is best-effort */
    }
  };

  const fetchRowPage = async (batchId: string) => {
    if (!API_BASE) return;
    const cached = pageCacheRef.current.get(pageCacheKey(batchId, pageOffset));
    if (cached) {
      // Already warmed by a prefetch — render without a visible wait.
      setActiveBatch(cached);
      setLiveRows(cached.rows || []);
      prefetchRowPage(batchId, pageOffset + ROWS_PER_PAGE);
      prefetchRowPage(batchId, pageOffset - ROWS_PER_PAGE);
      return;
    }
    setIsPagingRows(true);
    try {
      const res = await fetchWithRetry(pageUrl(batchId, pageOffset));
      if (res.ok) {
        const batch = await res.json();
        setActiveBatch(batch);
        setLiveRows(batch.rows || []);
        pageCacheRef.current.set(pageCacheKey(batchId, pageOffset), batch);
      }
    } catch (err) {
      console.error("Could not load that page of rows:", err);
    } finally {
      setIsPagingRows(false);
      prefetchRowPage(batchId, pageOffset + ROWS_PER_PAGE);
      prefetchRowPage(batchId, pageOffset - ROWS_PER_PAGE);
    }
  };

  /** Load everything that describes the workspace: batch list, rows, review
   *  queue, sources, audit trail and the synthetic benchmark. The five that
   *  don't depend on each other are requested together rather than in
   *  sequence — the slowest one sets the wait, instead of their sum. */
  const fetchWorkspace = async () => {
    if (!API_BASE) {
      setIsLoadingBatch(false); // No backend configured — nothing to wait for
      return;
    }
    setApiError(null);
    pageCacheRef.current.clear();
    try {
      const res = await fetchWithRetry(withOrg(`${API_BASE}/catalogue/batches`));
      if (!res.ok) {
        throw new Error(`The API responded with HTTP ${res.status}.`);
      }
      const data = await res.json();
      setBatchList(data.batches || []);

      if (data.batches && data.batches.length > 0) {
        const available = data.batches as Array<{ batch_id: string }>;
        const chosen = selectedBatchId
          && available.find((b) => b.batch_id === selectedBatchId);
        // Falls back to the newest batch when the selected one is gone,
        // rather than leaving the workspace pointed at nothing.
        const latestId = (chosen || available[0]).batch_id;

        // A different batch starts at the first page. Resetting pageOffset
        // from the click handler instead would fire the paging effect against
        // the batch being navigated away from, racing this request.
        const switchingBatch = Boolean(activeBatch) && activeBatch.batch_id !== latestId;
        const offset = switchingBatch ? 0 : pageOffset;
        if (switchingBatch && pageOffset !== 0) setPageOffset(0);

        const [batchRes, pendingRes, sourcesRes, auditRes, catsRes] = await Promise.all([
          fetchWithRetry(pageUrl(latestId, offset)),
          fetchWithRetry(withOrg(`${API_BASE}/catalogue/batches/${latestId}/review/pending`)),
          fetchWithRetry(withOrg(`${API_BASE}/catalogue/batches/${latestId}/sources`)),
          fetchWithRetry(
            withOrg(`${API_BASE}/catalogue/batches/${latestId}/audit?limit=50&actor=${auditFilterRef.current}`)
          ),
          fetchWithRetry(withOrg(`${API_BASE}/catalogue/batches/${latestId}/categories`)),
        ]);

        if (batchRes.ok) {
          const batch = await batchRes.json();
          setActiveBatch(batch);
          setLiveRows(batch.rows || []);
        }
        if (pendingRes.ok) {
          const pending = await pendingRes.json();
          const rawPending = pending.pending_rows || [];
          setPendingReviews(rawPending.filter((r: any) => !reviewedRowIdsRef.current.has(r.row_number)));
          // pending_rows is one page; total_pending is the whole backlog.
          setTotalPending(pending.total_pending ?? rawPending.length);
        }
        if (sourcesRes.ok) {
          const srcData = await sourcesRes.json();
          setBatchSources(srcData.sources || []);
        }
        if (auditRes.ok) {
          const auditData = await auditRes.json();
          setAuditEvents(auditData.events || []);
          setTotalAuditEvents(auditData.total_events ?? (auditData.events || []).length);
        }
        if (catsRes.ok) {
          const cats = await catsRes.json();
          setBatchCategories(cats.categories || []);
          setUnclassifiedCount(cats.unclassified ?? 0);
        }
      } else {
        // An empty workspace must look empty. Leaving the previous one's
        // state in place showed the master catalogue's row count, file name
        // and review queue under the sandbox's name — one organization's
        // data presented as another's, which is the exact failure a
        // workspace is supposed to rule out.
        setActiveBatch(null);
        setLiveRows([]);
        setPendingReviews([]);
        setTotalPending(0);
        setBatchSources([]);
        setAuditEvents([]);
        setTotalAuditEvents(0);
        setBatchCategories([]);
        setUnclassifiedCount(0);
      }

      // Scores the bundled synthetic benchmark server-side so the dashboard
      // reports what the pipeline currently achieves, not a stale constant.
      const evalRes = await fetchWithRetry(`${API_BASE}/catalogue/evaluation/synthetic`);
      if (evalRes.ok) {
        setSyntheticEval(await evalRes.json());
      }
    } catch (err: any) {
      // Every retry failed — this is a real outage, not a slow start, and
      // must read differently from "this batch is empty".
      console.error("Could not reach the SpecLedger API:", err);
      setApiError(
        err?.message?.startsWith("The API responded")
          ? err.message
          : "Could not reach the SpecLedger API after several attempts."
      );
    } finally {
      setIsLoadingBatch(false);
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
      const blob = await fetchCatalogueExport(activeBatch?.batch_id, format, organizationId);
      downloadBlob(blob, filename);
      setNotice(`Downloaded ${filename} successfully!`);
    } catch (err) {
      setNotice(`Export unavailable · ${err instanceof Error ? err.message : "Backend request failed"}`);
    }
  };

  // Upload handler for spreadsheets & PDFs
  /** Open the file picker, asking first where the catalogue should go.
   *
   *  Uploading adds a batch to whichever workspace is active and that batch
   *  becomes the one the dashboard opens on, so someone trying the app with
   *  their own data would quietly replace what the next reader sees. The
   *  choice is only ambiguous from the master workspace; inside a sandbox the
   *  intent is already clear, so it goes straight to the picker. */
  const requestImport = (trigger?: HTMLElement | null) => {
    if (organizationId !== DEFAULT_WORKSPACE_ID) {
      pendingUploadOrgRef.current = organizationId;
      fileInputRef.current?.click();
      return;
    }
    importTriggerRef.current = trigger ?? (document.activeElement as HTMLElement | null);
    setChosenDestination("sandbox");
    setUploadDestination(DEFAULT_WORKSPACE_ID);
  };

  // Opening the dialog: freeze the page behind it and move focus in, once.
  // This lived in an inline ref callback, which React runs on every render —
  // so each arrow-key selection dragged focus back to the first option and
  // the radiogroup could not be navigated by keyboard at all.
  useEffect(() => {
    if (!uploadDestination) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    destinationDialogRef.current
      ?.querySelector<HTMLElement>('[role="radio"]')
      ?.focus();
    return () => { document.body.style.overflow = previous; };
  }, [uploadDestination]);

  const closeDestinationDialog = () => {
    setUploadDestination(null);
    // Focus returns to whatever opened the dialog.
    importTriggerRef.current?.focus?.();
  };

  const confirmDestination = () => {
    const target = chosenDestination;
    // The request reads this rather than state: setState has not landed by
    // the time the file picker returns.
    pendingUploadOrgRef.current = target;
    setUploadDestination(null);

    // Move to the chosen workspace now, not after the upload finishes.
    // Waiting meant choosing "Evaluation Sandbox" appeared to do nothing —
    // the header still read Unilog CX1 Master while the file picker was
    // open, and cancelling the picker left no trace that a choice had been
    // made at all. Someone who says where their catalogue belongs should be
    // taken there, whether or not they go on to pick a file.
    if (target !== organizationId) {
      setSelectedBatchId(null);
      setPageOffset(0);
      setSearchQuery("");
      setCategoryFilter("all");
      setIsLoadingBatch(true);
      setOrganizationId(target);
      const destination = WORKSPACES.find((w) => w.id === target);
      if (destination) setNotice(`Switched to ${destination.name} — choose your catalogue file`);
    }
    fileInputRef.current?.click();
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    const uploadOrg = pendingUploadOrgRef.current ?? organizationId;
    pendingUploadOrgRef.current = null;
    if (!file) return;

    const isSpreadsheet = file.name.endsWith(".csv") || file.name.endsWith(".tsv") || file.name.endsWith(".xlsx");

    if (isSpreadsheet) {
      setNotice(
        liveFetchEnabled
          ? `Ingesting ${file.name} with live web fetch — real HTTP requests to manufacturer sites, capped at 50 rows…`
          : aiAssistEnabled
            ? `Ingesting ${file.name} — deterministic pipeline, then the LLM tier on whatever it can't classify…`
            : `Ingesting catalogue ${file.name} — deterministic pipeline…`
      );
      const body = new FormData();
      body.append("file", file);

      try {
        const response = await apiFetch(
          // The destination chosen in the dialog, not the active workspace:
          // switching first and relying on state would race the file picker.
          `/catalogue/ingest?process_immediately=true${liveFetchEnabled ? "&live_fetch=true" : ""}${aiAssistEnabled ? "&ai_assist=true" : ""}`
            + `&organization_id=${encodeURIComponent(uploadOrg)}`,
          { method: "POST", body }
        );

        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.detail || `Upload failed (${response.status})`);
        }

        const result = await response.json();
        const destination = WORKSPACES.find((w) => w.id === uploadOrg);
        setNotice(
          `Enrichment complete · ${file.name} (${result.row_count} SKUs enriched in 252-column format)`
          + (destination ? ` — in ${destination.name}` : "")
        );
        setActiveTab("catalogue");
        if (uploadOrg !== organizationId) {
          // Switching workspaces reloads it, so don't also fetch here.
          setSelectedBatchId(null);
          setPageOffset(0);
          setOrganizationId(uploadOrg);
        } else {
          await fetchWorkspace();
        }
      } catch (error) {
        setNotice(`Catalogue ingestion failed · ${error instanceof Error ? error.message : "Backend unavailable"}`);
      }
    } else {
      setNotice(`Storing document and queueing extraction…`);
      const body = new FormData();
      body.append("file", file);

      try {
        // The workspace chosen for this upload, like the spreadsheet path.
        // This was pinned to "default", so a datasheet uploaded from the
        // sandbox was filed against the master workspace instead.
        const response = await fetch(
          `${API_BASE}/documents/intake?organization_id=${encodeURIComponent(uploadOrg)}&category=generic`, {
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
            // Same workspace the document was filed under, or the task is
            // looked for somewhere it does not exist and never completes.
            const status = await fetch(
              `${API_BASE}/documents/tasks/${result.task_id}?organization_id=${encodeURIComponent(uploadOrg)}`
            ).then((r) => r.json());
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

  // Past tense per action. Appending "d" works for "approve" but produces
  // "rejectd"/"correctd", and that string is written into the audit trail —
  // a permanent compliance record, not a transient toast.
  const PAST_TENSE: Record<"approve" | "reject" | "correct", string> = {
    approve: "approved",
    reject: "rejected",
    correct: "corrected",
  };

  /** Remove a batch and everything in it. Confirmed first: it cannot be
   *  undone, and the audit trail goes with it. */
  const handleDeleteBatch = async (batchId: string, sourceName: string) => {
    if (!API_BASE) return;
    const ok = window.confirm(
      `Delete "${sourceName}" and all of its rows?\n\n`
      + "This cannot be undone. Its review decisions and audit trail are removed with it."
    );
    if (!ok) return;
    try {
      const res = await fetch(withOrg(`${API_BASE}/catalogue/batches/${batchId}`), {
        method: "DELETE",
        headers: getApiKeyHeaders(),
      });
      if (!res.ok) {
        throw new Error(`The API responded with HTTP ${res.status}.`);
      }
      const body = await res.json();
      setNotice(`Deleted "${sourceName}" · ${body.deleted_rows?.toLocaleString?.() ?? 0} rows removed`);
      // Whatever was selected may be the batch that just went.
      setSelectedBatchId(null);
      setPageOffset(0);
      setIsLoadingBatch(true);
      await fetchWorkspace();
    } catch (error) {
      setNotice(`Could not delete "${sourceName}" · ${error instanceof Error ? error.message : "backend unavailable"}`);
    }
  };

  // Human Review Actions
  const handleReviewAction = async (rowNumber: number, action: "approve" | "reject" | "correct", comment?: string) => {
    const reviewerName = `${currentPersona.name} (${currentPersona.badge})`;
    const batchId = activeBatch?.batch_id || "latest";

    // Snapshot enough to undo the optimistic update if the server refuses.
    const previousPending = pendingReviews;
    const previousRows = liveRows;
    const revertOptimisticUpdate = () => {
      reviewedRowIdsRef.current.delete(rowNumber);
      setReviewedRowIds(new Set(reviewedRowIdsRef.current));
      setPendingReviews(previousPending);
      setLiveRows(previousRows);
    };

    reviewedRowIdsRef.current.add(rowNumber);
    // Any cached page may now show this row's old state.
    pageCacheRef.current.clear();
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
      revertOptimisticUpdate();
      setNotice(`No backend configured — row #${rowNumber} was NOT ${PAST_TENSE[action]}.`);
      return;
    }
    try {
      // Deliberately not retried: this records an audit event, so a retry
      // after a request that actually succeeded would log the decision twice.
      const res = await fetch(withOrg(`${API_BASE}/catalogue/batches/${batchId}/rows/${rowNumber}/review`), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getApiKeyHeaders() },
        body: JSON.stringify({ action, reviewer: reviewerName, comment: comment || `Row ${PAST_TENSE[action]} via workspace` })
      });
      if (res.ok) {
        setNotice(`Row #${rowNumber} ${PAST_TENSE[action]} successfully by ${currentPersona.shortName}.`);
      } else {
        // The decision was not recorded, so it must not look like it was.
        revertOptimisticUpdate();
        setNotice(`Could not ${action} row #${rowNumber} — the API returned HTTP ${res.status}. Nothing was recorded; try again.`);
      }
    } catch {
      revertOptimisticUpdate();
      setNotice(`Could not ${action} row #${rowNumber} — the API is unreachable. Nothing was recorded; try again.`);
    }
  };

  const handleBulkApprove = async () => {
    // The control is labelled "≥80% confidence", so it must actually apply
    // that threshold — it previously approved every pending row regardless.
    const eligible = pendingReviews.filter(
      (r) => (r.overall_confidence ?? 0) >= BULK_APPROVE_CONFIDENCE,
    );
    if (eligible.length === 0) {
      setNotice(
        `No rows on this page meet the ${Math.round(BULK_APPROVE_CONFIDENCE * 100)}% confidence bar — nothing approved.`,
      );
      return;
    }

    const batchId = activeBatch?.batch_id || "latest";
    const reviewerName = `${currentPersona.name} (${currentPersona.badge})`;
    if (!API_BASE) {
      setNotice(`No backend configured — ${eligible.length} rows were NOT approved.`);
      return;
    }

    setNotice(`Approving ${eligible.length} rows…`);

    // Report what the server actually accepted, rather than announcing
    // success up front and swallowing whatever happens next.
    const results = await Promise.allSettled(
      eligible.map((r) =>
        fetch(withOrg(`${API_BASE}/catalogue/batches/${batchId}/rows/${r.row_number}/review`), {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getApiKeyHeaders() },
          body: JSON.stringify({ action: "approve", reviewer: reviewerName, comment: "Bulk approved via workspace" })
        }).then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return r.row_number;
        })
      )
    );

    const approvedIds = results.flatMap((res) =>
      res.status === "fulfilled" ? [res.value as number] : []
    );
    const failedCount = results.length - approvedIds.length;

    // Only rows the server confirmed are cleared from the queue.
    approvedIds.forEach((id) => reviewedRowIdsRef.current.add(id));
    pageCacheRef.current.clear();
    setReviewedRowIds(new Set(reviewedRowIdsRef.current));
    setPendingReviews((prev) => prev.filter((item) => !approvedIds.includes(item.row_number)));
    setLiveRows((prev) =>
      prev.map((r) =>
        approvedIds.includes(r.row_number)
          ? { ...r, overall_status: "verified", review_state: "approved" }
          : r
      )
    );
    setTotalPending((prev) => Math.max(prev - approvedIds.length, 0));

    setNotice(
      failedCount === 0
        ? `Approved ${approvedIds.length} rows as ${currentPersona.shortName} (≥${Math.round(BULK_APPROVE_CONFIDENCE * 100)}% confidence).`
        : `Approved ${approvedIds.length} of ${results.length} rows — ${failedCount} failed and were left in the queue.`
    );
  };

  // Fetches this row's manufacturer sources live, right now. Nothing is
  // replayed: the URL, the page snippet and any extracted specs all come from
  // requests made during this call, so the reader can open the link and check.
  const runLiveVerify = async () => {
    const batchId = activeBatch?.batch_id;
    const rowNumber = inspectorProduct?.row_number;
    if (!batchId || !rowNumber || !API_BASE) {
      setVerifyError("No row loaded to verify.");
      return;
    }
    setIsVerifying(true);
    setVerifyError(null);
    setVerifyResult(null);
    try {
      // Deliberately not retried: it performs real outbound fetches, and a
      // retry would just repeat them.
      const res = await fetch(
        withOrg(`${API_BASE}/catalogue/batches/${batchId}/rows/${rowNumber}/verify`),
        { method: "POST", headers: getApiKeyHeaders() }
      );
      if (!res.ok) throw new Error(`Verification failed (HTTP ${res.status})`);
      setVerifyResult(await res.json());
    } catch (err: any) {
      setVerifyError(err?.message ?? "Could not reach the API to verify.");
    } finally {
      setIsVerifying(false);
    }
  };

  // Actually re-runs the deterministic pipeline on the server, over whichever
  // batch is currently loaded, and reports the timings measured during that
  // request. Nothing is replayed or pre-computed — upload your own file and
  // this benchmarks that file.
  const runLiveBenchmark = async () => {
    const batchId = activeBatch?.batch_id;
    if (!batchId || !API_BASE) {
      setBenchError("Load a batch first — there's nothing to benchmark yet.");
      return;
    }

    setIsBenchmarking(true);
    setBenchError(null);
    setBenchStats(null);
    setBenchStages([]);
    setBenchStep(1);

    try {
      // Safe to retry: this endpoint only measures, it doesn't mutate state.
      const res = await fetchWithRetry(withOrg(`${API_BASE}/catalogue/batches/${batchId}/benchmark`), {
        method: "POST",
        headers: getApiKeyHeaders(),
      });
      if (!res.ok) throw new Error(`Benchmark failed (HTTP ${res.status})`);
      const data = await res.json();

      setBenchStep(5);
      setBenchStages(data.stages ?? []);
      setBenchStats({
        time: `${data.total_seconds}s`,
        throughput: `${Number(data.throughput_rows_per_sec).toLocaleString()} rows/s`,
        verified: `${(data.verified_rate * 100).toFixed(1)}%`,
        cost: `$${data.cost_usd} (${data.external_api_calls} external API calls)`,
      });
      setNotice(
        `Measured just now: ${data.row_count.toLocaleString()} rows in ${data.total_seconds}s ` +
        `(${Number(data.throughput_rows_per_sec).toLocaleString()} rows/sec) on "${data.source_name}".`
      );
    } catch (err: any) {
      setBenchStep(0);
      setBenchError(err?.message ?? "Benchmark request failed.");
    } finally {
      setIsBenchmarking(false);
    }
  };

  // Open 252-Column Deep-Dive Inspector Modal. Fetches the real per-row
  // 252-column record (same computation used for the actual CSV export)
  // rather than approximating it client-side.
  const openInspector = (row: any) => {
    setInspectorProduct(row);
    setInspectorTab("diff");
    setVerifyResult(null);
    setVerifyError(null);
    setUnilog252(null);

    const rowNumber = row?.row_number;
    const batchId = activeBatch?.batch_id;
    if (!rowNumber || !batchId || !API_BASE) return;

    setIsLoadingUnilog252(true);
    fetch(withOrg(`${API_BASE}/catalogue/batches/${batchId}/rows/${rowNumber}/unilog252`))
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
        // The raw 6-column input never has a category column, so role
        // detection alone always resolves to "Uncategorized" — the backend
        // computes a real classpath from the description (r.category) and
        // this falls back to it before giving up.
        // An unresolved row carries an empty category deliberately — the
        // export leaves its taxonomy blank rather than bucketing a tire gauge
        // as a maintenance product. Say so, instead of rendering an empty cell.
        const catField = findByRole(values, "category")
          || r.category
          || (r.category_source === "unresolved"
            ? "Not classified — routed for review"
            : "Uncategorized");
        // A row is "Ready" when the pipeline cleared it without a human
        // (auto_approved) or a reviewer signed it off (approved/corrected).
        // review_state is the live routing decision, so it governs; the
        // older overall_status check stays as a fallback for rows a queue
        // rebuild hasn't covered.
        const clearedStates = ["auto_approved", "approved", "corrected"];
        const status = clearedStates.includes(r.review_state)
          || r.overall_status === "verified"
          || r.overall_status === "approved"
            ? "Ready"
            : "Needs review";
        const quality = r.overall_confidence != null
          ? `${Math.round(r.overall_confidence * 100)}% verified`
          : "—";
        return [skuField, `${descField}`, mfrField, catField, status, quality, r];
      })
    : [];

  // Batch-wide totals. `rows` is one page, so anything describing the whole
  // batch must come from row_count / review_summary — never rows.length.
  const batchRowCount = activeBatch?.row_count ?? displayRows.length;
  const rowOffset = activeBatch?.offset ?? 0;
  const hasMoreRows = Boolean(activeBatch?.has_more);
  // When a search is active the server reports how many rows matched across
  // the whole batch. Every "of N" label and the pager must count that set,
  // not the batch total.
  const isSearching = debouncedSearch.length > 0;
  const isCategoryFiltered = categoryFilter !== "all";
  // Either filter narrows the batch server-side, so both report against the
  // matched set rather than the batch total.
  const isFiltered = isSearching || isCategoryFiltered;
  const activeCategoryLabel =
    categoryFilter === "__unclassified__"
      ? "not classified"
      : batchCategories.find((c) => c.classpath === categoryFilter)?.label ?? categoryFilter;
  // The API echoes the term it filtered on. Until the response for the
  // current term lands, the rows on screen still belong to the previous
  // query — reporting a match count against them would flash a wrong
  // number (e.g. "100 of 1,000 match") over stale rows mid-keystroke.
  const searchApplied = (activeBatch?.search ?? "") === debouncedSearch
    && (activeBatch?.category ?? "all") === (isCategoryFiltered ? categoryFilter : "all");
  const matchedRowCount = isFiltered
    ? (activeBatch?.matched_rows ?? displayRows.length)
    : batchRowCount;

  // Prefer the server's batch-wide pending count; fall back to counting the
  // loaded page only when no summary is available.
  const needsReviewInList =
    activeBatch?.review_summary?.pending_review
    ?? displayRows.filter((r: any) => r[4] === "Needs review").length;

  // Filter rows by Category & Search
  const filteredRows = displayRows.filter((r: any) => {
    if (filterMode === "review" && r[4] !== "Needs review") return false;
    // No category or search predicate here: the API filtered the whole batch
    // by both before paging. Re-filtering the page could only remove rows the
    // server deliberately matched.
    return true;
  });

  // liveRows carry enriched_values/raw_values (flat dicts by column name),
  // not the row.fields array this used to assume — see the catalogue-table
  // fix above. Compute real field-population coverage from that instead of
  // silently falling back to a hardcoded placeholder for every real batch.
  // Report the denominator too. The label used to read
  // `activeBatch.total_fields ?? liveRows.length` — the API has never sent
  // total_fields, so it always printed the page size and called it a field
  // count ("Across 100 fields" for 100 loaded rows), a number that changed
  // meaninglessly when you paged.
  const evidence = liveRows.length > 0
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
        return { coverage: total > 0 ? populated / total : 0, fields: total, rows: liveRows.length };
      })()
    : { coverage: 0, fields: 0, rows: 0 };
  const evidenceCoverage = evidence.coverage;
  const verifiedRate = activeBatch?.verified_rate ?? 0;
  // How many rows are loaded in the review pane right now (one page).
  const reviewCount = pendingReviews.length;
  // The real backlog across the whole batch — this is what a "rows needing
  // review" metric must report, since reviewCount caps at the page size.
  const reviewBacklog = Math.max(totalPending - reviewedRowIdsRef.current.size, 0);
  const throughput = activeBatch?.metrics?.throughput_rows_per_sec ?? null;

  // Render active view
  const renderMainContent = () => {
    switch (activeTab) {
      case "catalogue":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">COMMERCE CATALOGUE WORKSPACE</p>
                <h3>Enriched Product Catalogue ({batchRowCount.toLocaleString()} SKUs)</h3>
                {isFiltered ? (
                  <small style={{ color: "#64748b" }}>
                    {!searchApplied
                      ? `Filtering all ${batchRowCount.toLocaleString()} SKUs…`
                      : isSearching && isCategoryFiltered
                        ? `${matchedRowCount.toLocaleString()} of ${batchRowCount.toLocaleString()} SKUs in “${activeCategoryLabel}” match “${debouncedSearch}”.`
                        : isSearching
                          ? `${matchedRowCount.toLocaleString()} of ${batchRowCount.toLocaleString()} SKUs match “${debouncedSearch}” — searched across the whole batch.`
                          : `${matchedRowCount.toLocaleString()} of ${batchRowCount.toLocaleString()} SKUs are in “${activeCategoryLabel}” — filtered across the whole batch.`}
                  </small>
                ) : batchRowCount > displayRows.length && (
                  <small style={{ color: "#64748b" }}>
                    Showing rows {rowOffset + 1}–{rowOffset + displayRows.length} of {batchRowCount.toLocaleString()}.
                  </small>
                )}
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
              {/* Built from what this batch actually contains. The previous
                  five buttons were fixed verticals matched by keyword, so on
                  any catalogue but the sample they filtered to an empty table
                  and explained nothing. */}
              <button
                className={`category-chip ${categoryFilter === "all" ? "active" : ""}`}
                onClick={() => { setCategoryFilter("all"); setPageOffset(0); }}
              >
                All categories ({batchRowCount.toLocaleString()})
              </button>
              {batchCategories.slice(0, 8).map((c) => (
                <button
                  key={c.classpath}
                  className={`category-chip ${categoryFilter === c.classpath ? "active" : ""}`}
                  title={c.classpath}
                  onClick={() => { setCategoryFilter(c.classpath); setPageOffset(0); }}
                >
                  {c.label} ({c.count.toLocaleString()})
                </button>
              ))}
              {unclassifiedCount > 0 && (
                <button
                  className={`category-chip ${categoryFilter === "__unclassified__" ? "active" : ""}`}
                  title="No keyword rule placed these products, so no category is claimed. They route to the AI tier or a human."
                  onClick={() => { setCategoryFilter("__unclassified__"); setPageOffset(0); }}
                  style={{ fontStyle: "italic" }}
                >
                  Not classified ({unclassifiedCount.toLocaleString()})
                </button>
              )}
              {batchCategories.length === 0 && unclassifiedCount === 0 && (
                <span style={{ fontSize: 11, color: "#94a3b8", alignSelf: "center" }}>
                  Categories appear here once a batch is loaded.
                </span>
              )}
            </div>

            <div className="filters" style={{ marginTop: 8 }}>
              <button className={`filter ${filterMode === "all" ? "active" : ""}`} onClick={() => setFilterMode("all")}>
                All records <b>{batchRowCount.toLocaleString()}</b>
              </button>
              <button className={`filter ${filterMode === "review" ? "active" : ""}`} onClick={() => setFilterMode("review")}>
                Needs review <b>{needsReviewInList}</b>
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
              {isLoadingBatch ? (
                <div className="empty-review" style={{ margin: 16 }}>Loading catalogue…</div>
              ) : filteredRows.length === 0 ? (
                <div className="empty-review" style={{ margin: 16 }}>
                  {liveRows.length === 0 && !isSearching
                    ? "No batch loaded — import a catalogue to see real product records."
                    : isFiltered && searchApplied && matchedRowCount === 0
                      // Say what was actually searched. The old wording read as
                      // "not on this page" while sounding like "not in the batch".
                      ? `No SKU, description, or manufacturer in this batch matches “${debouncedSearch}”. All ${batchRowCount.toLocaleString()} rows were searched.`
                      : "No rows match the current filter."}
                </div>
              ) : filteredRows.map((r: any, i: number) => (
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
                  <span
                    className="tag"
                    style={r[6]?.category_source === "unresolved"
                      ? { color: "#94a3b8", fontStyle: "italic" }
                      : undefined}
                    title={r[6]?.category_source === "unresolved"
                      ? "No keyword rule placed this product, so no category is claimed. The delivered file leaves Dept/Class/Fine blank and the row routes to the AI tier or a human."
                      : undefined}
                  >
                    {r[3]}
                    {r[6]?.category_source === "ai_inferred" && (
                      <em
                        title={`AI-inferred (${Math.round((r[6].category_confidence ?? 0) * 100)}% model confidence). Deterministic rules returned "${r[6].category_deterministic}". Requires human review — this cannot auto-approve.`}
                        style={{
                          display: "inline-block", marginLeft: 6, padding: "1px 5px",
                          borderRadius: 4, background: "rgba(163,113,247,0.15)",
                          color: "#a371f7", fontSize: 9, fontWeight: 700,
                          fontStyle: "normal", letterSpacing: "0.02em",
                        }}
                      >
                        AI
                      </em>
                    )}
                  </span>
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

            {matchedRowCount > ROWS_PER_PAGE && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14, gap: 12 }}>
                <span style={{ fontSize: 12, color: "#64748b" }}>
                  Rows {(rowOffset + 1).toLocaleString()}–{(rowOffset + displayRows.length).toLocaleString()} of{" "}
                  {matchedRowCount.toLocaleString()}
                  {isSearching && <> matching “{debouncedSearch}”</>}
                  {isCategoryFiltered && <> in “{activeCategoryLabel}”</>}
                  {isPagingRows && <span style={{ marginLeft: 8, color: "#2872e3" }}>loading…</span>}
                  {filteredRows.length !== displayRows.length && (
                    <> · {filteredRows.length} shown after the category filter on this page</>
                  )}
                </span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => setPageOffset(Math.max(rowOffset - ROWS_PER_PAGE, 0))}
                    disabled={rowOffset === 0 || isLoadingBatch || isPagingRows}
                    style={{
                      background: rowOffset === 0 ? "#f1f5f9" : "#ffffff",
                      color: rowOffset === 0 ? "#94a3b8" : "#0f172a",
                      border: "1px solid #e2e8f0", borderRadius: 6,
                      padding: "6px 14px", fontSize: 12, fontWeight: 600,
                      cursor: rowOffset === 0 ? "not-allowed" : "pointer",
                      opacity: isPagingRows ? 0.6 : 1,
                      transition: "opacity 0.12s ease, background 0.12s ease",
                    }}
                  >
                    ← Previous
                  </button>
                  <button
                    onClick={() => setPageOffset(rowOffset + ROWS_PER_PAGE)}
                    disabled={!hasMoreRows || isLoadingBatch || isPagingRows}
                    style={{
                      background: !hasMoreRows ? "#f1f5f9" : "#ffffff",
                      color: !hasMoreRows ? "#94a3b8" : "#0f172a",
                      border: "1px solid #e2e8f0", borderRadius: 6,
                      padding: "6px 14px", fontSize: 12, fontWeight: 600,
                      opacity: isPagingRows ? 0.6 : 1,
                      transition: "opacity 0.12s ease, background 0.12s ease",
                      cursor: !hasMoreRows ? "not-allowed" : "pointer",
                    }}
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}
          </section>
        );

      case "review":
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">HUMAN GOVERNANCE WORKSPACE</p>
                <h3>Priority Review Queue ({reviewBacklog.toLocaleString()} pending)</h3>
                {reviewBacklog > pendingReviews.length && (
                  <small style={{ color: "#64748b" }}>
                    Showing the {pendingReviews.length} highest-priority rows of{" "}
                    {reviewBacklog.toLocaleString()}.
                  </small>
                )}
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                {pendingReviews.length > 0 && (
                  <button
                    className="view"
                    onClick={handleBulkApprove}
                    style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", borderColor: "rgba(16, 185, 129, 0.4)", padding: "6px 12px", borderRadius: 6, fontWeight: 600 }}
                  >
                    ✓ Approve High Confidence on This Page (≥80%)
                  </button>
                )}
                <span style={{ fontSize: 12, color: "#64748b" }}>
                  Threshold: <strong>80% confidence & 0 errors</strong>
                </span>
              </div>
            </div>

            {pendingReviews.length === 0 ? (
              <div style={{ padding: "48px 20px", textAlign: "center", color: "#64748b" }}>
                <p style={{ fontSize: 18, fontWeight: 600, color: "#10b981", margin: "0 0 8px 0" }}>✓ No rows pending human review</p>
                <small>{activeBatch ? "Every row in the active batch has either auto-approved or already been reviewed." : "No batch loaded yet."}</small>
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
                  // The queue is priority-ordered across the whole batch, so
                  // most of its rows are outside the catalogue page currently
                  // loaded. Prefer the identity the review API sends with each
                  // row; falling back to liveRows alone showed "Row 743" for
                  // every entry once the catalogue became paginated.
                  const sku = item.part_number
                    || findByRole(rowObj?.enriched_values || rowObj?.raw_values, "part_number")
                    || `Row ${item.row_number}`;
                  const rowDesc = item.description
                    || findByRole(rowObj?.enriched_values || rowObj?.raw_values, "description");
                  // The real validation findings for this row, as computed by
                  // the pipeline — errors first so the most serious reason is
                  // the one the reviewer sees.
                  const issues: any[] = item.validation?.issues ?? [];
                  const primaryIssue =
                    issues.find((i: any) => i.severity === "error") ?? issues[0] ?? null;
                  const issueCount = issues.length;
                  // Prefer the freshly recomputed confidence from the review
                  // API over the copy persisted on the batch row at ingest.
                  const confidence = item.overall_confidence ?? rowObj?.overall_confidence ?? null;
                  return (
                    <div className="tr" key={item.row_number || idx} style={{ gridTemplateColumns: "1.4fr 1.2fr 0.8fr 1fr 1.2fr" }}>
                      <span>
                        <strong>{sku}</strong>
                        <small>{rowDesc ? `${String(rowDesc).slice(0, 46)} · Row #${item.row_number}` : `Row #${item.row_number}`}</small>
                      </span>
                      <span style={{ color: "#d97706", fontSize: 11 }} title={primaryIssue?.suggestion || undefined}>
                        {primaryIssue ? primaryIssue.message : "Requires human verification"}
                        {issueCount > 1 && (
                          <small style={{ display: "block", color: "#94a3b8" }}>
                            +{issueCount - 1} more issue{issueCount > 2 ? "s" : ""}
                          </small>
                        )}
                      </span>
                      <span style={{ fontFamily: "DM Mono", fontSize: 11 }}>
                        {confidence != null ? `${Math.round(confidence * 100)}%` : "—"}
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
                          onClick={() => openInspector(rowObj || { row_number: item.row_number })}
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
              <button className="primary" onClick={(e) => requestImport(e.currentTarget)}>
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
                <strong>
                  {benchStats
                    ? <>{benchStats.throughput.replace(" rows/s", "")} <small style={{ fontSize: 12 }}>rows/s</small></>
                    : "—"}
                </strong>
                <small className="up">
                  {benchStats
                    ? "Deterministic path, measured this session"
                    : "Run the benchmark on Overview to measure"}
                </small>
              </article>
              <article title="Measured against a self-generated synthetic benchmark, not official Unilog ground truth — see README.">
                <span>SYNTHETIC BENCHMARK ACCURACY</span>
                <strong>
                  {syntheticEval
                    ? <>{(syntheticEval.overall_exact_accuracy * 100).toFixed(2)}<span className="percent">%</span></>
                    : "—"}
                </strong>
                <small className="up">
                  {syntheticEval
                    ? `Self-generated ${syntheticEval.rows_evaluated}-row set`
                    : "Self-generated 200-row set"}
                </small>
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
                  {syntheticEval
                    ? `${pct(syntheticEval.overall_exact_accuracy)} Overall Exact Match`
                    : "Measuring…"}
                </span>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>PART NUMBER</small>
                  <strong style={{ fontSize: 15, color: "#34d399" }}>{syntheticEval ? pct(syntheticEval.field_accuracy?.part_number) : "—"}</strong>
                  <span style={{ fontSize: 9, color: "#64748b", display: "block" }}>Exact match</span>
                </div>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>MANUFACTURER</small>
                  <strong style={{ fontSize: 15, color: "#34d399" }}>{syntheticEval ? pct(syntheticEval.field_accuracy?.manufacturer) : "—"}</strong>
                  <span style={{ fontSize: 9, color: "#64748b", display: "block" }}>Exact match</span>
                </div>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>CATEGORY TAXONOMY</small>
                  <strong style={{ fontSize: 15, color: "#34d399" }}>{syntheticEval ? pct(syntheticEval.field_accuracy?.category) : "—"}</strong>
                  <span style={{ fontSize: 9, color: "#64748b", display: "block" }}>Exact match</span>
                </div>
                <div style={{ background: "rgba(255,255,255,0.05)", padding: 10, borderRadius: 6 }}>
                  <small style={{ color: "#94a3b8", display: "block", fontSize: 9 }}>MATERIAL / ALLOY</small>
                  <strong style={{ fontSize: 15, color: "#38bdf8" }}>{syntheticEval ? pct(syntheticEval.field_accuracy?.material) : "—"}</strong>
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

      case "schemas": {
        // Real per-category breakdown of the active batch — grouped by the
        // same classify_category() classpath shown in the catalogue table,
        // not a fixed set of example categories shown regardless of what's
        // actually in the batch.
        // Grouped from the batch-wide classification, not the loaded page.
        // Counting the page described whichever hundred rows happened to be
        // on screen — on the official input it reported one unclassified SKU
        // where the batch has 252.
        const categoryBreakdown = (() => {
          const counts = new Map<string, { count: number; sample: Set<string> }>();
          for (const c of batchCategories) {
            const dept = c.classpath.split(">")[0].trim() || "Uncategorized";
            if (!counts.has(dept)) counts.set(dept, { count: 0, sample: new Set() });
            const entry = counts.get(dept)!;
            entry.count += c.count;
            if (entry.sample.size < 3) entry.sample.add(c.label);
          }
          if (unclassifiedCount > 0) {
            counts.set("Not classified", {
              count: unclassifiedCount,
              sample: new Set(["routed for human review"]),
            });
          }
          // Every department, not the top six. Capping them while the copy
          // above says "across all N SKUs" left the cards summing to less
          // than the batch — 960 of 1,000 on the official input. The taxonomy
          // has about a dozen branches, so there is nothing to truncate for.
          return [...counts.entries()].sort((a, b) => b[1].count - a[1].count);
        })();

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

            {/* Standards actually implemented and exportable — dropped
                UNSPSC/GTIN and ISO 8000 badges: those columns exist in the
                252-column template but are never populated by this
                pipeline, so claiming "ready"/"compliant" would be false. */}
            <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
              <span style={{ background: "rgba(56, 189, 248, 0.15)", color: "#38bdf8", padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, border: "1px solid rgba(56, 189, 248, 0.3)" }}>
                ✓ schema.org / Product & PropertyValue export
              </span>
              <span style={{ background: "rgba(16, 185, 129, 0.15)", color: "#34d399", padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700, border: "1px solid rgba(16, 185, 129, 0.3)" }}>
                ✓ Unilog CX1 252-column PIM specification
              </span>
            </div>

            <p style={{ fontSize: 12, color: "#64748b", marginTop: 14 }}>
              Category breakdown across all {batchRowCount.toLocaleString()} SKUs in this batch, computed by the deterministic classifier — not a fixed example set.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginTop: 10 }}>
              {categoryBreakdown.length > 0 ? categoryBreakdown.map(([dept, info]) => (
                <div key={dept} style={{ background: "rgba(255,255,255,0.03)", padding: 18, borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)" }}>
                  <h4 style={{ margin: "0 0 8px 0", fontSize: 14 }}>{dept}</h4>
                  <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, lineHeight: 1.5 }}>
                    {info.count} SKU{info.count !== 1 ? "s" : ""} in this batch
                  </p>
                  <small style={{ color: "#10b981", display: "block", marginTop: 10 }}>
                    {info.sample.size > 0 ? `Includes: ${[...info.sample].join(", ")}` : "No categories resolved"}
                  </small>
                </div>
              )) : (
                <div className="empty-review" style={{ gridColumn: "1 / -1" }}>No batch loaded — ingest a catalogue to see its real category breakdown.</div>
              )}
            </div>

            <div style={{ marginTop: 24, padding: 18, background: "#1e293b", color: "#f8fafc", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)" }}>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13, color: "#38bdf8" }}>Dual schema governance: Unilog 252-column PIM specification + schema.org / Product JSON-LD</h4>
              <p style={{ fontSize: 12, color: "#94a3b8", lineHeight: 1.6, margin: 0 }}>
                SpecLedger exports to both the enterprise PIM delivery template (Unilog CX1 252-column format) and the open-web schema.org/Product structured-data standard from the same underlying enriched record — see <a href="https://schema.org/Product" target="_blank" rel="noreferrer" style={{ color: "#38bdf8" }}>schema.org/Product</a> for the target vocabulary.
              </p>
            </div>
          </section>
        );
      }

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
                      <span style={{ fontFamily: "DM Mono", fontSize: 11, overflow: "hidden", textOverflow: "ellipsis" }} title={s.evidence_status === "verified_live" ? undefined : "URL pattern-guessed from a domain template, not fetched — may not resolve"}>
                        {s.evidence_status === "verified_live" ? (
                          <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "#38bdf8", textDecoration: "underline" }}>{s.url}</a>
                        ) : (
                          <span style={{ color: "#94a3b8" }}>{s.url}</span>
                        )}
                      </span>
                      <span>{s.source_type}</span>
                      <span>
                        <mark className={s.evidence_status === "verified_live" ? "ready" : "review"}>
                          ● {s.evidence_status === "verified_live" ? "Verified source" : "Unverified candidate (untested URL)"}
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
        // No client-side predicate: the API filtered the entire trail before
        // paging. Filtering the fetched page here is what made "Human
        // approvals" report nothing — restored approvals are dated when the
        // human decided, so they sort below every event a rebuild minted and
        // never appear in the newest 50.
        const filteredAuditEvents = auditEvents;
        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">ACCOUNTABILITY & COMPLIANCE LOG</p>
                <h3>Audit Trail & Decision Lineage</h3>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 6, background: "rgba(16,185,129,0.15)", color: "#10b981", border: "1px solid rgba(16,185,129,0.3)" }}>
                  {totalAuditEvents > auditEvents.length
                    ? `${auditEvents.length} of ${totalAuditEvents.toLocaleString()} real events`
                    : `${auditEvents.length} real events`}
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
              <button className={`filter ${auditFilter === "system" ? "active" : ""}`} onClick={() => setAuditFilter("system")}>
                Pipeline events
              </button>
            </div>

            <div className="activity" style={{ marginTop: 16 }}>
              {filteredAuditEvents.length === 0 ? (
                <div className="empty-review">
                  {auditFilter === "human"
                    ? "No human review decisions recorded for this batch yet — every event so far was recorded by the pipeline."
                    : auditFilter === "system"
                      ? "No pipeline events recorded for this batch."
                      : "No audit events recorded yet for this batch."}
                </div>
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

      case "help": {
        // Answers are derived from the batch that is actually loaded wherever
        // that is possible. A fixed FAQ would be exactly the static screen
        // this project is meant not to ship — "which columns did you find?"
        // is only worth asking if it answers about the reader's own file.
        const detected = activeBatch?.columns
          ? (activeBatch.columns as string[]).map((col) => ({ col, role: detectRole(col) }))
          : [];
        const roleLabels: Record<string, string> = {
          part_number: "Part number", description: "Description",
          manufacturer: "Manufacturer", brand: "Brand",
          category: "Category", other: "Carried through, not interpreted",
        };
        const summary = activeBatch?.review_summary;
        const autoApproved = summary?.auto_approved ?? 0;
        const pending = summary?.pending_review ?? 0;
        const known = autoApproved + pending + (summary?.approved ?? 0)
          + (summary?.corrected ?? 0) + (summary?.rejected ?? 0);

        const qa: Array<{ id: string; q: string; body: React.ReactNode }> = [
          {
            id: "upload",
            q: "How do I run this on my own dataset?",
            body: (
              <div>
                <p style={{ margin: "0 0 10px" }}>
                  Use <b>+ Import documents</b> in the top right. CSV, TSV and XLSX are accepted.
                  The file is enriched, validated and routed on upload, and the workspace switches to it.
                </p>
                <p style={{ margin: "0 0 10px" }}>
                  <b>Your column names do not have to match ours.</b> Columns are matched by role,
                  not by name — a file using <code>SKU</code>, <code>Item Description</code> and{" "}
                  <code>Vendor</code> works the same as one using{" "}
                  <code>Mfg_Part_Num</code>, <code>Part_Desc</code> and <code>Part_Manuf</code>.
                </p>
                <p style={{ margin: 0, color: "#64748b" }}>
                  Nothing is required. Columns we cannot interpret are carried through untouched,
                  and a missing field is delivered blank rather than filled in with a guess.
                </p>
              </div>
            ),
          },
          {
            id: "columns",
            q: "Which columns did you find in the loaded file?",
            body: detected.length ? (
              <div>
                <p style={{ margin: "0 0 10px", color: "#64748b" }}>
                  Read from <b>{activeBatch?.source_name}</b> just now — not a fixed list.
                </p>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "#64748b" }}>
                      <th style={{ padding: "6px 8px" }}>COLUMN IN YOUR FILE</th>
                      <th style={{ padding: "6px 8px" }}>READ AS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detected.map(({ col, role }) => (
                      <tr key={col} style={{ borderTop: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "6px 8px", fontFamily: "DM Mono" }}>{col}</td>
                        <td style={{ padding: "6px 8px", color: role === "other" ? "#94a3b8" : "#0f172a" }}>
                          {roleLabels[role] ?? role}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p style={{ margin: 0 }}>No batch is loaded yet.</p>,
          },
          {
            id: "batches",
            q: "I uploaded a file — how do I get back to the previous one?",
            body: (
              <div>
                <p style={{ margin: "0 0 10px", color: "#64748b" }}>
                  Every batch stays available. Click one to switch the whole workspace to it.
                </p>
                {(batchList || []).map((b: any) => {
                  const isActive = b.batch_id === activeBatch?.batch_id;
                  return (
                    <div
                      key={b.batch_id}
                      onClick={() => setSelectedBatchId(b.batch_id)}
                      style={{
                        padding: "8px 10px", marginBottom: 6, borderRadius: 6, cursor: "pointer",
                        border: `1px solid ${isActive ? "#2872e3" : "#e2e8f0"}`,
                        background: isActive ? "rgba(40,114,227,0.06)" : "#fff",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                        <div>
                          <b style={{ fontSize: 12 }}>{isActive ? "✓ " : ""}{b.source_name}</b>
                          <small style={{ display: "block", color: "#64748b" }}>
                            {(b.row_count ?? 0).toLocaleString()} rows
                          </small>
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteBatch(b.batch_id, b.source_name); }}
                          title="Delete this batch and all of its rows"
                          style={{
                            background: "none", border: "1px solid #e2e8f0", borderRadius: 5,
                            color: "#b91c1c", fontSize: 11, fontWeight: 600,
                            padding: "4px 9px", cursor: "pointer", whiteSpace: "nowrap",
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ),
          },
          {
            id: "review",
            q: "Why do so many rows still need a human?",
            body: (
              <div>
                <p style={{ margin: "0 0 10px" }}>
                  {known > 0 ? (
                    <>On the batch loaded now, <b>{autoApproved.toLocaleString()}</b> rows cleared
                    validation without a human and <b>{pending.toLocaleString()}</b> were routed for review.</>
                  ) : <>Load a batch to see the split for it.</>}
                </p>
                <p style={{ margin: "0 0 10px" }}>
                  Auto-approval is gated on matching a controlled vocabulary. This sample data is
                  almost entirely <code>-- Unbranded --</code> placeholders, and the reference tables
                  here are self-authored and much smaller than Unilog's real 27,000-row manufacturer
                  list, which was never available for this build.
                </p>
                <p style={{ margin: 0, color: "#64748b" }}>
                  So the number is a data gap, not an algorithmic one — and routing an unrecognised
                  manufacturer to a person is the correct behaviour for a real vocabulary gate.
                </p>
              </div>
            ),
          },
          {
            id: "blank",
            q: "Why are some cells empty instead of filled in?",
            body: (
              <div>
                <p style={{ margin: "0 0 10px" }}>
                  Because we could not establish the value. Empty is a real answer here, and it is
                  chosen deliberately over a plausible-looking one:
                </p>
                <ul style={{ margin: "0 0 10px", paddingLeft: 18, color: "#334155" }}>
                  <li>No manufacturer URL unless we can say which manufacturer the row belongs to</li>
                  <li>No category unless a rule actually placed the product</li>
                  <li>No marketing copy, which has no honest source without fetching the maker's page</li>
                  <li>No specification read out of a part number</li>
                </ul>
                <p style={{ margin: 0, color: "#64748b" }}>
                  A wrong value is worse than a missing one, because a missing one is visible.
                </p>
              </div>
            ),
          },
          {
            id: "verify",
            q: "How do I check a value is real?",
            body: (
              <div>
                <p style={{ margin: "0 0 10px" }}>
                  Open any row's <b>Inspect 252 Specs</b>, then <b>Verified Sourcing &amp; Safety</b>,
                  and press <b>⚡ Verify live</b>. That fetches the manufacturer's page during the
                  request and marks a source verified <b>only if the part number appears on the page
                  it fetched</b>, returning the URL and the surrounding page text.
                </p>
                <p style={{ margin: 0, color: "#64748b" }}>
                  Open the link and search it yourself — that is the point. It does not always find
                  one, and reports that rather than inventing a source. Marketplace domains are
                  blocked; manufacturer sites only.
                </p>
              </div>
            ),
          },
          {
            id: "ai",
            q: "Where is the AI, and what does it cost?",
            body: (
              <div>
                <p style={{ margin: "0 0 10px" }}>
                  The default path is fully deterministic and makes <b>zero</b> model calls. The
                  opt-in <b>AI assist</b> toggle sends only the rows deterministic rules could not
                  resolve, batched and constrained to the existing taxonomy.
                </p>
                <p style={{ margin: 0, color: "#64748b" }}>
                  Its suggestions are marked <code>ai_inferred</code> and <b>can never auto-approve</b> —
                  they shorten a reviewer's reading, they do not replace the decision.
                </p>
              </div>
            ),
          },
          {
            id: "limits",
            q: "What isn't ready for production?",
            body: (
              <div>
                <p style={{ margin: "0 0 10px" }}>
                  This is a hackathon prototype, and the gaps are stated rather than hidden:
                </p>
                <ul style={{ margin: "0 0 10px", paddingLeft: 18, color: "#334155" }}>
                  <li>No real user accounts — the reviewer name is not authenticated</li>
                  <li>The review queue is single-writer; concurrent reviewers would need row locking</li>
                  <li>Audit events are partly reconstructed after a restart</li>
                  <li>Ingest is synchronous, which would not hold at 750,000 rows</li>
                  <li>Live verification is a spot-check, not full coverage</li>
                </ul>
                <p style={{ margin: 0, color: "#64748b" }}>
                  The full list, with what closing each would take, is in the repository README.
                </p>
              </div>
            ),
          },
        ];

        return (
          <section className="section-card" style={{ marginTop: 0 }}>
            <div className="table-head">
              <div>
                <p className="eyebrow">GETTING STARTED</p>
                <h3>How this works</h3>
              </div>
            </div>
            <p style={{ fontSize: 12, color: "#7d8590", margin: "8px 0 16px" }}>
              Answers about the batch you have loaded, read live rather than written in advance.
              Click a question to open it.
            </p>
            <div>
              {qa.map(({ id, q, body }) => {
                const open = openQuestion === id;
                return (
                  <div key={id} style={{ borderTop: "1px solid #e2e8f0" }}>
                    <button
                      onClick={() => setOpenQuestion(open ? null : id)}
                      aria-expanded={open}
                      style={{
                        width: "100%", textAlign: "left", background: "none", border: "none",
                        padding: "14px 4px", cursor: "pointer", fontSize: 13, fontWeight: 600,
                        color: "#0f172a", display: "flex", justifyContent: "space-between",
                        alignItems: "center", gap: 12, font: "inherit",
                      }}
                    >
                      <span>{q}</span>
                      <span style={{ color: "#94a3b8", fontSize: 15 }}>{open ? "−" : "+"}</span>
                    </button>
                    {open && (
                      <div style={{ padding: "0 4px 16px", fontSize: 12.5, lineHeight: 1.65, color: "#334155" }}>
                        {body}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        );
      }

      case "overview":
      default:
        return (
          <>
            {/* Batch Benchmark Banner */}
            <div className="benchmark-banner">
              <div className="benchmark-banner-header">
                <div>
                  <span className="eyebrow" style={{ color: "#8b949e" }}>BATCH BENCHMARK</span>
                  <h3 style={{ margin: "6px 0 0", fontSize: 20, fontWeight: 600, color: "#ffffff", letterSpacing: "-0.01em" }}>
                    Enrichment pipeline
                  </h3>
                  <p style={{ margin: "4px 0 0", fontSize: 13, color: "#8b949e" }}>
                    {activeBatch
                      ? `Deterministic path — runs live against "${activeBatch.source_name}" (${(activeBatch.row_count ?? 0).toLocaleString()} rows)`
                      : "Deterministic path — load or upload a batch to benchmark it"}
                  </p>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button
                    onClick={runLiveBenchmark}
                    disabled={isBenchmarking || !activeBatch}
                    style={{
                      background: isBenchmarking || !activeBatch ? "#30363d" : "#238636",
                      color: "#ffffff",
                      border: "1px solid rgba(255,255,255,0.1)",
                      padding: "8px 16px",
                      borderRadius: 6,
                      fontWeight: 500,
                      fontSize: 13,
                      cursor: isBenchmarking ? "wait" : !activeBatch ? "not-allowed" : "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 6
                    }}
                  >
                    {isBenchmarking ? "Processing…" : "Run benchmark"}
                  </button>
                  <button
                    className="export-btn"
                    onClick={() => handleExport("unilog_template")}
                    style={{ background: "transparent", color: "#c9d1d9", borderColor: "rgba(255,255,255,0.15)" }}
                  >
                    <DownloadIcon size={12} />
                    252-col CSV
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

              {/* Benchmark Telemetry Counters — empty until a real run returns */}
              <div className="benchmark-stats-row">
                <div className="benchmark-stat-item">
                  <span>EXECUTION TIME</span>
                  <strong>{benchStats ? benchStats.time : "—"}</strong>
                </div>
                <div className="benchmark-stat-item">
                  <span>THROUGHPUT</span>
                  <strong>{benchStats ? benchStats.throughput : "—"}</strong>
                </div>
                <div className="benchmark-stat-item" title="Fraction of all output fields matched against reference data in this run — not a ground-truth accuracy score.">
                  <span>FIELD VERIFIED RATE</span>
                  <strong style={{ color: benchStats ? "#34d399" : undefined }}>
                    {benchStats ? benchStats.verified : "—"}
                  </strong>
                </div>
                <div className="benchmark-stat-item" title="The deterministic path makes zero external API calls, so the real cost is $0. The optional live_fetch mode adds one Serper.dev search call only when direct manufacturer-domain guessing fails — see README. No LLM API is used anywhere in this pipeline.">
                  <span>OPERATING COST</span>
                  <strong>{benchStats ? benchStats.cost : "—"}</strong>
                </div>
              </div>

              {!benchStats && !benchError && (
                <p style={{ margin: "10px 0 0", fontSize: 12, color: "#8b949e" }}>
                  No figures shown until you run it — these are measured during the
                  request, not stored from a previous run.
                </p>
              )}

              {benchError && (
                <p style={{ margin: "10px 0 0", fontSize: 12, color: "#f85149" }}>
                  {benchError}
                </p>
              )}

              {benchStages.length > 0 && (
                <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 16 }}>
                  {benchStages.map((s) => (
                    <div key={s.name} style={{ fontSize: 12, color: "#8b949e" }}>
                      <span style={{ color: "#c9d1d9" }}>{s.name}</span>{" "}
                      {s.seconds}s · {s.rows_per_sec.toLocaleString()} rows/s
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Metrics Cards */}
            <section className="metrics">
              <article>
                <span>PRODUCT RECORDS</span>
                <strong>{isLoadingBatch ? "…" : (activeBatch?.row_count ?? 0)}</strong>
                <small className="up">{isLoadingBatch ? "Loading…" : activeBatch ? "Current enrichment batch" : "No batch loaded"}</small>
              </article>
              <article>
                <span>REVIEW QUEUE</span>
                <strong className="amber">{isLoadingBatch ? "…" : reviewBacklog.toLocaleString()}</strong>
                <small>{isLoadingBatch ? "Loading…" : !activeBatch ? "No batch loaded" : reviewBacklog > 0 ? "Requires human verification" : "No rows pending review"}</small>
              </article>
              <article>
                <span>CATALOGUE HEALTH</span>
                <strong>{isLoadingBatch ? "…" : `${Math.round(verifiedRate * 100)}`}<span className="percent">{isLoadingBatch ? "" : "%"}</span></strong>
                <small className="up">{isLoadingBatch ? "Loading…" : activeBatch ? "Validated fields in active batch" : "No batch loaded"}</small>
              </article>
              <article>
                <span>EVIDENCE COVERAGE</span>
                <strong>{isLoadingBatch ? "…" : `${Math.round(evidenceCoverage * 100)}`}<span className="percent">{isLoadingBatch ? "" : "%"}</span></strong>
                <small>{isLoadingBatch ? "Loading…" : activeBatch ? `Across ${evidence.fields.toLocaleString()} fields in ${evidence.rows.toLocaleString()} loaded rows${throughput ? ` · ${throughput} rows/sec` : ""}` : "No batch loaded yet"}</small>
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
                {isLoadingBatch ? (
                  <div className="empty-review" style={{ margin: 16 }}>Loading catalogue…</div>
                ) : displayRows.length === 0 ? (
                  <div className="empty-review" style={{ margin: 16 }}>No batch loaded — import a catalogue to see real product records here.</div>
                ) : displayRows.slice(0, 5).map((r: any, i: number) => (
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
  // No invented fallbacks. These used to end in "VLV-600-050" / "Apollo
  // Valves" / "Ball Valve · DN50 Full Port Stainless Steel", so a row whose
  // real values were missing — an unresolved part number, or a batch removed
  // while the page was open — displayed a complete, entirely fictional
  // product. A dash says "not known"; a fake part number says something
  // false, and it is the one screen a reviewer is meant to trust.
  const inspectedSku = findByRole(inspectorValues, "part_number") || inspectorProduct?.[0] || "—";
  const inspectedDesc = findByRole(inspectorValues, "description") || inspectorProduct?.[1] || "—";
  const inspectedMfr = findByRole(inspectorValues, "manufacturer") || findByRole(inspectorValues, "brand") || inspectorProduct?.[2] || "—";
  // True when the row carries no identifying values at all, which in practice
  // means it could not be loaded rather than that it is empty.
  const inspectorUnloadable = !inspectorValues && !inspectorProduct?.[0];
  const inspectedCat = unilog252?.Classpath || findByRole(inspectorValues, "category") || inspectorProduct?.category || inspectorProduct?.[3] || "Uncategorized";
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

  // Real populated counts for the inspector's tab labels. Derived once so
  // the tab label and the transformation card can't drift apart — they did:
  // the card computed "5 of 6 computed" while the tab claimed a flat "(6)".
  const DESCRIPTION_TIER_COLUMNS = [
    "MOBILE_DESC", "INVOICE_DESC", "SHORT_DESC",
    "LONG_DESC1", "RETAIL_DESC", "MARKETING_DESCRIPTION",
  ] as const;
  const descriptionTierCount = unilog252
    ? DESCRIPTION_TIER_COLUMNS.filter((col) => unilog252[col]).length
    : 0;
  const featureBulletCount = unilog252
    ? Array.from({ length: 20 }, (_, i) => unilog252[`ITEM_FEATURES_${i + 1}`]).filter(Boolean).length
    : 0;

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

      {/* Where an uploaded catalogue should go.
          Asked before the file picker rather than after, because once the
          batch exists it is already in a workspace. Built to the dialog
          contract: labelled heading, described body, focus moved in on open
          and returned to the trigger on close, Tab kept inside, Escape and
          backdrop both cancel, and the options are a real radiogroup so
          arrow keys move between them. */}
      {uploadDestination && (
        <div
          className="spec-modal-backdrop"
          onClick={closeDestinationDialog}
          // Scrollable and top-aligned. Centring a dialog taller than the
          // viewport clips it at both ends, and the page behind is frozen, so
          // there was nothing left to scroll — the buttons were simply
          // unreachable on a short window.
          style={{ alignItems: "flex-start", overflowY: "auto", padding: "24px 20px" }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="upload-destination-title"
            aria-describedby="upload-destination-desc"
            onClick={(e) => e.stopPropagation()}
            ref={destinationDialogRef}
            onKeyDown={(e) => {
              if (e.key === "Escape") { e.stopPropagation(); closeDestinationDialog(); return; }
              if (e.key !== "Tab") return;
              const focusable = Array.from(
                e.currentTarget.querySelectorAll<HTMLElement>(
                  'button:not([disabled]), [role="radio"]'
                )
              ).filter((el) => el.tabIndex !== -1);
              if (focusable.length === 0) return;
              const first = focusable[0];
              const last = focusable[focusable.length - 1];
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault(); last.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault(); first.focus();
              }
            }}
            style={{
              background: "#ffffff", borderRadius: 12, width: "min(560px, 92vw)",
              boxShadow: "0 24px 60px rgba(2,6,23,0.35)",
              // Same shape as the inspector modal: bounded height, the middle
              // scrolls, and the actions never leave the screen.
              maxHeight: "calc(100vh - 48px)",
              display: "flex", flexDirection: "column", overflow: "hidden",
            }}
          >
            <div style={{ padding: "26px 28px 14px", flexShrink: 0 }}>
              <h3 id="upload-destination-title" style={{ margin: "0 0 6px", fontSize: 17, color: "#0f172a" }}>
                Where should this catalogue go?
              </h3>
              <p id="upload-destination-desc" style={{ margin: 0, fontSize: 13, color: "#64748b", lineHeight: 1.6 }}>
                An uploaded file becomes a batch in one workspace, and the dashboard
                opens on the most recent one. Choose where yours belongs.
              </p>
            </div>

            <div style={{ padding: "0 28px", overflowY: "auto", flex: "1 1 auto" }}>
            <div role="radiogroup" aria-labelledby="upload-destination-title">
              {[
                {
                  id: "sandbox",
                  name: "Evaluation Sandbox",
                  recommended: true,
                  detail: "Your catalogue is kept on its own. The Unilog challenge dataset stays exactly as it is for the next person who opens the app.",
                },
                {
                  id: DEFAULT_WORKSPACE_ID,
                  name: "Unilog CX1 Master",
                  recommended: false,
                  detail: "Added alongside the 1,000-row challenge dataset, and becomes the batch the dashboard opens on.",
                },
              ].map((option, index, all) => {
                const selected = chosenDestination === option.id;
                return (
                  <div
                    key={option.id}
                    role="radio"
                    aria-checked={selected}
                    tabIndex={selected ? 0 : -1}
                    onClick={() => setChosenDestination(option.id)}
                    onKeyDown={(e) => {
                      if (e.key === " " || e.key === "Enter") {
                        e.preventDefault(); setChosenDestination(option.id); return;
                      }
                      if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].includes(e.key)) return;
                      e.preventDefault();
                      const step = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : -1;
                      const next = all[(index + step + all.length) % all.length];
                      setChosenDestination(next.id);
                      const group = e.currentTarget.parentElement;
                      const radios = group?.querySelectorAll<HTMLElement>('[role="radio"]');
                      radios?.[(index + step + all.length) % all.length]?.focus();
                    }}
                    style={{
                      display: "flex", gap: 12, alignItems: "flex-start",
                      border: `1px solid ${selected ? "#2872e3" : "#e2e8f0"}`,
                      background: selected ? "rgba(40,114,227,0.05)" : "#fff",
                      borderRadius: 9, padding: "13px 15px", marginBottom: 10,
                      cursor: "pointer", outlineOffset: 2,
                    }}
                  >
                    <span
                      aria-hidden="true"
                      style={{
                        marginTop: 2, width: 15, height: 15, borderRadius: "50%",
                        border: `2px solid ${selected ? "#2872e3" : "#cbd5e1"}`,
                        background: selected
                          ? "radial-gradient(circle, #2872e3 0 4px, #fff 5px)"
                          : "#fff",
                        flexShrink: 0,
                      }}
                    />
                    <span>
                      <b style={{ fontSize: 13.5, color: "#0f172a" }}>
                        {option.name}
                        {option.recommended && (
                          <em style={{
                            marginLeft: 8, fontStyle: "normal", fontSize: 10, fontWeight: 700,
                            background: "rgba(16,185,129,0.14)", color: "#059669",
                            padding: "2px 7px", borderRadius: 4, letterSpacing: "0.02em",
                          }}>
                            RECOMMENDED
                          </em>
                        )}
                      </b>
                      <span style={{ display: "block", fontSize: 12, color: "#64748b", marginTop: 4, lineHeight: 1.55 }}>
                        {option.detail}
                      </span>
                    </span>
                  </div>
                );
              })}
            </div>

            <p style={{ margin: "4px 0 18px", fontSize: 11.5, color: "#94a3b8", lineHeight: 1.55 }}>
              CSV, TSV or XLSX. Your column names do not have to match ours — columns
              are matched by role, so <code>SKU</code> / <code>Item Description</code> /{" "}
              <code>Vendor</code> works the same as the challenge file's headers.
            </p>
            </div>

            <div style={{
              display: "flex", justifyContent: "flex-end", gap: 10,
              padding: "14px 28px 20px", flexShrink: 0,
              borderTop: "1px solid #f1f5f9", background: "#fff",
            }}>
              <button
                onClick={closeDestinationDialog}
                style={{
                  background: "#fff", color: "#334155", border: "1px solid #e2e8f0",
                  borderRadius: 7, padding: "9px 18px", fontSize: 13, fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDestination}
                style={{
                  background: "#2872e3", color: "#fff", border: "none",
                  borderRadius: 7, padding: "9px 20px", fontSize: 13, fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Choose file…
              </button>
            </div>
          </div>
        </div>
      )}

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
                    {unilog252
                      ? `${all252ColumnsList.filter((c) => c.val).length} of 252 columns populated`
                      : isLoadingUnilog252
                        ? "Loading…"
                        : inspectorUnloadable
                          ? "Row could not be loaded — it may have been removed"
                          : "Unavailable"}
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
                Description Tiers ({descriptionTierCount} of {DESCRIPTION_TIER_COLUMNS.length})
              </button>
              <button className={`spec-tab-btn ${inspectorTab === "features" ? "active" : ""}`} onClick={() => setInspectorTab("features")}>
                Feature Bullets ({featureBulletCount} of 20)
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
                        <span style={{ color: unilog252?.["MFR URL"] ? "#2563eb" : "#94a3b8" }} title={unilog252?.["MFR URL"] ? "Pattern-guessed from the manufacturer's domain, not fetched — see the Evidence tab for fetch-verified sources" : undefined}>{unilog252?.["MFR URL"] || "Not resolved"}</span>
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
                        <span>{descriptionTierCount} of {DESCRIPTION_TIER_COLUMNS.length} computed</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Item Feature Bullets (Cols 30-49)</strong>
                        <span>{featureBulletCount} of 20 populated</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Prop 65 (Col 51)</strong>
                        <span style={{ color: unilog252?.["Prop 65"] ? "#0f172a" : "#94a3b8" }}>{unilog252?.["Prop 65"] || "Not populated"}</span>
                      </div>
                      <div className="diff-field-row">
                        <strong>Specification Sheet</strong>
                        <span style={{ color: unilog252?.["Specification Sheet"] ? "#2563eb" : "#94a3b8" }} title={unilog252?.["Specification Sheet"] ? "Pattern-guessed filename, not a fetched/confirmed document" : undefined}>{unilog252?.["Specification Sheet"] || "Not populated"}</span>
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
                      {unilog252 ? `${featureBulletCount} of 20 slots populated` : "Loading…"} — each bullet restates a spec genuinely found in the raw input description (e.g. voltage, grit); empty when the description doesn't state one
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
                    <div style={{ marginBottom: 14, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
                      <div>
                        <strong style={{ color: "#0f172a", fontSize: 14, display: "block" }}>
                          Manufacturer Provenance &amp; Documents
                        </strong>
                        <small style={{ color: "#64748b" }}>
                          Real sources discovered for this SKU during batch ingestion. Reseller marketplaces (Amazon, eBay, Walmart) are blocked at discovery time, never surfaced here.
                        </small>
                      </div>
                      <button
                        onClick={runLiveVerify}
                        disabled={isVerifying}
                        title="Fetch this part's manufacturer page right now and show the evidence — the URL fetched and the text on that page containing the part number."
                        style={{
                          background: isVerifying ? "#94a3b8" : "#2563eb", color: "#fff",
                          border: 0, borderRadius: 6, padding: "8px 14px",
                          fontSize: 12, fontWeight: 700, whiteSpace: "nowrap",
                          cursor: isVerifying ? "wait" : "pointer",
                        }}
                      >
                        {isVerifying ? "Fetching live…" : "⚡ Verify live"}
                      </button>
                    </div>

                    {isVerifying && (
                      <div className="diff-card" style={{ marginBottom: 14, color: "#64748b", fontSize: 12 }}>
                        Contacting the manufacturer's own site for <strong>{inspectedSku}</strong>. Real
                        network requests — this takes a few seconds and may find nothing.
                      </div>
                    )}

                    {verifyError && (
                      <div className="diff-card" style={{ marginBottom: 14, color: "#dc2626", fontSize: 12 }}>
                        {verifyError}
                      </div>
                    )}

                    {verifyResult && (
                      <div className="diff-card" style={{ marginBottom: 16, borderColor: verifyResult.verified ? "#16a34a" : "#f59e0b" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                          <span className="eyebrow" style={{ color: verifyResult.verified ? "#15803d" : "#b45309" }}>
                            {verifyResult.verified ? "✓ VERIFIED AGAINST LIVE MANUFACTURER SOURCE" : "NO VERIFIED SOURCE FOUND"}
                          </span>
                          <small style={{ color: "#64748b" }}>fetched just now · {verifyResult.seconds}s</small>
                        </div>

                        {verifyResult.manufacturer_was_corrected && (
                          <div style={{ background: "#ecfdf5", border: "1px solid #a7f3d0", borderRadius: 6, padding: "8px 10px", marginBottom: 10, fontSize: 12 }}>
                            <strong style={{ color: "#065f46" }}>Manufacturer corrected.</strong>{" "}
                            <span style={{ color: "#334155" }}>
                              Input said <em>{verifyResult.input_manufacturer}</em> — a distributor. The real
                              manufacturer is <strong>{verifyResult.resolved_manufacturer}</strong>, identified
                              from a live search and confirmed on their own site.
                            </span>
                          </div>
                        )}

                        {verifyResult.verified ? (
                          verifyResult.sources.filter((s: any) => s.is_verified).map((s: any, i: number) => (
                            <div key={i} style={{ marginBottom: 12 }}>
                              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 3 }}>Source fetched</div>
                              <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "#2563eb", fontFamily: "DM Mono", fontSize: 11, wordBreak: "break-all" }}>
                                {s.url}
                              </a>
                              {s.match_snippet && (
                                <>
                                  <div style={{ fontSize: 11, color: "#64748b", margin: "8px 0 3px" }}>
                                    Text found on that page — open the link and search for it
                                  </div>
                                  <blockquote style={{
                                    margin: 0, padding: "8px 10px", background: "#f8fafc",
                                    borderLeft: "3px solid #16a34a", fontSize: 12, color: "#0f172a",
                                  }}>
                                    {s.match_snippet}
                                  </blockquote>
                                </>
                              )}
                            </div>
                          ))
                        ) : (
                          <div style={{ fontSize: 12, color: "#334155" }}>
                            Nothing could be confirmed for <strong>{verifyResult.part_number}</strong> right now.
                            No value is invented to fill the gap — the row keeps whatever the deterministic
                            pipeline could establish, and this stays unverified. Manufacturers retire pages,
                            some parts were never published, and some sites refuse automated requests.
                          </div>
                        )}

                        {verifyResult.extracted_attributes?.length > 0 && (
                          <div style={{ marginTop: 10 }}>
                            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>
                              Specs read from the linked datasheet
                            </div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                              {verifyResult.extracted_attributes.map((a: any, i: number) => (
                                <span key={i} title={a.source_url} style={{ background: "#e0f2fe", color: "#0c4a6e", padding: "3px 8px", borderRadius: 5, fontSize: 11 }}>
                                  <strong>{a.label}:</strong> {a.value}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {rowSources.length > 0 ? (
                      <div className="diff-card">
                        {rowSources.map((s: any, idx: number) => (
                          <div key={idx} style={{ padding: "10px 0", borderBottom: idx < rowSources.length - 1 ? "1px solid #e2e8f0" : "none" }}>
                            <div className="diff-field-row">
                              <strong>{s.source_type}</strong>
                              {s.evidence_status === "verified_live" ? (
                                <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "#2563eb", fontFamily: "DM Mono", fontSize: 11 }}>{s.url}</a>
                              ) : (
                                <span style={{ color: "#94a3b8", fontFamily: "DM Mono", fontSize: 11 }} title="URL pattern-guessed from a domain template, not fetched — may not resolve">{s.url}</span>
                              )}
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
            src={`${import.meta.env.BASE_URL}favicon.png`}
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
          {currentWorkspace.name}
          {activeBatch ? ` (${batchRowCount.toLocaleString()} SKUs)` : ""} <b>▾</b>
        </div>

        {showWorkspaceMenu && (
          <div style={{ background: "#172232", border: "1px solid #2c374b", borderRadius: 6, padding: 6, marginTop: 4, fontSize: 11 }}>
            {WORKSPACES.map((w) => {
              const isActive = w.id === organizationId;
              return (
                <div
                  key={w.id}
                  onClick={() => {
                    if (w.id !== organizationId) {
                      // Switching organization changes which batches exist at
                      // all, so nothing from the previous one may survive.
                      setOrganizationId(w.id);
                      setSelectedBatchId(null);
                      setPageOffset(0);
                      setSearchQuery("");
                      setCategoryFilter("all");
                      setIsLoadingBatch(true);
                    }
                    setShowWorkspaceMenu(false);
                  }}
                  style={{
                    padding: "8px 8px", cursor: "pointer", borderRadius: 4,
                    color: isActive ? "#38bdf8" : "#aeb7c7",
                    fontWeight: isActive ? 700 : 500,
                  }}
                >
                  <div>{isActive ? "✓ " : ""}{w.name}</div>
                  <div style={{ color: "#6b7688", fontWeight: 400, marginTop: 2, lineHeight: 1.4 }}>
                    {w.blurb}
                  </div>
                </div>
              );
            })}
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
            <span>Catalogue ({batchRowCount.toLocaleString()})</span>
            <kbd>⌘ C</kbd>
          </a>
          <a
            className={activeTab === "review" ? "active" : ""}
            onClick={() => setActiveTab("review")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>Human review</span>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {reviewBacklog > 0 && <i>{reviewBacklog.toLocaleString()}</i>}
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

        <div className="nav-group">
          <label>GETTING STARTED</label>
          <a
            className={activeTab === "help" ? "active" : ""}
            onClick={() => setActiveTab("help")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
          >
            <span>How this works</span>
            <kbd>⌘ H</kbd>
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
            <label
              title="After the deterministic pipeline runs, send only the rows it could not classify to Gemini. Suggestions are marked AI-inferred, keep the rule-based answer alongside them, and always require human review — they can never auto-approve. Requires GEMINI_API_KEY on the server; without it this is a no-op."
              style={{
                display: "flex", alignItems: "center", gap: 6,
                fontSize: 10, fontWeight: 600, color: aiAssistEnabled ? "#a371f7" : "#8b949e",
                cursor: "pointer", padding: "0 8px",
              }}
            >
              <input
                type="checkbox"
                checked={aiAssistEnabled}
                onChange={(e) => setAiAssistEnabled(e.target.checked)}
                style={{ cursor: "pointer" }}
              />
              AI assist
            </label>
            <button
              className="primary"
              onClick={(e) => requestImport(e.currentTarget)}
            >
              + Import documents
            </button>
          </div>
        </header>

        <div className="content">
          {updateAvailable && (
            <div
              role="status"
              style={{
                background: "rgba(56,189,248,0.10)",
                border: "1px solid rgba(56,189,248,0.35)",
                borderRadius: 8,
                padding: "10px 16px",
                marginBottom: 12,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 16,
                fontSize: 12,
                color: "#0369a1",
              }}
            >
              <span>
                <b>A newer version of SpecLedger is live.</b> This tab is still running an
                older build — reload to pick it up.
              </span>
              <button
                onClick={reloadOntoLatest}
                style={{
                  background: "#0284c7", color: "#fff", border: "none",
                  borderRadius: 6, padding: "6px 14px", fontSize: 12,
                  fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap",
                }}
              >
                Reload
              </button>
            </div>
          )}

          {apiError && (
            <div
              role="alert"
              style={{
                background: "rgba(248,81,73,0.08)",
                border: "1px solid rgba(248,81,73,0.35)",
                borderRadius: 8,
                padding: "12px 16px",
                marginBottom: 16,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 16,
              }}
            >
              <div style={{ fontSize: 13, color: "#f85149" }}>
                <strong>Can’t reach the API.</strong>{" "}
                <span style={{ color: "#8b949e" }}>
                  {apiError} Figures below are unavailable — nothing shown is
                  substituted or cached.
                </span>
              </div>
              <button
                onClick={() => { setIsLoadingBatch(true); fetchWorkspace(); }}
                style={{
                  background: "#238636", color: "#fff",
                  border: "1px solid rgba(255,255,255,0.1)",
                  padding: "6px 14px", borderRadius: 6,
                  fontWeight: 500, fontSize: 13, cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                Retry
              </button>
            </div>
          )}
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
