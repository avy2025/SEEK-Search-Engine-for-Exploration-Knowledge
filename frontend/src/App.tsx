import React, { useState, useEffect, useCallback } from 'react';

interface HealthStatus {
  status: string;
  service: string;
}

interface SearchHit {
  rank: number;
  document_id: string;
  title: string;
  source: string;
  snippet: string;
  score: number;
  matched_terms: string[];
}

interface SearchResponse {
  query: string;
  total: number;
  limit: number;
  hits: SearchHit[];
  took_ms: number;
  message: string;
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const App: React.FC = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [backendStatus, setBackendStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking');
  const [healthData, setHealthData] = useState<HealthStatus | null>(null);

  const checkBackendHealth = useCallback(async () => {
    setBackendStatus('checking');
    try {
      const res = await fetch(`${apiBaseUrl}/health`, { method: 'GET' }).catch(() => fetch('/api/health'));
      if (res && res.ok) {
        const data: HealthStatus = await res.json();
        setHealthData(data);
        setBackendStatus('connected');
      } else {
        setBackendStatus('disconnected');
        setHealthData(null);
      }
    } catch {
      setBackendStatus('disconnected');
      setHealthData(null);
    }
  }, []);

  useEffect(() => {
    checkBackendHealth();
    const interval = setInterval(checkBackendHealth, 15000);
    return () => clearInterval(interval);
  }, [checkBackendHealth]);

  const runSearch = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/search?q=${encodeURIComponent(q)}&limit=10`,
        { method: 'GET' }
      );
      if (!res.ok) {
        throw new Error(`Search failed with status ${res.status}`);
      }
      const data: SearchResponse = await res.json();
      setResults(data);
      setSearched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed');
      setSearched(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    runSearch(trimmed);
  };

  return (
    <div className="min-h-screen bg-[#0b0f19] text-gray-100 flex flex-col p-4 md:p-8">
      {/* Header */}
      <header className="w-full max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 py-4 px-6 bg-[#131b2e] rounded-xl border border-gray-800 shadow-lg">
        <div className="flex items-center space-x-3">
          <div className="w-3 h-3 rounded-full bg-blue-500 animate-pulse" />
          <span className="font-semibold text-sm tracking-wide text-gray-300">
            SEEK Phase 2 — BM25 Lexical Search MVP
          </span>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={checkBackendHealth}
            className="text-xs px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors"
            title="Click to re-check connection"
          >
            Refresh Health
          </button>
          <div className="flex items-center space-x-2 px-3 py-1.5 rounded-full border text-xs font-medium bg-[#0b0f19]">
            {backendStatus === 'checking' && (
              <>
                <span className="w-2 h-2 rounded-full bg-yellow-400 animate-ping" />
                <span className="text-yellow-400">Backend: Checking...</span>
              </>
            )}
            {backendStatus === 'connected' && (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-emerald-400">Backend: Connected</span>
              </>
            )}
            {backendStatus === 'disconnected' && (
              <>
                <span className="w-2 h-2 rounded-full bg-rose-500" />
                <span className="text-rose-400">Backend: Disconnected</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="w-full max-w-3xl mx-auto flex-1 flex flex-col items-center my-6 text-center">
        <div className="mb-4">
          <h1 className="text-5xl md:text-6xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent">
            SEEK
          </h1>
          <p className="mt-2 text-base md:text-lg font-medium text-gray-400 tracking-wide">
            Search Engine for Exploration & Knowledge
          </p>
        </div>

        {/* Search Form */}
        <form onSubmit={handleSearchSubmit} className="w-full max-w-2xl flex flex-col sm:flex-row items-center gap-3 mb-6">
          <div className="relative w-full">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Try: docker, machine learning, odoo, database..."
              className="w-full px-5 py-4 bg-[#131b2e] border border-gray-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-100 placeholder-gray-500 shadow-inner transition-all"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full sm:w-auto px-8 py-4 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl shadow-lg hover:shadow-blue-500/25 transition-all cursor-pointer whitespace-nowrap"
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </form>

        {/* Status / Error */}
        {error && (
          <div className="w-full p-4 bg-rose-950/40 border border-rose-800/50 rounded-xl text-rose-200 text-sm text-left mb-4">
            <p className="font-semibold mb-1">Search Error</p>
            <p>{error}</p>
          </div>
        )}

        {/* Results */}
        {searched && !error && results && (
          <div className="w-full text-left space-y-4">
            <div className="flex items-center justify-between text-xs text-gray-400 px-1">
              <span>
                {results.total} result{results.total === 1 ? '' : 's'} for{' '}
                <span className="text-blue-300 font-medium">"{results.query}"</span>
              </span>
              <span>{(results.took_ms / 1000).toFixed(2)}s</span>
            </div>

            {results.hits.length === 0 ? (
              <div className="p-6 bg-[#131b2e] border border-gray-800 rounded-xl text-sm text-gray-400">
                No documents matched your query. Try different terms like{' '}
                <span className="text-blue-300">docker</span>,{' '}
                <span className="text-blue-300">python</span>, or{' '}
                <span className="text-blue-300">machine learning</span>.
              </div>
            ) : (
              results.hits.map((hit) => (
                <article
                  key={hit.document_id}
                  className="p-5 bg-[#131b2e] border border-gray-800 rounded-xl shadow hover:border-blue-800/60 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <h2 className="text-lg font-semibold text-blue-300">
                      {hit.title}
                    </h2>
                    <span className="text-xs font-mono text-gray-500 shrink-0">
                      {hit.score.toFixed(4)}
                    </span>
                  </div>
                  {hit.source && (
                    <div className="text-xs text-gray-500 mt-0.5">{hit.source}</div>
                  )}
                  <p className="text-sm text-gray-300 mt-2 leading-relaxed">
                    {hit.snippet || '(no excerpt available)'}
                  </p>
                  {hit.matched_terms.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      {hit.matched_terms.map((term) => (
                        <span
                          key={term}
                          className="px-2 py-0.5 rounded bg-blue-500/10 border border-blue-500/20 text-[11px] text-blue-300 font-mono"
                        >
                          {term}
                        </span>
                      ))}
                    </div>
                  )}
                </article>
              ))
            )}
          </div>
        )}

        {!searched && (
          <div className="mt-8 w-full p-6 bg-[#131b2e] border border-gray-800 rounded-xl text-sm text-gray-400 text-left">
            <p className="font-semibold text-gray-300 mb-2">How it works (Phase 2)</p>
            <p>
              SEEK now performs real <span className="text-blue-300">BM25 lexical search</span> over a
              committed Markdown corpus. Type a query above to see ranked results with
              keyword-aware excerpts. No database, embeddings, or external AI — purely
              in-memory Okapi-BM25 over the sample corpus.
            </p>
          </div>
        )}

        {/* Health Details */}
        <div className="mt-10 w-full p-6 bg-[#131b2e] border border-gray-800 rounded-xl text-left shadow-lg">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3 flex items-center justify-between">
            <span>System Health Diagnostics</span>
            <span className="text-xs normal-case text-gray-500">API: {apiBaseUrl}</span>
          </h2>
          {backendStatus === 'connected' && healthData ? (
            <div className="space-y-2 text-sm text-gray-300">
              <div className="flex justify-between border-b border-gray-800 pb-2">
                <span className="text-gray-400">Response Status:</span>
                <span className="font-mono text-emerald-400">{healthData.status}</span>
              </div>
              <div className="flex justify-between pb-2">
                <span className="text-gray-400">Service Identifier:</span>
                <span className="font-mono text-blue-400">{healthData.service}</span>
              </div>
              <div className="flex justify-between pt-1">
                <span className="text-gray-400">Documentation:</span>
                <a
                  href={`${apiBaseUrl}/docs`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-400 hover:underline text-xs"
                >
                  Open FastAPI Swagger (/docs) ↗
                </a>
              </div>
            </div>
          ) : backendStatus === 'disconnected' ? (
            <div className="text-sm text-rose-300 space-y-2">
              <p>
                Unable to reach FastAPI backend at{' '}
                <code className="bg-gray-900 px-1.5 py-0.5 rounded">{apiBaseUrl}/health</code>.
              </p>
              <p className="text-xs text-gray-400">
                Start it with <code className="bg-gray-900 px-1 rounded">uvicorn backend.main:app</code>{' '}
                or <code className="bg-gray-900 px-1 rounded">docker compose up backend</code>.
              </p>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Verifying API connection...</p>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full max-w-5xl mx-auto py-4 text-center text-xs text-gray-500 border-t border-gray-800">
        <p>SEEK — Phase 2: BM25 Lexical Search MVP • In-memory index over committed corpus</p>
      </footer>
    </div>
  );
};

export default App;