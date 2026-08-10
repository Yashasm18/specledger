type Fact = { name: string; value: string; normalized_value?: string; normalized_unit?: string; page: number; confidence: number; evidence: string };

export function openReviewWorkspace(artifact: { data?: { facts?: Fact[]; pages?: { page: number; text: string }[] }; review_state?: string }) {
  document.getElementById("review-workspace")?.remove();
  const panel = document.createElement("section");
  panel.id = "review-workspace";
  const facts = artifact.data?.facts || [];
  panel.innerHTML = `<div class="review-header"><div><span class="review-eyebrow">EVIDENCE REVIEW WORKSPACE</span><h2>Verify extracted product intelligence</h2><p>Every value remains linked to its source before publication.</p></div><button class="review-close" aria-label="Close review workspace">×</button></div><div class="review-body"><div class="review-summary"><span><b>${facts.length}</b> extracted facts</span><span class="pending">● ${artifact.review_state || "pending_review"}</span><span>Evidence-backed</span></div><div class="fact-list">${facts.length ? facts.map((fact) => `<article class="fact-card"><div class="fact-title"><strong>${fact.name.replaceAll("_", " ")}</strong><mark>${Math.round(fact.confidence * 100)}% confidence</mark></div><div class="fact-values"><b>${fact.value}</b><span>${fact.normalized_value || "—"} ${fact.normalized_unit || ""}</span></div><p>“${fact.evidence}”</p><button class="evidence-link">↳ Page ${fact.page} evidence</button></article>`).join("") : `<div class="empty-review">No structured facts were found. The source document remains available for manual review.</div>`}</div></div><div class="review-footer"><span>Nothing is published automatically.</span><button class="review-reject">Reject</button><button class="review-approve">Approve artifact</button></div>`;
  document.body.appendChild(panel);
  panel.querySelector(".review-close")?.addEventListener("click", () => panel.remove());
}
