import React, { useState, useEffect } from 'react';

interface HealthStatus {
  status: string;
  service: string;
}

export const App: React.FC = () => {
  const [query, setQuery] = useState('');
  const [backendStatus, setBackendStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking');
  const [healthData, setHealthData] = useState<HealthStatus | null>(null);
  const [searchNotice, setSearchNotice] = useState<string | null>(null);

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

  const checkBackendHealth = async () => {
    setBackendStatus('checking');
    try {
      // Try direct URL first, fallback to relative path if proxied
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
  };

  useEffect(() => {
    checkBackendHealth();
    const interval = setInterval(checkBackendHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearchNotice(`Search query "${query}" received. System is in Phase 1 (Foundation Setup). Real lexical & semantic search will be available in Phase 2!`);
  };

  return (
    <div className="min-h-screen bg-[#0b0f19] text-gray-100 flex flex-col justify-between p-4 md:p-8">
      {/* Top Banner & Status Header */}
      <header className="w-full max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 py-4 px-6 bg-[#131b2e] rounded-xl border border-gray-800 shadow-lg">
        <div className="flex items-center space-x-3">
          <div className="w-3 h-3 rounded-full bg-blue-500 animate-pulse" />
          <span className="font-semibold text-sm tracking-wide text-gray-300">
            SEEK Phase 1 — Foundation & Docker Architecture
          </span>
        </div>

        {/* Backend Status Indicator */}
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
                <span className="text-yellow-400">Backend Status: Checking...</span>
              </>
            )}
            {backendStatus === 'connected' && (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-emerald-400">Backend Status: Connected</span>
              </>
            )}
            {backendStatus === 'disconnected' && (
              <>
                <span className="w-2 h-2 rounded-full bg-rose-500" />
                <span className="text-rose-400">Backend Status: Disconnected</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="w-full max-w-3xl mx-auto flex-1 flex flex-col items-center justify-center my-12 text-center">
        {/* SEEK Logo & Subtitle */}
        <div className="mb-8">
          <h1 className="text-6xl md:text-7xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent">
            SEEK
          </h1>
          <p className="mt-3 text-lg md:text-xl font-medium text-gray-400 tracking-wide">
            Search Engine for Exploration & Knowledge
          </p>
        </div>

        {/* Under Development Badge */}
        <div className="mb-8 inline-flex items-center px-4 py-1.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
          🚧 Under Active Development — Phase 1 Infrastructure
        </div>

        {/* Search Input & Button Form */}
        <form onSubmit={handleSearchSubmit} className="w-full max-w-2xl flex flex-col sm:flex-row items-center gap-3">
          <div className="relative w-full">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search documents, topics, or explore knowledge..."
              className="w-full px-5 py-4 bg-[#131b2e] border border-gray-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-100 placeholder-gray-500 shadow-inner transition-all"
            />
          </div>
          <button
            type="submit"
            className="w-full sm:w-auto px-8 py-4 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold rounded-xl shadow-lg hover:shadow-blue-500/25 transition-all cursor-pointer whitespace-nowrap"
          >
            Search
          </button>
        </form>

        {/* Search Notice / Informational Feedback */}
        {searchNotice && (
          <div className="mt-6 p-4 w-full bg-blue-950/40 border border-blue-800/50 rounded-xl text-blue-200 text-sm text-left">
            <p className="font-semibold mb-1">ℹ️ Phase 1 Notice</p>
            <p>{searchNotice}</p>
          </div>
        )}

        {/* Health Check Details Card */}
        <div className="mt-12 w-full p-6 bg-[#131b2e] border border-gray-800 rounded-xl text-left shadow-lg">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3 flex items-center justify-between">
            <span>System Health Diagnostics</span>
            <span className="text-xs normal-case text-gray-500">API Endpoint: {apiBaseUrl}/health</span>
          </h2>
          {backendStatus === 'connected' && healthData ? (
            <div className="space-y-2 text-sm text-gray-300">
              <div className="flex justify-between border-b border-gray-800 pb-2">
                <span className="text-gray-400">Response Status:</span>
                <span className="font-mono text-emerald-400">{healthData.status}</span>
              </div>
              <div className="flex justify-between border-b border-gray-800 pb-2">
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
              <p>⚠️ Unable to reach FastAPI backend service at <code className="bg-gray-900 px-1.5 py-0.5 rounded">{apiBaseUrl}/health</code>.</p>
              <p className="text-xs text-gray-400">
                Ensure the backend container/service is running (<code className="bg-gray-900 px-1 rounded">uvicorn</code> or <code className="bg-gray-900 px-1 rounded">docker compose up backend</code>).
              </p>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Verifying API connection...</p>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full max-w-5xl mx-auto py-4 text-center text-xs text-gray-500 border-t border-gray-800">
        <p>SEEK — Search Engine for Exploration & Knowledge • Docker-First Full Stack Architecture</p>
      </footer>
    </div>
  );
};

export default App;
