import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "./apiClient";

describe("resolveApiBaseUrl", () => {
  it("uses the configured production API and removes a trailing slash", () => {
    expect(resolveApiBaseUrl("https://api.specledger.example/", "specledger-app.vercel.app"))
      .toBe("https://api.specledger.example");
  });

  it("uses the local FastAPI service during local development", () => {
    expect(resolveApiBaseUrl(undefined, "localhost")).toBe("http://localhost:8000");
  });

  it("does not silently use the frontend origin in production", () => {
    expect(resolveApiBaseUrl(undefined, "specledger-app.vercel.app")).toBe("");
  });
});
