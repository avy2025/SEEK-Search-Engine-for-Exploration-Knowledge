import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Home, Loader2, RotateCcw, WifiOff } from 'lucide-react';
import Header from './components/Header';
import ModeSelector from './components/ModeSelector';
import SearchBar from './components/SearchBar';
import SearchResults from './components/SearchResults';
import AdminPanel from './components/AdminPanel';
import LiveSearchFilters from './components/LiveSearchFilters';
import LiveSearchResults, { LiveSearchBudget } from './components/LiveSearchResults';
import type { BackendStatus } from './components/HealthBadge';
import {
  apiBaseUrl,
  asModeResponse,
  fetchHealth,
  fetchLiveSearchUsage,
  liveSearch,
  LiveSearchError,
  search,
  type LiveSearchResponse,
  type SearchResponse,
} from './lib/api';
import { DEFAULT_SEARCH_MODE, modeLabel, type AppSearchMode } from './lib/modes';
import { buildSearchPath, parseSearchState } from './lib/urlState';

type View = 'landing' | 'loading' | 'results' | 'error';

const SAMPLE_QUERIES: Record<AppSearchMode, readonly string[]> = {
  web: ['docker container', 'machine learning', 'odoo erp', 'natural language'],
  ai: ['how does SEEK rank documents?', 'what is hybrid search?', 'why BM25?'],
  research: ['search engine ranking', 'information retrieval evaluation'],
  code: ['faiss_store.SearchEngine', 'backend/api/search.py', 'create_engine()'],
  live: ['current technology news', 'Python documentation', 'latest space discoveries'],
};

