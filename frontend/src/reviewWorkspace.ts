import { getApiBaseUrl, getApiKeyHeaders } from "./apiClient";

type Fact = { name: string; value: string; normalized_value?: string; normalized_unit?: string; page: number; confidence: number; evidence: string };
type ReviewArtifact = {
  artifact_id?: string;
  document_id?: string;
  batch_id?: string;
  row_number?: number;
  sku?: string;
  description?: string;
  data?: { facts?: Fact[]; pages?: { page: number; text: string }[] };
  review_state?: string;
  onReviewSubmit?: (action: "approve" | "reject" | "correct", comment?: string) => Promise<void>;
};

const API_BASE = getApiBaseUrl();

export function openReviewWorkspace(artifact: ReviewArtifact) {
  document.getElementById("review-workspace")?.remove();
  const panel = document.createElement("section");
  panel.id = "review-workspace";
  const facts = artifact.data?.facts || [];
  const headerSub = artifact.sku ? `SKU: ${artifact.sku} · ${artifact.description || ""}` : "Every value remains linked to its source before publication.";
  
  panel.innerHTML = `<div class="review-header"><div><span class="review-eyebrow">EVIDENCE REVIEW WORKSPACE</span><h2>Verify extracted product intelligence</h2><p>${headerSub}</p></div><button class="review-close" aria-label="Close review workspace">×</button></div><div class="review-body"><div class="review-summary"><span><b>${facts.length}</b> extracted facts</span><span class="pending">● ${artifact.review_state || "pending_review"}</span><span>Evidence-backed</span></div><div class="fact-list">${facts.length ? facts.map((fact) => `<article class="fact-card"><div class="fact-title"><strong>${fact.name.replace(/_/g, " ")}</strong><mark>${Math.round(fact.confidence * 100)}% confidence</mark></div><div class="fact-values"><b>${fact.value}</b><span>${fact.normalized_value || "—"} ${fact.normalized_unit || ""}</span></div><p>“${fact.evidence}”</p><button class="evidence-link">↳ Source evidence</button></article>`).join("") : `<div class="empty-review">No structured facts were found. The source document remains available for manual review.</div>`}</div></div><div class="review-footer"><span>Nothing is published automatically.</span><button class="review-reject">Reject</button><button class="review-approve">Approve artifact</button></div>`;
  
  document.body.appendChild(panel);
  panel.querySelector(".review-close")?.addEventListener("click", () => panel.remove());

  panel.querySelectorAll<HTMLButtonElement>(".evidence-link").forEach((button, index) => {
    button.addEventListener("click", () => {
      const fact = facts[index];
      const pageText = artifact.data?.pages?.find((page) => page.page === fact.page)?.text;
      const detail = document.createElement("div");
      detail.className = "review-evidence-detail";
      detail.innerHTML = `<div><strong>Source Evidence · ${fact.name}</strong><button aria-label="Close evidence">×</button></div><p>${pageText || fact.evidence}</p>`;
      detail.querySelector("button")?.addEventListener("click", () => detail.remove());
      panel.querySelector(".review-body")?.prepend(detail);
    });
  });

  const submitDecision = async (reviewState: "approved" | "rejected") => {
    if (artifact.onReviewSubmit) {
      try {
        await artifact.onReviewSubmit(reviewState === "approved" ? "approve" : "reject", `Artifact ${reviewState} from review workspace`);
        const status = panel.querySelector(".review-summary .pending");
        if (status) status.textContent = `● ${reviewState}`;
        panel.querySelectorAll<HTMLButtonElement>(".review-approve, .review-reject").forEach((button) => {
          button.disabled = true;
          button.textContent = reviewState === "approved" ? "Approved" : "Rejected";
        });
      } catch (err) {
        window.alert(`Review submission failed: ${err instanceof Error ? err.message : String(err)}`);
      }
      return;
    }

    if (artifact.batch_id && artifact.row_number) {
      try {
        const response = await fetch(
          `${API_BASE}/catalogue/batches/${artifact.batch_id}/rows/${artifact.row_number}/review`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", ...getApiKeyHeaders() },
            body: JSON.stringify({ action: reviewState === "approved" ? "approve" : "reject", reviewer: import.meta.env.VITE_REVIEWER_NAME || "Yashas M", comment: `Row ${reviewState} in workspace` }),
          }
        );
        if (!response.ok) {
          const failure = await response.json().catch(() => ({}));
          throw new Error(failure.detail || "Unable to save review decision.");
        }
        const status = panel.querySelector(".review-summary .pending");
        if (status) status.textContent = `● ${reviewState}`;
        panel.querySelectorAll<HTMLButtonElement>(".review-approve, .review-reject").forEach((button) => {
          button.disabled = true;
          button.textContent = reviewState === "approved" ? "Approved" : "Rejected";
        });
      } catch (err) {
        window.alert(`Review submission failed: ${err instanceof Error ? err.message : String(err)}`);
      }
      return;
    }

    if (!artifact.document_id || !artifact.artifact_id) {
      window.alert("This review record is missing its document identity. Please upload the document again.");
      return;
    }
    const response = await fetch(
      `${API_BASE}/documents/${artifact.document_id}/artifact/${artifact.artifact_id}/review?organization_id=default`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...getApiKeyHeaders() },
        body: JSON.stringify({ review_state: reviewState, actor_id: "yashas", comment: `Artifact ${reviewState} from review workspace` }),
      },
    );
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      window.alert(failure.detail || "Unable to save the review decision.");
      return;
    }
    const status = panel.querySelector(".review-summary .pending");
    if (status) status.textContent = `● ${reviewState}`;
    panel.querySelectorAll<HTMLButtonElement>(".review-approve, .review-reject").forEach((button) => {
      button.disabled = true;
      button.textContent = reviewState === "approved" ? "Approved" : "Rejected";
    });
  };
  panel.querySelector(".review-approve")?.addEventListener("click", () => void submitDecision("approved"));
  panel.querySelector(".review-reject")?.addEventListener("click", () => void submitDecision("rejected"));
}

