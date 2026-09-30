import React from 'react';
import { ExternalLink, FileCode2 } from 'lucide-react';
import type { SearchHit } from '../lib/api';
import { splitSource } from '../lib/api';
import type { SearchMode } from '../lib/modes';

interface ResultCardProps {
  hit: SearchHit;
  /** Active specialized mode; `code` renders the extracted code excerpt. */
  mode?: SearchMode;
}

/**
 * Single ranked result: title, source/domain, snippet, score, matched terms.
 *
 * The code excerpt is only rendered when the backend supplied one
 * (`hit.code_snippet`, produced by the Code Docs mode from indexed content) -
 * nothing is ever synthesised client-side.
 */
export const ResultCard: React.FC<ResultCardProps> = ({ hit, mode }) => {
  const { domain, rest, pathOnly } = splitSource(hit.source);
  const isLink = !pathOnly && Boolean(hit.source);
  const codeSnippet = hit.code_snippet?.trim() ?? '';

  const title = isLink ? (
    <a
      href={hit.source}
      target="_blank"
      rel="noreferrer"
      className="text-lg font-semibold text-blue-300 transition-colors hover:text-blue-200 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent focus:rounded"
    >
      {hit.title || hit.document_id}
    </a>
  ) : (
    <span className="text-lg font-semibold text-gray-100">{hit.title || hit.document_id}</span>
  );

  return (
    <article className="rounded-xl border border-seek-border bg-seek-card p-5 shadow-sm transition-colors hover:border-blue-800/60">
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0">{title}</h2>
        <span className="shrink-0 font-mono text-xs text-gray-500">
          #{hit.rank}
        </span>
      </div>

      <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
        {domain ? (
          <span className="inline-flex max-w-full items-center gap-1 truncate rounded-full border border-seek-border bg-seek-dark px-2.5 py-0.5 font-medium text-blue-300/90">
            {domain}
            {isLink && <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />}
          </span>
        ) : null}
        <span className="truncate font-mono text-gray-500" title={hit.source}>
          {pathOnly ? hit.source : rest}
        </span>
        {hit.score > 0 && (
          <span
            className="ml-auto shrink-0 font-mono text-blue-300/80"
            title={`Relevance score ${hit.score.toFixed(4)}`}
          >
            {hit.score.toFixed(4)}
          </span>
        )}
      </div>

      <p className="mt-3 text-sm leading-relaxed text-gray-300">
        {hit.snippet || '(no excerpt available)'}
      </p>

      {codeSnippet && (
        <div className="mt-3 overflow-hidden rounded-lg border border-seek-border bg-[#080c15]">
          <p className="flex items-center gap-1.5 border-b border-seek-border px-3 py-1.5 text-[11px] font-medium text-gray-500">
            <FileCode2 className="h-3 w-3" aria-hidden="true" />
            Code excerpt from this document
          </p>
          <pre className="overflow-x-auto px-3 py-2.5 font-mono text-[11.5px] leading-relaxed text-emerald-200/90">
            <code>{codeSnippet}</code>
          </pre>
        </div>
      )}

      {mode === 'research' && (
        <p className="mt-3 text-[11px] text-gray-600">
          Retrieved evidence &mdash; any synthesis above is generated from this material.
        </p>
      )}

      {hit.matched_terms.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Matched terms">
          {hit.matched_terms.map((term) => (
            <li
              key={term}
              className="rounded-md border border-seek-accent/20 bg-seek-accent/10 px-2 py-0.5 font-mono text-[11px] text-blue-300"
            >
              {term}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
};

export default ResultCard;