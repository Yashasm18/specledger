import { apiFetch, readApiError } from "./apiClient";

export async function fetchCatalogueExport(batchId: string | undefined, format: string): Promise<Blob> {
  if (!batchId) {
    throw new Error("No verified catalogue batch is available to export.");
  }
  const response = await apiFetch(
    `/catalogue/batches/${encodeURIComponent(batchId)}/export?format=${encodeURIComponent(format)}`,
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Export failed"));
  }
  return response.blob();
}