// Bridge the existing task poller to the review surface without duplicating polling logic.
const nativeFetch = window.fetch.bind(window);
const openedTasks = new Set<string>();
window.fetch = async (...args: Parameters<typeof window.fetch>) => {
  const response = await nativeFetch(...args);
  const requestUrl = typeof args[0] === "string" ? args[0] : args[0] instanceof Request ? args[0].url : "";
  if (requestUrl.includes("/documents/tasks/") && response.ok) {
    const status = await response.clone().json().catch(() => null);
    if (status?.state === "completed" && status.document_id && !openedTasks.has(status.task_id)) {
      openedTasks.add(status.task_id);
      const artifactRequest = status.artifact ? Promise.resolve(status.artifact) : nativeFetch(`${API_BASE}/documents/${status.document_id}/artifact?organization_id=default`).then((artifactResponse) => artifactResponse.json());
      artifactRequest.then((artifact) => {
        openReviewWorkspace(artifact);
        document.getElementById("review-launcher")?.remove();
        const launcher = document.createElement("button");
        launcher.id = "review-launcher";
        launcher.textContent = "Open evidence review →";
        launcher.setAttribute("aria-label", "Open evidence review workspace");
        launcher.onclick = () => { openReviewWorkspace(artifact); launcher.remove(); };
        document.body.appendChild(launcher);
      }).catch(() => {
        const launcher = document.createElement("button");
        launcher.id = "review-launcher";
        launcher.textContent = "Open evidence review →";
        launcher.onclick = () => launcher.remove();
        document.body.appendChild(launcher);
      });
    }
  }
  return response;
};


// Review opens from the upload task completion bridge above. Do not poll and
// auto-open the latest artifact on page load; that would interrupt users on
// every refresh and make an old review appear unexpectedly.
