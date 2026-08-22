/**
 * Detecting that the page is running a superseded build.
 *
 * GitHub Pages serves index.html with a short max-age and gives no way to
 * change it, so after a deploy a browser can keep the previous HTML — which
 * names the previous hashed bundle. The old bundle is still on the host, so
 * nothing errors: the app simply runs old code and the deploy looks like it
 * silently failed.
 *
 * Rather than fight the cache, notice it. Vite fingerprints the entry bundle,
 * so the filename in a freshly fetched index.html is a build identifier that
 * needs no extra file or build step: if it differs from the one this page
 * loaded, a newer build is live.
 */

const ENTRY_PATTERN = /assets\/(index-[A-Za-z0-9_.-]+\.js)/;

/** The fingerprinted entry bundle named by any of `sources`, or null.
 *  Null under the dev server, which serves unhashed module source and so has
 *  no build identity to compare. */
export function entryBundleFrom(sources: Iterable<string>): string | null {
  for (const src of sources) {
    const match = src.match(ENTRY_PATTERN);
    if (match) return match[1];
  }
  return null;
}

/** The entry bundle in a page of HTML. */
export function bundleFromHtml(html: string): string | null {
  return entryBundleFrom([html]);
}

/** The entry bundle this page is running. */
export function runningBundle(): string | null {
  return entryBundleFrom(
    Array.from(document.querySelectorAll<HTMLScriptElement>("script[src]"), (s) => s.src),
  );
}

/** The entry bundle the host is serving right now. */
export async function deployedBundle(signal?: AbortSignal): Promise<string | null> {
  const base = import.meta.env.BASE_URL || "/";
  // cache:"no-store" plus a unique query, because an intermediary that
  // ignores the header would otherwise hand back the copy being tested for.
  const res = await fetch(`${base}?_v=${Date.now()}`, { cache: "no-store", signal });
  if (!res.ok) return null;
  return bundleFromHtml(await res.text());
}

/** Whether a newer build is live.
 *
 *  False whenever it cannot be established — a failed check must never nag
 *  someone to reload for no reason. `running` is injectable so the decision
 *  can be tested without a DOM.
 */
export async function isSupersededBuild(
  signal?: AbortSignal,
  running: string | null = runningBundle(),
): Promise<boolean> {
  if (!running) return false;
  try {
    const deployed = await deployedBundle(signal);
    return Boolean(deployed) && deployed !== running;
  } catch {
    return false;
  }
}

/** Reload onto the current build, bypassing the cached HTML.
 *  location.reload() may revalidate against the same stale copy, so this
 *  navigates with a unique query instead; the marker is stripped on arrival
 *  by clearReloadMarker(). */
export function reloadOntoLatest(): void {
  const url = new URL(window.location.href);
  url.searchParams.set("_v", String(Date.now()));
  window.location.replace(url.toString());
}

/** Remove the cache-busting marker from the address bar after the reload. */
export function clearReloadMarker(): void {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("_v")) return;
  url.searchParams.delete("_v");
  window.history.replaceState({}, "", url.pathname + url.search + url.hash);
}
