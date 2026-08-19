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

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${requireApiBaseUrl()}${path}`, init);
  return response;
}

export async function readApiError(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (payload && typeof payload.detail === "string") return payload.detail;
  return `${fallback} (${response.status})`;
}
