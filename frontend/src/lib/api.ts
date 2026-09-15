/* Single API client for the SEEK frontend (Phase 3).
 *
 * The backend stays the single source of truth for query processing, BM25
 * ranking and retrieval; this module only performs requests and shapes the
 * responses. The base URL is configurable through VITE_API_BASE_URL and falls
 * back to a same-origin proxy so the same bundle works with CORS (local dev)
 * and the Nginx reverse proxy (Docker).
 */

export interface HealthStatus {
  status: string;
  service: string;
}

export interface SearchHit {
  rank: number;
  document_id: string;
  title: string;
  source: string;
  snippet: string;
  score: number;
  matched_terms: string[];
}

export interface SearchResponse {
  query: string;
  total: number;
  limit: number;
  hits: SearchHit[];
  took_ms: number;
  message: string;
}

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

function resolveBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (configured && configured.trim()) {
    return configured.trim().replace(/\/+$/, '');
  }
  return DEFAULT_API_BASE_URL;
}

export const apiBaseUrl = resolveBaseUrl();

async function probe(base: string, path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${base}${path}`, init);
  if (!res.ok) {
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
  return res;
}

export async function fetchHealth(): Promise<HealthStatus> {
  try {
    const res = await probe(apiBaseUrl, '/health', { method: 'GET' });
    return (await res.json()) as HealthStatus;
  } catch {
    // Same-origin fallback so a reverse proxy (Docker) can serve health too.
    const res = await probe('', '/api/health', { method: 'GET' });
    return (await res.json()) as HealthStatus;
  }
}

export async function search(query: string, limit = 10): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const path = `/api/search?${params.toString()}`;
  try {
    const res = await probe(apiBaseUrl, path, { method: 'GET' });
    return (await res.json()) as SearchResponse;
  } catch {
    const res = await probe('', path, { method: 'GET' });
    return (await res.json()) as SearchResponse;
  }
}

// --------------------------------------------------------------------------- //
// Small UI helpers derived purely from backend fields (no new API surface).
// --------------------------------------------------------------------------- //

export interface SourceParts {
  domain: string;
  rest: string;
  pathOnly: boolean;
}

/** Split a backend ``source`` into a displayable host + remainder. Corpus docs
 * carry file paths; crawled docs carry URLs - both must render without breaking
 * the layout. */
export function splitSource(source: string): SourceParts {
  try {
    const url = new URL(source);
    let rest = url.pathname;
    if (url.search) rest += url.search;
    return { domain: url.hostname, rest, pathOnly: false };
  } catch {
    return { domain: '', rest: source, pathOnly: true };
  }
}