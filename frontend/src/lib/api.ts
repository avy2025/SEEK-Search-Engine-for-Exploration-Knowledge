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

export interface LiveSearchResult {
  title: string;
  url: string;
  domain: string;
  snippet: string;
  score: number | null;
  favicon: string | null;
}

export interface LiveSearchUsage {
  month: string;
  monthly_allowance: number;
  credits_consumed: number;
  credits_remaining: number;
  successful_searches: number;
  failed_searches: number;
  last_successful_search_at: string | null;
  provider_configured?: boolean;
}

export interface LiveSearchResponse {
  mode: 'live';
  query: string;
  total: number;
  results: LiveSearchResult[];
  took_ms: number;
  cached: boolean;
  searched_at: string;
  usage: LiveSearchUsage;
  message: string;
}

export interface AIAnswerSource {
  id: number;
  title: string;
  url: string;
  domain: string;
  content: string;
}

export interface AIAnswerUsage {
  day: string;
  daily_limit: number;
  requests_used: number;
  requests_remaining: number;
  failed_requests: number;
  quota_exhausted: boolean;
  last_successful_request_at: string | null;
  gemini_configured?: boolean;
  tavily_configured?: boolean;
}

export interface AIAnswerResponse {
  mode: 'ai';
  query: string;
  answer: string;
  sources: AIAnswerSource[];
  model: string;
  provider: 'gemini';
  cached: boolean;
  searched_at: string;
  took_ms: number;
  usage: AIAnswerUsage;
  message: string;
}

export interface LiveSearchOptions {
  include_domains?: string[];
  exclude_domains?: string[];
}

export class LiveSearchError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status = 0) {
    super(message);
    this.name = 'LiveSearchError';
    this.code = code;
    this.status = status;
  }
}

export class AIAnswerError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status = 0) {
    super(message);
    this.name = 'AIAnswerError';
    this.code = code;
    this.status = status;
  }
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

export interface CrawlJobSummary {
  job_id: string;
  status: string;
  pages_crawled: number;
}

export interface CrawlJobsResponse {
  jobs: CrawlJobSummary[];
  total_jobs: number;
  crawled_documents: number;
}

export interface CrawlRequest {
  urls: string[];
  max_pages: number;
  max_depth: number;
  respect_robots: boolean;
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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, init);
  } catch {
    try {
      response = await fetch(path, init);
    } catch {
      throw new Error(`Could not connect to the SEEK backend for ${path}.`);
    }
  }

  if (!response.ok) {
    let detail = '';
    try {
      const body = (await response.json()) as { detail?: unknown; message?: unknown };
      const value = body.detail ?? body.message;
      if (typeof value === 'string') detail = `: ${value}`;
    } catch {
      // The response may not contain JSON; the HTTP status is still actionable.
    }
    throw new Error(`Request to ${path} failed with status ${response.status}${detail}`);
  }
  return (await response.json()) as T;
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

export function fetchCrawlJobs(): Promise<CrawlJobsResponse> {
  return requestJson<CrawlJobsResponse>('/api/crawl');
}

export function startCrawl(request: CrawlRequest): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/crawl', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

export function fetchIndexStatus(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/index/status');
}

export function refreshIndex(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/index/refresh', { method: 'POST' });
}

export function rebuildIndex(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/index/rebuild', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ include_crawled: true }),
  });
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

export async function liveSearch(
  query: string,
  options: LiveSearchOptions = {},
): Promise<LiveSearchResponse> {
  let response: Response;
  const body = JSON.stringify({
    query,
    include_domains: options.include_domains ?? [],
    exclude_domains: options.exclude_domains ?? [],
  });
  const init: RequestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  };
  try {
    response = await fetch(`${apiBaseUrl}/api/live-search`, init);
  } catch {
    try {
      response = await fetch('/api/live-search', init);
    } catch {
      throw new LiveSearchError(
        'backend_unavailable',
        'Could not connect to the SEEK backend.',
      );
    }
  }

  if (!response.ok) {
    let code = 'tavily_unavailable';
    let message = `Live search failed with status ${response.status}.`;
    try {
      const body = (await response.json()) as {
        detail?: { code?: unknown; message?: unknown } | string;
      };
      if (body.detail && typeof body.detail === 'object') {
        if (typeof body.detail.code === 'string') code = body.detail.code;
        if (typeof body.detail.message === 'string') message = body.detail.message;
      } else if (typeof body.detail === 'string') {
        message = body.detail;
      }
    } catch {
      // Keep the status-based message if the backend did not return JSON.
    }
    if (response.status === 422 && code === 'tavily_unavailable') {
      code = 'invalid_query';
      message = 'Check the query and domain filters; queries must be 1–500 characters.';
    }
    throw new LiveSearchError(code, message, response.status);
  }
  return (await response.json()) as LiveSearchResponse;
}

export function fetchLiveSearchUsage(): Promise<LiveSearchUsage> {
  return requestJson<LiveSearchUsage>('/api/live-search/usage');
}

export async function aiAnswer(query: string): Promise<AIAnswerResponse> {
  const init: RequestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  };
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/ai-answer`, init);
  } catch {
    try {
      response = await fetch('/api/ai-answer', init);
    } catch {
      throw new AIAnswerError('backend_unavailable', 'Could not connect to the SEEK backend.');
    }
  }

  if (!response.ok) {
    let code = 'gemini_unavailable';
    let message = `AI Answers failed with status ${response.status}.`;
    try {
      const body = (await response.json()) as {
        detail?: { code?: unknown; message?: unknown } | string;
      };
      if (body.detail && typeof body.detail === 'object') {
        if (typeof body.detail.code === 'string') code = body.detail.code;
        if (typeof body.detail.message === 'string') message = body.detail.message;
      } else if (typeof body.detail === 'string') {
        message = body.detail;
      }
    } catch {
      // Keep the status-based message if the backend did not return JSON.
    }
    if (response.status === 422 && code === 'gemini_unavailable') {
      code = 'invalid_query';
      message = 'Enter a question between 1 and 500 characters.';
    }
    throw new AIAnswerError(code, message, response.status);
  }
  return (await response.json()) as AIAnswerResponse;
}

export function fetchAIAnswerUsage(): Promise<AIAnswerUsage> {
  return requestJson<AIAnswerUsage>('/api/ai-answer/usage');
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