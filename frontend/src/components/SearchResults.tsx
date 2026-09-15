import React from 'react';
import { SearchX } from 'lucide-react';
import type { SearchResponse } from '../lib/api';
import ResultCard from './ResultCard';

interface SearchResultsProps {
  response: SearchResponse;
}

/**
 * A response counts as "useful only if at least one hit earned a non-zero BM25
 * relevance score. The backend always returns up to ``limit`` documents (even
 * for unmatched queries all scores are 0.0), so use the genuine ``score`` field
 * to decide whether anything is actually ranked - never the hit count alone.
 */
function hasRankedHits(response: SearchResponse): boolean {
  return response.hits.some((hit) => hit.score > 0);
}

/** Ranked result list plus the empty-result state (no meaningless cards). */
export const SearchResults: React.FC<SearchResultsProps> = ({ response }) => {
  if (response.hits.length === 0 || !hasRankedHits(response)) {
    return (
      <div
        className="mx-auto mt-10 w-full max-w-2xl rounded-xl border border-seek-border bg-seek-card p-8 text-center"
        role="status"
      >
        <SearchX className="mx-auto mb-3 h-8 w-8 text-gray-500" aria-hidden="true" />
        <h2 className="text-lg font-semibold text-gray-200">No results found</h2>
        <p className="mt-2 text-sm text-gray-400">
          Nothing matched{' '}
          <span className="font-medium text-gray-300">“{response.query}”</span>{' '}
          strongly enough to rank. Try more specific terms or check the
          spelling.
        </p>
      </div>
    );
  }

  return (
    <section className="mx-auto w-full max-w-2xl" aria-label="Search results">
      <div
        className="mb-4 px-1 text-xs text-gray-400"
        role="status"
        aria-live="polite"
      >
        {response.total} result{response.total === 1 ? '' : 's'} for{' '}
        <span className="font-medium text-blue-300">“{response.query}”</span>
        <span className="ml-2 text-gray-500">· {response.took_ms.toFixed(0)} ms</span>
      </div>
      <ol className="flex flex-col gap-4">
        {response.hits.map((hit) => (
          <li key={hit.document_id}>
            <ResultCard hit={hit} />
          </li>
        ))}
      </ol>
    </section>
  );
};

export default SearchResults;