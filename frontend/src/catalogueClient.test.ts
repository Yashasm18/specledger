import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCatalogueExport } from "./catalogueClient";

afterEach(() => vi.unstubAllGlobals());

describe("fetchCatalogueExport", () => {
  it("refuses to export demo rows without a persisted batch", async () => {
    await expect(fetchCatalogueExport(undefined, "unilog_template"))
      .rejects.toThrow("No verified catalogue batch");
  });

  it("surfaces API failures instead of fabricating a client-side export", async () => {
    vi.stubGlobal("window", { location: { hostname: "localhost" } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Batch not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    await expect(fetchCatalogueExport("missing", "audit")).rejects.toThrow("Batch not found");
  });

  it("returns the backend export when the request succeeds", async () => {
    vi.stubGlobal("window", { location: { hostname: "localhost" } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("sku,description", { status: 200 })));
    const blob = await fetchCatalogueExport("batch-1", "csv");
    expect(await blob.text()).toBe("sku,description");
  });
});
