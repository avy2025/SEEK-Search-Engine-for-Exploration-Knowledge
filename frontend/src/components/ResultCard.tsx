import React from 'react';
import { ExternalLink } from 'lucide-react';
import type { SearchHit } from '../lib/api';
import { splitSource } from '../lib/api';

interface ResultCardProps {
  hit: SearchHit;
}

/** Single ranked result: title, source/domain, snippet, score, matched terms. */
export const ResultCard: React.FC<ResultCardProps> = ({ hit }) => {
  const { domain, rest, pathOnly } = splitSource(hit.source);
  const isLink = !pathOnly && Boolean(hit.source);

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