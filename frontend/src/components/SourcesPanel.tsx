import React from 'react';
import { ExternalLink, Quote } from 'lucide-react';
import type { ModeSource } from '../lib/api';
import { splitSource } from '../lib/api';
import type { SearchMode } from '../lib/modes';

interface SourcesPanelProps {
  mode: SearchMode;
  sources: ModeSource[];
  /** Hide the panel entirely when a mode has nothing to cite. */
  collapsible?: boolean;
}

const EMPTY_COPY: Record<SearchMode, string> = {
  web: '',
  ai: 'No citations - SEEK retrieved no source that could ground an answer.',
  research: 'No sources were retrieved, so there is nothing to synthesize.',
  code: '',
};

/**
 * Cited / supporting sources for the specialized modes (Phase 9).
 *
 * `sources` come straight from the backend: RAG citations when an answer was
 * produced, otherwise the supporting hits. An empty list renders an explicit
 * note rather than an invented placeholder entry.
 */
export const SourcesPanel: React.FC<SourcesPanelProps> = ({ mode, sources, collapsible = true }) => {
  if (sources.length === 0) {
    const copy = EMPTY_COPY[mode];
    if (!copy) return null;
    return (
      <section
        aria-label="Sources"
        className="rounded-xl border border-seek-border bg-seek-card p-5 text-sm text-gray-400"
      >
        <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-300">
          <Quote className="h-4 w-4" aria-hidden="true" />
          Sources
        </h2>
        <p className="mt-2">{copy}</p>
      </section>
    );
  }

  return (
    <section
      aria-label="Sources"
      className="rounded-xl border border-seek-border bg-seek-card p-5 shadow-sm"
    >
      <details open={!collapsible} className="group">
        <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md text-sm font-semibold text-gray-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent">
          <Quote className="h-4 w-4 text-indigo-300" aria-hidden="true" />
          <span>
            Sources
            <span className="ml-2 font-mono text-xs font-normal text-gray-500">
              {sources.length} cited
            </span>
          </span>
        </summary>

        <ol className="mt-4 flex flex-col gap-2.5">
          {sources.map((source, index) => {
            const { domain, rest, pathOnly } = splitSource(source.source);
            const key = source.citation_id ?? `${source.document_id}-${index}`;
            const label = (
              <>
                <span className="min-w-0 flex-1 truncate">{source.title || source.document_id}</span>
                {domain && (
                  <span className="shrink-0 font-mono text-[11px] text-gray-500">{domain}</span>
                )}
              </>
            );
            const meta = (
              <span className="flex items-center gap-2 text-[11px] text-gray-500">
                {!domain && <span className="truncate font-mono" title={source.source}>{source.source}</span>}
                {domain && <span className="truncate font-mono" title={source.source}>{rest}</span>}
                {source.score > 0 && (
                  <span className="ml-auto shrink-0 font-mono text-blue-300/70">
                    {source.score.toFixed(4)}
                  </span>
                )}
              </span>
            );

            const isLink = !pathOnly && Boolean(source.source);
            return (
              <li
                key={key}
                className="rounded-lg border border-seek-border bg-seek-dark/50 px-3 py-2.5"
              >
                <div className="flex items-start gap-2.5">
                  <span
                    className="mt-0.5 inline-flex h-5 shrink-0 items-center justify-center rounded-md bg-indigo-600/20 px-1.5 font-mono text-[11px] font-semibold text-indigo-200"
                    aria-hidden="true"
                  >
                    {source.citation_id ?? index + 1}
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex items-center gap-2 text-sm text-gray-200">
                      {isLink ? (
                        <a
                          href={source.source}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex min-w-0 flex-1 items-center gap-1.5 truncate font-medium text-blue-300 transition-colors hover:text-blue-200 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent focus:rounded"
                        >
                          {label}
                          <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
                        </a>
                      ) : (
                        <span className="flex min-w-0 flex-1 items-center gap-2">{label}</span>
                      )}
                    </div>
                    {meta}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </details>
    </section>
  );
};

export default SourcesPanel;