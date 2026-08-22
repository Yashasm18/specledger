import { apiFetch, readApiError } from "./apiClient";

export async function fetchCatalogueExport(
  batchId: string | undefined,
  format: string,
  organizationId = "default",
): Promise<Blob> {
  if (!batchId) {
    throw new Error("No verified catalogue batch is available to export.");
  }
  // Scoped to the workspace, like every other read — an export that ignored
  // it would resolve a batch id against the wrong organization.
  const response = await apiFetch(
    `/catalogue/batches/${encodeURIComponent(batchId)}/export`
      + `?format=${encodeURIComponent(format)}`
      + `&organization_id=${encodeURIComponent(organizationId)}`,
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Export failed"));
  }
  return response.blob();
}
