import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Home, Loader2, RotateCcw, WifiOff } from 'lucide-react';
import Header from './components/Header';
import ModeSelector from './components/ModeSelector';
import SearchBar from './components/SearchBar';
import SearchResults from './components/SearchResults';
import type { BackendStatus } from './components/HealthBadge';
import { apiBaseUrl, asModeResponse, fetchHealth, search, type SearchResponse } from './lib/api';
import { DEFAULT_SEARCH_MODE, modeLabel, type SearchMode } from './lib/modes';
import { buildSearchPath, parseSearchState } from './lib/urlState';

type View = 'landing' | 'loading' | 'results' | 'error';

const SAMPLE_QUERIES: Record<SearchMode, readonly string[]> = {
  web: ['docker container', 'machine learning', 'odoo erp', 'natural language'],
  ai: ['how does SEEK rank documents?', 'what is hybrid search?', 'why BM25?'],
  research: ['search engine ranking', 'information retrieval evaluation'],
  code: ['faiss_store.SearchEngine', 'backend/api/search.py', 'create_engine()'],
};

export const App: React.FC = () => {
  // The URL is the source of truth for (query, mode): it makes every view
  // deep-linkable and survives refresh / back-forward navigation.
  const initial = useRef(parseSearchState(window.location.search));
  const didInitialSearch = useRef(false);

  const [query, setQuery] = useState(initial.current.query);
  const [mode, setMode] = useState<SearchMode>(initial.current.mode);
  const [activeQuery, setActiveQuery] = useState(initial.current.query);
  const [view, setView] = useState<View>(initial.current.query ? 'loading' : 'landing');
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('checking');

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

  const runSearch = useCallback(async (q: string, searchMode: SearchMode) => {
    setActiveQuery(q);
    setView('loading');
    setError(null);
    try {
      const response = await search(q, { mode: searchMode });
      setResults(response);
      setView('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The search request failed.');
      setView('error');
    }
  }, []);

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
    (next: SearchMode) => {
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
  const modeResponse = results ? asModeResponse(results) : null;

  return (
    <div className="flex min-h-screen flex-col bg-seek-dark text-gray-100 antialiased">
      <Header backendStatus={backendStatus} onHome={goHome} />

      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 py-6 sm:px-6">
        {view === 'landing' ? (
          <section className="flex flex-1 flex-col items-center justify-center text-center">
            <h1 className="text-5xl font-extrabold tracking-tight">
              <span className="bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent">
                SEEK
              </span>
            </h1>
            <p className="mt-3 text-lg font-medium text-gray-400">
              Search Engine for Exploration &amp; Knowledge
            </p>

            <div className="mt-10 flex w-full flex-col items-center gap-4">
              <SearchBar
                value={query}
                onChange={setQuery}
                loading={false}
                autoFocus
                onSearch={handleSearch}
              />
              <ModeSelector value={mode} onChange={handleModeChange} />
            </div>

            <nav
              className="mt-8 flex flex-wrap items-center justify-center gap-2"
              aria-label="Sample queries"
            >
              <span className="text-xs text-gray-500">Try:</span>
              {SAMPLE_QUERIES[mode].map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() => {
                    setQuery(sample);
                    handleSearch(sample);
                  }}
                  className="rounded-full border border-seek-border bg-seek-card px-3 py-1.5 text-xs text-gray-300 transition hover:border-seek-accent/50 hover:text-blue-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
                >
                  {sample}
                </button>
              ))}
            </nav>

            <p className="mt-12 max-w-xl text-sm leading-relaxed text-gray-500">
              Pick a mode above, then type a query and press{' '}
              <kbd className="rounded border border-seek-border bg-seek-card px-1.5 py-0.5 font-mono text-xs text-gray-300">
                Enter
              </kbd>
              . Every mode runs real retrieval over the SEEK corpus — the active mode is kept in
              the URL, so results are shareable and survive a refresh.
            </p>
          </section>
        ) : (
          <section aria-label="Search" className="flex flex-col gap-5">
            <div className="flex flex-col items-center gap-4">
              <SearchBar
                value={query}
                onChange={setQuery}
                loading={view === 'loading'}
                autoFocus={false}
                onSearch={handleSearch}
              />
              <ModeSelector value={mode} onChange={handleModeChange} disabled={view === 'loading'} />
            </div>

            {view === 'loading' && (
              <div
                className="mx-auto mt-12 flex flex-col items-center gap-3 text-gray-400"
                role="status"
                aria-live="polite"
              >
                <Loader2 className="h-6 w-6 animate-spin text-blue-400" aria-hidden="true" />
                <p className="text-sm">
                  Searching &ldquo;{activeQuery}&rdquo; &middot; {modeLabel(mode)}&hellip;
                </p>
              </div>
            )}

            {view === 'results' && results && (
              <SearchResults response={results} modeResponse={modeResponse} />
            )}

            {view === 'error' && (
              <div
                className="mx-auto mt-10 w-full max-w-2xl rounded-xl border border-rose-900/50 bg-rose-950/40 p-8 text-center"
                role="alert"
              >
                <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-rose-900/60">
                  <WifiOff className="h-6 w-6 text-rose-300" aria-hidden="true" />
                </div>
                <h2 className="text-lg font-semibold text-rose-100">
                  Unable to reach the SEEK search backend
                </h2>
                <p className="mt-2 text-sm text-rose-200/80">{error}</p>
                <p className="mt-1 text-xs text-rose-300/60">
                  Make sure the FastAPI backend is running at{' '}
                  <code className="rounded bg-seek-dark px-1.5 py-0.5 font-mono">{apiBaseUrl}</code>{' '}
                  and try again.
                </p>
                <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleSearch(activeQuery)}
                    className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                  >
                    <RotateCcw className="h-4 w-4" aria-hidden="true" />
                    Retry
                  </button>
                  <button
                    type="button"
                    onClick={goHome}
                    className="inline-flex items-center gap-2 rounded-lg border border-seek-border bg-seek-card px-4 py-2 text-sm font-medium text-gray-300 transition hover:text-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
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
        <p>
          SEEK &mdash; BM25 &middot; Crawler &middot; Semantic &middot; Hybrid &middot; RAG &middot;
          Specialized search modes
        </p>
        <p className="mt-1 text-gray-600">
          Mode: {mode === DEFAULT_SEARCH_MODE ? 'Web Search' : mode} &middot; API: {apiBaseUrl}
        </p>
      </footer>
    </div>
  );
};

export default App;