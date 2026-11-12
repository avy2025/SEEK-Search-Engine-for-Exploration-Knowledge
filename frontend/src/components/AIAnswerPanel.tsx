import React, { useState } from 'react';
import { Check, Clipboard, ExternalLink, Sparkles } from 'lucide-react';
import type { AIAnswerResponse, AIAnswerSource } from '../lib/api';

interface AIAnswerPanelProps {
  response: AIAnswerResponse;
}

function renderInline(text: string, sources: Map<number, AIAnswerSource>): React.ReactNode[] {
  const tokenPattern = /(\[(\d+)\])|(\*\*(.+?)\*\*)|(`([^`]+)`)/g;
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = tokenPattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    if (match[2]) {
      const source = sources.get(Number(match[2]));
      nodes.push(
        source ? (
          <a
            key={`citation-${match.index}`}
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Source ${source.id}: ${source.title}`}
            className="font-medium text-seek-accent underline decoration-seek-accent/40 underline-offset-2 hover:decoration-seek-accent"
          >
            {match[1]}
          </a>
        ) : (
          match[1]
        ),
      );
    } else if (match[4]) {
      nodes.push(<strong key={`bold-${match.index}`}>{match[4]}</strong>);
    } else if (match[6]) {
      nodes.push(
        <code
          key={`code-${match.index}`}
          className="rounded bg-seek-dark px-1 py-0.5 font-mono text-[0.9em]"
        >
          {match[6]}
        </code>,
      );
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function AnswerMarkdown({ answer, sources }: { answer: string; sources: AIAnswerSource[] }) {
  const sourceMap = new Map(sources.map((source) => [source.id, source]));
  const lines = answer.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const HeadingTag = heading[1].length === 1 ? 'h2' : 'h3';
      blocks.push(
        <HeadingTag
          key={`heading-${index}`}
          className="mb-2 mt-5 font-semibold text-seek-ink first:mt-0"
        >
          {renderInline(heading[2], sourceMap)}
        </HeadingTag>,
      );
      index += 1;
      continue;
    }
    const unordered = /^[-*]\s+/.test(line);
    const ordered = /^\d+[.)]\s+/.test(line);
    if (unordered || ordered) {
      const items: string[] = [];
      const listPattern = unordered ? /^[-*]\s+(.+)$/ : /^\d+[.)]\s+(.+)$/;
      while (index < lines.length) {
        const item = listPattern.exec(lines[index].trim());
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      const ListTag = ordered ? 'ol' : 'ul';
      blocks.push(
        <ListTag
          key={`list-${index}`}
          className={`mb-3 space-y-1.5 pl-6 text-[15px] leading-relaxed text-gray-200 ${
            ordered ? 'list-decimal' : 'list-disc'
          }`}
        >
          {items.map((item, itemIndex) => (
            <li key={`${index}-${itemIndex}`}>{renderInline(item, sourceMap)}</li>
          ))}
        </ListTag>,
      );
      continue;
    }
    const paragraph: string[] = [];
    while (index < lines.length) {
      const next = lines[index].trim();
      if (
        !next ||
        /^(#{1,3})\s+/.test(next) ||
        /^[-*]\s+/.test(next) ||
        /^\d+[.)]\s+/.test(next)
      ) {
        break;
      }
      paragraph.push(next);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph-${index}`} className="mb-3 text-[15px] leading-relaxed text-gray-200">
        {renderInline(paragraph.join(' '), sourceMap)}
      </p>,
    );
  }
  return <div>{blocks}</div>;
}

export const AIAnswerPanel: React.FC<AIAnswerPanelProps> = ({ response }) => {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const copyAnswer = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(response.answer);
      setCopyState('copied');
    } catch {
      setCopyState('error');
    }
  };

  return (
    <section
      aria-label="AI answer"
      className="mx-auto w-full max-w-3xl rounded-xl border border-seek-border bg-white p-5 shadow-sm sm:p-7"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-md bg-seek-soft px-2.5 py-1 text-sm font-medium text-seek-accent">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            AI answer
          </span>
          <span className="text-xs text-gray-500">Tavily research · Gemini {response.model}</span>
        </div>
        <button
          type="button"
          onClick={() => void copyAnswer()}
          className="inline-flex items-center gap-2 rounded-lg border border-seek-border px-3 py-2 text-sm text-gray-300 transition hover:text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
          aria-label="Copy AI answer"
        >
          {copyState === 'copied' ? (
            <Check className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Clipboard className="h-4 w-4" aria-hidden="true" />
          )}
          {copyState === 'copied' ? 'Copied' : 'Copy answer'}
        </button>
      </div>

      <h2 className="mt-5 font-serif text-2xl font-medium leading-snug text-seek-ink">
        {response.query}
      </h2>
      <p className="mt-2 text-xs text-gray-500" role="status">
        {response.cached ? 'Cached answer from' : 'Researched'}{' '}
        {new Date(response.searched_at).toLocaleString()} · {response.sources.length} source
        {response.sources.length === 1 ? '' : 's'} · {response.usage.requests_remaining} of{' '}
        {response.usage.daily_limit} AI requests left today
      </p>

      {copyState === 'error' && (
        <p className="mt-2 text-sm text-red-700" role="status">
          Could not copy the answer. Your browser may not allow clipboard access.
        </p>
      )}

      <div className="mt-6">
        <AnswerMarkdown answer={response.answer} sources={response.sources} />
      </div>

      <div className="mt-7 border-t border-seek-border pt-5">
        <h3 className="mb-3 text-sm font-semibold text-seek-ink">Sources</h3>
        <ol className="space-y-2">
          {response.sources.map((source) => (
            <li key={source.id}>
              <details className="group rounded-lg border border-seek-border bg-seek-dark/30">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-3 text-sm font-medium text-gray-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent">
                  <span className="min-w-0">
                    <span className="mr-2 font-mono text-xs text-seek-accent">[{source.id}]</span>
                    <span>{source.title}</span>
                    <span className="ml-2 text-xs font-normal text-gray-500">{source.domain}</span>
                  </span>
                  <span className="shrink-0 text-xs text-gray-500 group-open:hidden">Details</span>
                </summary>
                <div className="border-t border-seek-border px-3 pb-3 pt-2">
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 break-all text-xs text-seek-accent underline underline-offset-2"
                  >
                    {source.url}
                    <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
                  </a>
                  <p className="mt-2 text-sm leading-relaxed text-gray-400">{source.content}</p>
                </div>
              </details>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
};

export default AIAnswerPanel;
