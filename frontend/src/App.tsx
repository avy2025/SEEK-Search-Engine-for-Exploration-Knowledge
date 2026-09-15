import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Home, Loader2, RotateCcw, WifiOff } from 'lucide-react';
import Header from './components/Header';
import SearchBar from './components/SearchBar';
import SearchResults from './components/SearchResults';
import type { BackendStatus } from './components/HealthBadge';
import { apiBaseUrl, fetchHealth, search, type SearchResponse } from './lib/api';

type View = 'landing' | 'loading' | 'results' | 'error';

const SAMPLE_QUERIES = ['docker container', 'machine learning', 'odoo erp', 'natural language'];

function readQueryFromUrl(): string {
  return new URLSearchParams(window.location.search).get('q') ?? '';
}

function pushQueryToUrl(query: string): void {
  const url = query ? `/?q=${encodeURIComponent(query)}` : '/';
  window.history.pushState({}, '', url);
}

export const App: React.FC = () => {
  const initialQuery = useRef(readQueryFromUrl());
  const didInitialSearch = useRef(false);

  const [query, setQuery] = useState(initialQuery.current);
  const [activeQuery, setActiveQuery] = useState(initialQuery.current);
  const [view, setView] = useState<View>(initialQuery.current ? 'loading' : 'landing');
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

  const runSearch = useCallback(async (q: string) => {
    setActiveQuery(q);
    setView('loading');
    setError(null);
    try {
      const response = await search(q);
      setResults(response);
      setView('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The search request failed.');
      setView('error');
    }
  }, []);

  const handleSearch = useCallback(
    (q: string) => {
      pushQueryToUrl(q);
      void runSearch(q);
    },
    [runSearch],
  );

  const goHome = useCallback(() => {
    setQuery('');
    setActiveQuery('');
    setResults(null);
    setError(null);
    setView('landing');
    pushQueryToUrl('');
  }, []);

  // Execute a query found in the URL on first render (deep links / refresh).
  useEffect(() => {
    if (initialQuery.current && !didInitialSearch.current) {
      didInitialSearch.current = true;
      void runSearch(initialQuery.current);
    }
  }, [runSearch]);

  // Honour back/forward navigation across queried states.
  useEffect(() => {
    const handlePopState = () => {
      const q = readQueryFromUrl();
      setQuery(q);
      if (q) {
        void runSearch(q);
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

            <div className="mt-10 w-full flex justify-center">
              <SearchBar
                value={query}
                onChange={setQuery}
                loading={false}
                autoFocus
                onSearch={handleSearch}
              />
            </div>

            <nav className="mt-8 flex flex-wrap items-center justify-center gap-2" aria-label="Sample queries">
              <span className="text-xs text-gray-500">Try:</span>
              {SAMPLE_QUERIES.map((sample) => (
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

            <p className="mt-16 max-w-xl text-sm leading-relaxed text-gray-500">
              Type a query above and press <kbd className="rounded border border-seek-border bg-seek-card px-1.5 py-0.5 font-mono text-xs text-gray-300">Enter</kbd>{' '}
              — SEEK runs a real BM25 lexical search over its committed corpus and
              crawled pages, then returns ranked, source-tagged results.
            </p>
          </section>
        ) : (
          <section aria-label="Search" className="flex flex-col gap-6">
            <SearchBar
              value={query}
              onChange={setQuery}
              loading={view === 'loading'}
              autoFocus={false}
              onSearch={handleSearch}
            />

            {view === 'loading' && (
              <div
                className="mx-auto mt-12 flex flex-col items-center gap-3 text-gray-400"
                role="status"
                aria-live="polite"
              >
                <Loader2 className="h-6 w-6 animate-spin text-blue-400" aria-hidden="true" />
                <p className="text-sm">Searching “{activeQuery}”…</p>
              </div>
            )}

            {view === 'results' && results && <SearchResults response={results} />}

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
                <p className="mt-2 text-sm text-rose-200/80">
                  {error}
                </p>
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
          SEEK &mdash; Phases 1&ndash;4: Foundation &middot; BM25 Search MVP &middot; UI &middot; Controlled Crawler
        </p>
        <p className="mt-1 text-gray-600">API: {apiBaseUrl}</p>
      </footer>
    </div>
  );
};

export default App;