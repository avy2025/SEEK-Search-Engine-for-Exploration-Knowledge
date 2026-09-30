import React from 'react';
import { AlertTriangle, CircleSlash, SearchX } from 'lucide-react';
import {
  metaValue,
  type ModeSearchResponse,
  type SearchResponse,
} from '../lib/api';
import { modeLabel, type SearchMode } from '../lib/modes';
import AnswerPanel from './AnswerPanel';
import ResultCard from './ResultCard';
import SourcesPanel from './SourcesPanel';

interface SearchResultsProps {
  response: SearchResponse;
  /**
   * Phase 9 specialized-mode envelope. Omitted for the pre-Phase-9 retrieval
   * modes so their original rendering (and payload) stays untouched.
   */
  modeResponse?: ModeSearchResponse | null;
}

/**
 * A response counts as "useful only if at least one hit earned a non-zero
 * relevance score. The backend always returns up to ``limit`` documents (even
 * for unmatched queries all scores are 0.0), so use the genuine ``score`` field
 * to decide whether anything is actually ranked - never the hit count alone.
 */
function hasRankedHits(response: SearchResponse): boolean {
  return response.hits.some((hit) => hit.score > 0);
}

/** Explicit degraded / unavailable banner - retrieval failures are never hidden. */
const StatusBanner: React.FC<{ modeResponse: ModeSearchResponse }> = ({ modeResponse }) => {
  const { status, message, metadata } = modeResponse;
  const degraded = metaValue(metadata, 'degraded_reason');
  const strategy = metaValue(metadata, 'retrieval_strategy');

  const config =
    status === 'unavailable'
      ? {
          tone: 'border-rose-900/50 bg-rose-950/30 text-rose-200',
          badge: 'border-rose-800/60 bg-rose-900/40 text-rose-300',
          icon: CircleSlash,
          title: `${modeLabel(modeResponse.mode)} is unavailable`,
        }
      : status === 'degraded'
        ? {
            tone: 'border-amber-900/50 bg-amber-950/25 text-amber-200',
            badge: 'border-amber-800/60 bg-amber-900/40 text-amber-300',
            icon: AlertTriangle,
            title: `${modeLabel(modeResponse.mode)} served in degraded mode`,
          }
        : null;
  if (!config) return null;

  const Icon = config.icon;
  const details = [message, typeof degraded === 'string' ? degraded : ''].filter(
    (entry): entry is string => Boolean(entry && entry.trim()),
  );

  return (
    <div className={`rounded-xl border p-4 ${config.tone}`} role="status" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        <p className="text-sm font-semibold">{config.title}</p>
        {typeof strategy === 'string' && (
          <span className={`rounded-full border px-2 py-0.5 font-mono text-[11px] ${config.badge}`}>
            retrieval: {strategy}
          </span>
        )}
      </div>
      {details.map((entry) => (
        <p key={entry} className="mt-1.5 pl-6 text-xs leading-relaxed opacity-90">
          {entry}
        </p>
      ))}
    </div>
  );
};

/**
 * Empty state. Specialised modes always carry a backend-authored ``message``
 * (e.g. "no indexed SEEK sources matched this query") which is preferred over
 * the generic copy so the UI never contradicts the API.
 */
const EmptyState: React.FC<{ response: SearchResponse; specialized: boolean }> = ({
  response,
  specialized,
}) => {
  const backendMessage = response.message?.trim();
  const useBackendCopy = Boolean(
    specialized && backendMessage && backendMessage.toLowerCase() !== 'ok',
  );

  return (
    <div
      className="w-full rounded-xl border border-seek-border bg-seek-card p-8 text-center"
      role="status"
    >
      <SearchX className="mx-auto mb-3 h-8 w-8 text-gray-500" aria-hidden="true" />
      <h2 className="text-lg font-semibold text-gray-200">No results found</h2>
      <p className="mt-2 text-sm text-gray-400">
        {useBackendCopy ? (
          <span>
            {response.message} for{' '}
            <span className="font-medium text-gray-300">&ldquo;{response.query}&rdquo;</span>.
          </span>
        ) : (
          <span>
            Nothing matched{' '}
            <span className="font-medium text-gray-300">&ldquo;{response.query}&rdquo;</span>{' '}
            strongly enough to rank. Try more specific terms or check the spelling.
          </span>
        )}
      </p>
    </div>
  );
};

/** Ranked result list plus the empty-result state (no meaningless cards). */
export const SearchResults: React.FC<SearchResultsProps> = ({ response, modeResponse }) => {
  const mode: SearchMode | null = modeResponse?.mode ?? null;
  const passages = metaValue(modeResponse?.metadata, 'rag.passages');
  const empty = response.hits.length === 0 || !hasRankedHits(response);

  const ranked = (
    <ol className="flex flex-col gap-4">
      {response.hits.map((hit) => (
        <li key={hit.document_id}>
          <ResultCard hit={hit} mode={mode ?? undefined} />
        </li>
      ))}
    </ol>
  );

  if (!modeResponse) {
    // Pre-Phase-9 retrieval modes: unchanged rendering.
    return (
      <section className="mx-auto w-full max-w-2xl" aria-label="Search results">
        {empty ? (
          <EmptyState response={response} specialized={false} />
        ) : (
          <>
            <p className="mb-4 px-1 text-xs text-gray-400" role="status" aria-live="polite">
              {response.total} result{response.total === 1 ? '' : 's'} for{' '}
              <span className="font-medium text-blue-300">&ldquo;{response.query}&rdquo;</span>
              <span className="ml-2 text-gray-500">&middot; {response.took_ms.toFixed(0)} ms</span>
            </p>
            {ranked}
          </>
        )}
      </section>
    );
  }

  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-5" aria-label="Search results">
      <div
        className="flex flex-wrap items-center gap-2 px-1 text-xs text-gray-400"
        role="status"
        aria-live="polite"
      >
        <span className="rounded-full border border-seek-accent/30 bg-seek-accent/10 px-2.5 py-0.5 font-medium text-blue-300">
          {modeLabel(modeResponse.mode)}
        </span>
        <span>
          {response.total} result{response.total === 1 ? '' : 's'} for{' '}
          <span className="font-medium text-blue-300">&ldquo;{response.query}&rdquo;</span>
        </span>
        <span className="text-gray-500">&middot; {response.took_ms.toFixed(0)} ms</span>
      </div>

      <StatusBanner modeResponse={modeResponse} />

      <AnswerPanel
        mode={modeResponse.mode}
        answer={modeResponse.answer}
        note={
          typeof metaValue(modeResponse.metadata, 'answer_note') === 'string'
            ? (metaValue(modeResponse.metadata, 'answer_note') as string)
            : undefined
        }
        passages={typeof passages === 'number' ? passages : undefined}
      />

      {empty ? <EmptyState response={response} specialized /> : ranked}

      <SourcesPanel mode={modeResponse.mode} sources={modeResponse.sources} />
    </section>
  );
};

export default SearchResults;