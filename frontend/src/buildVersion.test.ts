import { afterEach, describe, expect, it, vi } from "vitest";
import { bundleFromHtml, entryBundleFrom, isSupersededBuild } from "./buildVersion";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function servesHtmlNaming(name: string, ok = true) {
  return vi.fn(async () => ({
    ok,
    text: async () =>
      `<!doctype html><script type="module" src="/specledger/assets/${name}"></script>`,
  }));
}

describe("entryBundleFrom", () => {
  it("picks the fingerprinted entry bundle out of the page's scripts", () => {
    expect(entryBundleFrom([
      "https://cdn.example/vendor.js",
      "https://yashasm18.github.io/specledger/assets/index-ABC123.js",
    ])).toBe("index-ABC123.js");
  });

  it("is null under the dev server, which serves unhashed source", () => {
    expect(entryBundleFrom(["/src/main.tsx"])).toBeNull();
  });

  it("reads the bundle out of served HTML", () => {
    expect(bundleFromHtml('<script src="/specledger/assets/index-Z9.js"></script>'))
      .toBe("index-Z9.js");
  });
});

describe("isSupersededBuild", () => {
  it("is true when the host serves a different bundle than this page runs", async () => {
    vi.stubGlobal("fetch", servesHtmlNaming("index-NEW222.js"));
    await expect(isSupersededBuild(undefined, "index-OLD111.js")).resolves.toBe(true);
  });

  it("is false when they match", async () => {
    vi.stubGlobal("fetch", servesHtmlNaming("index-SAME99.js"));
    await expect(isSupersededBuild(undefined, "index-SAME99.js")).resolves.toBe(false);
  });

  it("is false when the check fails, so a flaky network never nags", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    await expect(isSupersededBuild(undefined, "index-OLD111.js")).resolves.toBe(false);
  });

  it("is false on a non-OK response rather than assuming staleness", async () => {
    vi.stubGlobal("fetch", servesHtmlNaming("index-NEW222.js", false));
    await expect(isSupersededBuild(undefined, "index-OLD111.js")).resolves.toBe(false);
  });

  it("is false under the dev server, without fetching at all", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await expect(isSupersededBuild(undefined, null)).resolves.toBe(false);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("defeats an intermediary that ignores no-store, via a unique query", async () => {
    const spy = servesHtmlNaming("index-NEW222.js");
    vi.stubGlobal("fetch", spy);
    await isSupersededBuild(undefined, "index-OLD111.js");
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/_v=\d+/);
    expect(init.cache).toBe("no-store");
  });
});
