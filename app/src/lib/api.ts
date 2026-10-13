export interface HealthResponse {
  status: string;
  version: string;
}

export interface ClientConfig {
  languages: { code: string; name: string; default: boolean }[];
  voices: { id: string; name: string }[];
  tts_provider: string;
}

/** Bundled fallback so Settings still works when the backend is unreachable. */
export const FALLBACK_CONFIG: ClientConfig = {
  languages: [{ code: "en", name: "English", default: true }],
  voices: [],
  tts_provider: "",
};

function join(base: string, path: string): string {
  return base.replace(/\/+$/, "") + path;
}

async function getJson<T>(baseUrl: string, path: string, timeoutMs = 4000): Promise<T> {
  const res = await fetch(join(baseUrl, path), { signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const fetchHealth = (baseUrl: string) => getJson<HealthResponse>(baseUrl, "/health");
export const fetchClientConfig = (baseUrl: string) => getJson<ClientConfig>(baseUrl, "/v1/config");
