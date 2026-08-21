import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithRetry, resolveApiBaseUrl } from "./apiClient";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

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

describe("fetchWithRetry", () => {
  const noSleep = async () => {};
  const response = (status: number) =>
    new Response(status === 200 ? '{"ok":true}' : "", { status });

  it("retries a 502 and returns the response once the backend recovers", async () => {
    // The backend restarting behind the edge: 502 until the app is listening.
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(502))
      .mockResolvedValueOnce(response(502))
      .mockResolvedValueOnce(response(200));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("http://api.test/x", undefined, 5, noSleep);

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("retries a connection failure, which is how a cold start surfaces", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(response(200));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("http://api.test/x", undefined, 5, noSleep);

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry a 404, which is a real answer from the application", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(404));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("http://api.test/x", undefined, 5, noSleep);

    expect(res.status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("throws after exhausting attempts so callers can show a real outage", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchWithRetry("http://api.test/x", undefined, 3, noSleep),
    ).rejects.toThrow("Failed to fetch");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
