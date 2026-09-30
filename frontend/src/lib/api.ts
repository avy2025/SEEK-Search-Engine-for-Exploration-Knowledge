/* Single API client for the SEEK frontend (Phases 3 & 9).
 *
 * The backend stays the single source of truth for query processing, BM25 /
 * semantic / hybrid ranking, mode orchestration and RAG answer generation; this
 * module only performs requests and shapes the responses. The base URL is
 * configurable through VITE_API_BASE_URL and falls back to a same-origin proxy
 * so the same bundle works with CORS (local dev) and the Nginx reverse proxy
 * (Docker).
 */

import { DEFAULT_SEARCH_MODE, type SearchMode } from './modes';

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
  /** Phase 9 `code` mode only: excerpt extracted from the indexed document. */
  code_snippet?: string | null;
}

export interface SearchResponse {
  query: string;
  total: number;
  limit: number;
  hits: SearchHit[];
  took_ms: number;
  message: string;
  /** Legacy retrieval modes echo their retrieval mode. */
  mode?: string;
  /** Phase 9 specialized modes report an explicit health status. */
  status?: string;
  /** Phase 9 specialized modes: grounded answer, `null` when none was produced. */
  answer?: string | null;
  sources?: ModeSource[];
  metadata?: Record<string, unknown>;
}

export interface ModeSource {
  document_id: string;
  title: string;
  source: string;
  domain: string;
  rank: number;
  score: number;
  citation_id?: number | null;
}

/** Envelope returned for `web | ai | research | code` search modes. */
export interface ModeSearchResponse extends SearchResponse {
  mode: SearchMode;
  status: string;
  answer: string | null;
  sources: ModeSource[];
  metadata: Record<string, unknown>;
}

export type LegacySearchMode = 'lexical' | 'bm25' | 'semantic' | 'hybrid';

export interface SearchOptions {
  limit?: number;
  /** Phase 9 specialized mode (`web | ai | research | code`). */
  mode?: SearchMode;
  /** Pre-Phase-9 retrieval mode; kept for advanced/debug use. */
  legacyMode?: LegacySearchMode;
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

export async function search(
  query: string,
  options: SearchOptions = {},
): Promise<SearchResponse> {
  const mode = options.mode ?? DEFAULT_SEARCH_MODE;
  const params = new URLSearchParams({ q: query, mode });
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  else if (options.legacyMode) params.set('mode', options.legacyMode);
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

/** Narrow a search response to the Phase 9 specialized-mode envelope. */
export function asModeResponse(response: SearchResponse): ModeSearchResponse | null {
  const mode = response.mode;
  if (!mode || !['web', 'ai', 'research', 'code'].includes(mode)) return null;
  return {
    ...response,
    mode: mode as SearchMode,
    status: response.status ?? 'ok',
    answer: response.answer ?? null,
    sources: response.sources ?? [],
    metadata: response.metadata ?? {},
  };
}

/** Read a nested metadata value without pretending it always exists. */
export function metaValue(
  metadata: Record<string, unknown> | undefined,
  path: string,
): unknown {
  if (!metadata) return undefined;
  return path.split('.').reduce<unknown>((acc, key) => {
    if (acc && typeof acc === 'object') {
      return (acc as Record<string, unknown>)[key];
    }
    return undefined;
  }, metadata);
}