export const App: React.FC = () => {
  // The URL is the source of truth for (query, mode): it makes every view
  // deep-linkable and survives refresh / back-forward navigation.
  const initial = useRef(parseSearchState(window.location.search));
  const didInitialSearch = useRef(false);

  const [query, setQuery] = useState(initial.current.query);
  const [mode, setMode] = useState<AppSearchMode>(initial.current.mode);
  const [activeQuery, setActiveQuery] = useState(initial.current.query);
  const [view, setView] = useState<View>(initial.current.query ? 'loading' : 'landing');
  const [results, setResults] = useState<SearchResponse | LiveSearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [includeDomains, setIncludeDomains] = useState('');
  const [excludeDomains, setExcludeDomains] = useState('');
  const [liveUsage, setLiveUsage] = useState<Awaited<ReturnType<typeof fetchLiveSearchUsage>> | null>(null);
  const [liveUsageError, setLiveUsageError] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('checking');
  const [adminOpen, setAdminOpen] = useState(false);

  const refreshLiveUsage = useCallback(async () => {
    try {
      const usage = await fetchLiveSearchUsage();
      setLiveUsage(usage);
      setLiveUsageError(null);
    } catch {
      setLiveUsage(null);
      setLiveUsageError('SEEK live-search budget status is temporarily unavailable.');
    }
  }, []);

  const checkBackendHealth = useCallback(async () => {
    setBackendStatus('checking');
    try {
      await fetchHealth();
      setBackendStatus('connected');
    } catch {
      setBackendStatus('disconnected');
    }
  }, []);

  useEffect(() => {
    checkBackendHealth();
    const interval = setInterval(checkBackendHealth, 15000);
    return () => clearInterval(interval);
  }, [checkBackendHealth]);

  useEffect(() => {
    if (mode === 'live') void refreshLiveUsage();
  }, [mode, refreshLiveUsage]);

  const runSearch = useCallback(async (q: string, searchMode: AppSearchMode) => {
    setActiveQuery(q);
    setView('loading');
    setError(null);
    setErrorCode(null);
    try {
      const parseDomains = (value: string) =>
        value.split(',').map((domain) => domain.trim()).filter(Boolean);
      if (searchMode === 'live') {
        const response = await liveSearch(q, {
          include_domains: parseDomains(includeDomains),
          exclude_domains: parseDomains(excludeDomains),
        });
        setResults(response);
        setLiveUsage(response.usage);
        setLiveUsageError(null);
      } else {
        setResults(await search(q, { mode: searchMode }));
      }
      setView('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The search request failed.');
      setErrorCode(err instanceof LiveSearchError ? err.code : null);
      setView('error');
      if (searchMode === 'live') void refreshLiveUsage();
    }
  }, [excludeDomains, includeDomains, refreshLiveUsage]);

  /** Submit a query in the currently selected mode and record it in history. */
  const handleSearch = useCallback(
    (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;
      window.history.pushState({}, '', buildSearchPath({ query: trimmed, mode }));
      void runSearch(trimmed, mode);
    },
    [mode, runSearch],
  );

  /**
   * Switch mode. On the landing page this just re-selects the mode (the URL
   * remembers the choice via `?mode=…`); with an active query it re-runs the
   * search immediately so the new mode is visible straight away.
   */
  const handleModeChange = useCallback(
    (next: AppSearchMode) => {
      setMode(next);
      const active = activeQuery.trim();
      if (view === 'landing' || !active) {
        window.history.replaceState({}, '', buildSearchPath({ query: '', mode: next }));
        return;
      }
      window.history.pushState({}, '', buildSearchPath({ query: active, mode: next }));
      void runSearch(active, next);
    },
    [activeQuery, runSearch, view],
  );

  const goHome = useCallback(() => {
    setQuery('');
    setActiveQuery('');
    setResults(null);
    setError(null);
    setErrorCode(null);
    setView('landing');
    // Home keeps the selected mode in the URL so the landing page remembers it.
    window.history.pushState({}, '', buildSearchPath({ query: '', mode }));
  }, [mode]);

  // Execute a query found in the URL on first render (deep links / refresh).
  useEffect(() => {
    const { query: urlQuery, mode: urlMode } = initial.current;
    if (urlQuery && !didInitialSearch.current) {
      didInitialSearch.current = true;
      void runSearch(urlQuery, urlMode);
    }
  }, [runSearch]);

  // Honour back/forward navigation across queried states.
  useEffect(() => {
    const handlePopState = () => {
      const next = parseSearchState(window.location.search);
      setQuery(next.query);
      setMode(next.mode);
      if (next.query) {
        void runSearch(next.query, next.mode);
      } else {
        setResults(null);
        setError(null);
        setActiveQuery('');
        setView('landing');
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [runSearch]);

  // Narrow to the Phase 9 envelope when the backend reported a specialized mode.
  const localResults = results && 'hits' in results ? results : null;
  const liveResults = results && 'results' in results ? results : null;
  const modeResponse = localResults ? asModeResponse(localResults) : null;
  const liveErrorTitle: Record<string, string> = {
    invalid_query: 'Invalid live-search query',
    tavily_not_configured: 'Live Internet Search is not configured',
    tavily_authentication_error: 'Tavily authentication failed',
    tavily_rate_limited: 'Tavily rate limit exceeded',
    tavily_credits_exhausted: 'Tavily free credits are exhausted',
    seek_monthly_budget_exhausted: 'SEEK monthly live-search budget reached',
    tavily_timeout: 'Tavily search timed out',
    tavily_network_error: 'Could not connect to Tavily',
    tavily_unavailable: 'Live Internet Search is unavailable',
    provider_unavailable: 'Live Internet Search is unavailable',
    usage_store_unavailable: 'Live Internet Search is temporarily unavailable',
    backend_unavailable: 'Unable to reach the SEEK backend',
  };
  const liveControls = mode === 'live' && (
    <>
      <LiveSearchFilters
        includeDomains={includeDomains}
        excludeDomains={excludeDomains}
        onIncludeDomainsChange={setIncludeDomains}
        onExcludeDomainsChange={setExcludeDomains}
      />
      <LiveSearchBudget usage={liveUsage} error={liveUsageError} onRefresh={() => void refreshLiveUsage()} />
    </>
  );

  return (
    <div className="flex min-h-screen flex-col bg-seek-dark text-seek-ink antialiased">
      <Header backendStatus={backendStatus} onHome={goHome} />

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-5 py-8 sm:px-8">
        <div className="mb-5 flex justify-end">
          <button
            type="button"
            className="rounded-lg border border-seek-border bg-white px-3 py-2 text-sm font-medium text-gray-300 transition hover:text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
            aria-expanded={adminOpen}
            aria-controls="seek-admin-panel"
            onClick={() => setAdminOpen((open) => !open)}
          >
            {adminOpen ? 'Hide sources & indexing' : 'Manage sources & indexing'}
          </button>
        </div>
        {adminOpen && (
          <div id="seek-admin-panel">
            <AdminPanel />
          </div>
        )}
        {view === 'landing' ? (
          <section className="flex flex-1 flex-col items-center justify-center pb-16 pt-8 text-center sm:pb-24">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-seek-accent">
              Search &amp; discovery
            </p>
            <h1 className="mt-5 max-w-3xl font-serif text-4xl font-medium leading-tight tracking-tight text-seek-ink sm:text-6xl">
              Find the knowledge you need.
            </h1>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-gray-400 sm:text-lg">
              {mode === 'live'
                ? 'Search the live public web with Tavily—no crawling or indexing required.'
                : 'One thoughtful search across your sources and documents.'}
            </p>

            <div className="mt-9 flex w-full flex-col items-center gap-5">
              <SearchBar
                value={query}
                onChange={setQuery}
                loading={false}
                autoFocus
                searchLabel={mode === 'live' ? 'Search the live internet' : undefined}
                placeholder={mode === 'live' ? 'Search the live internet…' : undefined}
                onSearch={handleSearch}
              />
              <ModeSelector value={mode} onChange={handleModeChange} />
              {liveControls}
            </div>

            <nav
              className="mt-8 flex flex-wrap items-center justify-center gap-x-5 gap-y-2"
              aria-label="Sample queries"
            >
              <span className="text-sm text-gray-500">Try searching</span>
              {(SAMPLE_QUERIES[mode] ?? []).map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() => {
                    setQuery(sample);
                    handleSearch(sample);
                  }}
                  className="rounded-md px-1 py-1 text-sm text-gray-400 underline decoration-seek-border underline-offset-4 transition-colors hover:text-seek-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
                >
                  {sample}
                </button>
              ))}
            </nav>

            <p className="mt-12 max-w-lg text-sm leading-relaxed text-gray-500">
              Choose a search mode, enter a question or topic, and explore what SEEK finds.
            </p>
          </section>
        ) : (
          <section aria-label="Search" className="flex flex-col gap-8">
            <div className="flex flex-col items-center gap-2">
              <SearchBar
                value={query}
                onChange={setQuery}
                loading={view === 'loading'}
                autoFocus={false}
                searchLabel={mode === 'live' ? 'Search the live internet' : undefined}
                placeholder={mode === 'live' ? 'Search the live internet…' : undefined}
                onSearch={handleSearch}
              />
              <ModeSelector value={mode} onChange={handleModeChange} disabled={view === 'loading'} />
              {liveControls}
            </div>

            {view === 'loading' && (
              <div
                className="mx-auto mt-12 flex flex-col items-center gap-3 text-gray-400"
                role="status"
                aria-live="polite"
              >
                <Loader2 className="h-6 w-6 animate-spin text-seek-accent" aria-hidden="true" />
                <p className="text-sm">
                  Searching &ldquo;{activeQuery}&rdquo; &middot; {modeLabel(mode)}
                  {mode === 'live' ? ' through Tavily' : ''}&hellip;
                </p>
              </div>
            )}

            {view === 'results' && liveResults && mode === 'live' && (
              <LiveSearchResults response={liveResults} />
            )}

            {view === 'results' && localResults && (
              <SearchResults response={localResults} modeResponse={modeResponse} />
            )}

            {view === 'error' && (
              <div
                className="mx-auto mt-10 w-full max-w-2xl rounded-lg border border-seek-border bg-white p-8 text-center"
                role="alert"
              >
                <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-gray-50">
                  <WifiOff className="h-6 w-6 text-gray-400" aria-hidden="true" />
                </div>
                <h2 className="text-lg font-semibold text-seek-ink">
                  {mode === 'live'
                    ? liveErrorTitle[errorCode ?? ''] ?? 'Live Internet Search is unavailable'
                    : 'Unable to reach the SEEK search backend'}
                </h2>
                <p className="mt-2 text-sm text-gray-400">{error}</p>
                {mode !== 'live' && <p className="mt-1 text-xs text-gray-400">
                  Make sure the FastAPI backend is running at{' '}
                  <code className="rounded bg-seek-dark px-1.5 py-0.5 font-mono">{apiBaseUrl}</code>{' '}
                  and try again.
                </p>}
                <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleSearch(activeQuery)}
                    className="inline-flex items-center gap-2 rounded-lg bg-seek-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-[#2d4d3c] focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent focus-visible:ring-offset-2"
                  >
                    <RotateCcw className="h-4 w-4" aria-hidden="true" />
                    Retry
                  </button>
                  <button
                    type="button"
                    onClick={goHome}
                    className="inline-flex items-center gap-2 rounded-lg border border-seek-border bg-white px-4 py-2 text-sm font-medium text-gray-300 transition hover:text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
                  >
                    <Home className="h-4 w-4" aria-hidden="true" />
                    Go home
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
      </main>

      <footer className="border-t border-seek-border py-5 text-center text-xs text-gray-500">
        <p>SEEK &middot; A search engine for exploration and knowledge</p>
        <p className="mt-1 text-gray-500">{mode === DEFAULT_SEARCH_MODE ? 'Web Search' : mode}</p>
      </footer>
    </div>
  );
};

export default App;