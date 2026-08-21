const LOCAL_API_URL = "http://localhost:8000";

export class ApiConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiConfigurationError";
  }
}

export function resolveApiBaseUrl(configuredValue: unknown, hostname: string): string {
  const configured = String(configuredValue || "").trim().replace(/\/$/, "");
  if (configured) return configured;

  if (["localhost", "127.0.0.1"].includes(hostname)) {
    return LOCAL_API_URL;
  }

  return "";
}

export function getApiBaseUrl(): string {
  return resolveApiBaseUrl(
    import.meta.env.VITE_API_URL,
    typeof window !== "undefined" ? window.location.hostname : "",
  );
}

export function requireApiBaseUrl(): string {
  const baseUrl = getApiBaseUrl();
  if (!baseUrl) {
    throw new ApiConfigurationError(
      "The production API is not configured. Set VITE_API_URL to the deployed SpecLedger FastAPI URL.",
    );
  }
  return baseUrl;
}

export function getApiKeyHeaders(): Record<string, string> {
  const apiKey = String(import.meta.env.VITE_API_KEY || "").trim();
  return apiKey ? { "X-API-Key": apiKey } : {};
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${requireApiBaseUrl()}${path}`, {
    ...init,
    headers: { ...getApiKeyHeaders(), ...(init?.headers || {}) },
  });
  return response;
}

/**
 * Fetch that rides out a backend restart or cold start.
 *
 * The API runs on a platform that replaces the container on deploy and can
 * cold-start after idling, so the first request after either event may fail
 * outright or get a 502/503 from the edge before the app is listening. The
 * browser reports those as opaque network/CORS errors, because an
 * edge-level failure carries no CORS headers — which previously left the
 * dashboard looking permanently empty after a single failed attempt.
 *
 * Retries only what is actually transient: connection failures and 5xx. A
 * 4xx is a real answer from the application and is returned as-is.
 *
 * Default timing is 0.8s, 1.6s, 3.2s, 6.4s between five attempts (~12s
 * total), which comfortably covers an observed cold start.
 */
export async function fetchWithRetry(
  url: string,
  init?: RequestInit,
  attempts = 5,
  sleep: (ms: number) => Promise<void> = (ms) =>
    new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      const response = await fetch(url, init);
      if (response.status >= 500) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response;
    } catch (error) {
      lastError = error;
      if (attempt < attempts - 1) {
        await sleep(800 * 2 ** attempt);
      }
    }
  }
  throw lastError;
}

export async function readApiError(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (payload && typeof payload.detail === "string") return payload.detail;
  return `${fallback} (${response.status})`;
}
