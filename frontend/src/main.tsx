import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  return <main className="shell">
    <nav><div className="brand"><span>SL</span> SpecLedger</div><div className="nav-status">● PostgreSQL connected</div></nav>
    <section className="hero"><div><p className="eyebrow">INDUSTRIAL PRODUCT INTELLIGENCE</p><h1>Turn scattered specifications into <em>trusted catalogue data.</em></h1><p className="sub">Evidence-backed extraction, validation, and review for industrial commerce teams.</p></div><div className="score"><strong>0</strong><span>documents under review</span></div></section>
    <section className="workspace"><div className="section-head"><div><p className="eyebrow">INGESTION WORKSPACE</p><h2>Start a product evidence review</h2></div><button>+ New review</button></div>
      <div className="dropzone"><div className="upload-icon">↑</div><h3>Drop a technical PDF here</h3><p>We’ll extract facts, preserve page evidence, and flag conflicts before publication.</p><button className="primary">Choose document</button><small>PDF up to 5 MB · Human approval required</small></div>
    </section>
    <section className="cards"><article><span className="card-label">PIPELINE</span><strong>Ready for evidence</strong><p>Upload your first supplier datasheet to begin.</p></article><article><span className="card-label warning">REVIEW GATE</span><strong>Nothing auto-published</strong><p>Every inferred value stays pending review.</p></article><article><span className="card-label">SCHEMA</span><strong>Category-aware</strong><p>Valves, pumps, fittings, and generic industrial goods.</p></article></section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
