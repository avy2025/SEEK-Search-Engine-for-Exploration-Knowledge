import React from 'react';
import { Clock3, ExternalLink, SearchX } from 'lucide-react';
import type { LiveSearchResponse, LiveSearchUsage } from '../lib/api';
import { createBrowserPage } from '../lib/browserState';

interface LiveSearchResultsProps {
  response: LiveSearchResponse;
  selectedUrl?: string | null;
  onOpenResult?: (url: string, title: string, snippet: string) => void;
}

export const LiveSearchResults: React.FC<LiveSearchResultsProps> = ({
  response,
  selectedUrl,
  onOpenResult,
}) => (
  <section className="mx-auto flex w-full max-w-3xl flex-col gap-4" aria-label="Live internet search results">
    <div className="flex flex-wrap items-center gap-2 px-1 text-xs text-gray-400" role="status" aria-live="polite">
      <span className="rounded-md bg-seek-soft px-2.5 py-1 font-medium text-seek-accent">
        Live Internet Search
      </span>
      <span>
        {response.total} result{response.total === 1 ? '' : 's'} for{' '}
        <span className="font-medium text-seek-ink">&ldquo;{response.query}&rdquo;</span>
      </span>
      <span className="text-gray-500">&middot; {response.took_ms.toFixed(0)} ms</span>
      {response.cached && (
        <span className="inline-flex items-center gap-1 rounded-md border border-seek-border px-2 py-1 text-gray-500">
          <Clock3 className="h-3 w-3" aria-hidden="true" />
          Cached from {new Date(response.searched_at).toLocaleString()}
        </span>
      )}
    </div>

    {response.results.length === 0 ? (
      <div className="rounded-lg border border-seek-border bg-white p-8 text-center" role="status">
        <SearchX className="mx-auto mb-3 h-8 w-8 text-gray-500" aria-hidden="true" />
        <h2 className="text-lg font-semibold text-gray-200">No live results found</h2>
        <p className="mt-2 text-sm text-gray-400">
          Try a different query or adjust the domain filters.
        </p>
      </div>
    ) : (
      <ol className="flex flex-col gap-4">
        {response.results.map((result, index) => {
          const browserPage = createBrowserPage(result.url, result.title, result.snippet);
          const selected = browserPage?.url === selectedUrl;
          return (
            <li key={`${result.url}-${index}`}>
              <article className={`rounded-lg border bg-seek-card p-5 transition-colors ${
                selected ? 'border-seek-accent ring-1 ring-seek-accent/30' : 'border-seek-border hover:border-gray-600'
              }`}>
                <div className="flex items-start gap-3">
                  {result.favicon && (
                    <img
                      src={result.favicon}
                      alt=""
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      className="mt-1 h-5 w-5 shrink-0 rounded-sm"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <h2 className="break-words text-lg font-semibold">
                      {browserPage ? (
                        <button
                          type="button"
                          onClick={() => onOpenResult?.(result.url, result.title, result.snippet)}
                          aria-pressed={selected}
                          className={`text-left transition-colors hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent focus:rounded ${
                            selected ? 'text-seek-ink underline decoration-seek-accent decoration-2 underline-offset-4' : 'text-seek-accent'
                          }`}
                        >
                          {result.title}
                          <ExternalLink className="ml-1 inline h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                      ) : (
                        <span className="text-gray-100">{result.title}</span>
                      )}
                    </h2>
                    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-400">
                      <span className="rounded-md bg-seek-soft px-2 py-0.5 font-medium text-seek-accent">
                        {result.domain}
                      </span>
                      <span className="min-w-0 break-all font-mono text-gray-500">{result.url}</span>
                      {result.score !== null && (
                        <span className="ml-auto shrink-0 font-mono text-gray-500">
                          Relevance {result.score.toFixed(3)}
                        </span>
                      )}
                    </div>
                    <p className="mt-3 whitespace-pre-line break-words text-sm leading-relaxed text-gray-300">
                      {result.snippet || '(no excerpt available)'}
                    </p>
                  </div>
                </div>
              </article>
            </li>
          );
        })}
      </ol>
    )}
  </section>
);

interface LiveSearchBudgetProps {
  usage: LiveSearchUsage | null;
  error?: string | null;
  onRefresh: () => void;
}

export const LiveSearchBudget: React.FC<LiveSearchBudgetProps> = ({ usage, error, onRefresh }) => (
  <div
    className="w-full max-w-3xl rounded-lg border border-seek-border bg-white px-4 py-3 text-left text-xs text-gray-400"
    role="status"
    aria-live="polite"
  >
    {!usage ? (
      <span>{error || 'Loading SEEK live-search budget…'}</span>
    ) : (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          SEEK monthly allowance: <strong className="text-seek-ink">{usage.monthly_allowance} credits</strong>
          {' '}&middot; remaining: <strong className="text-seek-accent">{usage.credits_remaining}</strong>
        </span>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded px-1 text-seek-accent underline underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
        >
          Refresh
        </button>
      </div>
    )}
    {usage && usage.provider_configured === false && (
      <p className="mt-1 text-amber-700">Live search needs TAVILY_API_KEY configured on the backend.</p>
    )}
    {usage?.credits_remaining === 0 && (
      <p className="mt-1 text-amber-700">SEEK&apos;s application-side monthly budget is exhausted.</p>
    )}
  </div>
);

export default LiveSearchResults;
