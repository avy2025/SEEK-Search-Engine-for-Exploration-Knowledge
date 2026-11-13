import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, BookOpen, ExternalLink, Loader2, RotateCw, X } from 'lucide-react';
import { fetchReaderPage } from '../lib/api';
import {
  canGoBack,
  canGoForward,
  createBrowserPage,
  type BrowserAction,
  type BrowserState,
} from '../lib/browserState';

interface BrowserPanelProps {
  state: BrowserState;
  dispatch: React.Dispatch<BrowserAction>;
  onClose: () => void;
  onBackToResults: () => void;
}

function isSafeReaderImage(src: string, pageUrl: string): boolean {
  try {
    const image = new URL(src);
    const page = new URL(pageUrl);
    return ['http:', 'https:'].includes(image.protocol) && image.hostname === page.hostname;
  } catch {
    return false;
  }
}

export const BrowserPanel: React.FC<BrowserPanelProps> = ({
  state,
  dispatch,
  onClose,
  onBackToResults,
}) => {
  const page = state.history[state.index];
  const readerPageUrl = state.readerPage?.url ?? '';
  const [addressDraft, setAddressDraft] = useState('');
  const [addressDraftPageUrl, setAddressDraftPageUrl] = useState('');
  const [addressError, setAddressError] = useState<string | null>(null);
  const address = addressDraftPageUrl === page?.url ? addressDraft : page?.url ?? '';

  useEffect(() => {
    setAddressDraft(page?.url ?? '');
    setAddressDraftPageUrl(page?.url ?? '');
    setAddressError(null);
  }, [page?.url]);

  useEffect(() => {
    if (!page || state.mode !== 'reader') return;
    const controller = new AbortController();
    void fetchReaderPage(page.url, controller.signal).then(
      (readerPage) => dispatch({ type: 'reader-success', url: page.url, page: readerPage }),
      () => {
        if (!controller.signal.aborted) {
          dispatch({
            type: 'reader-failure',
            url: page.url,
            message: 'Reader Mode could not retrieve this page. The site may restrict access or provide no readable article.',
          });
        }
      },
    );
    return () => controller.abort();
  }, [dispatch, page, state.mode, state.reloadKey]);

  if (!state.open || !page) return null;

  const submitAddress = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextPage = createBrowserPage(address, '');
    if (!nextPage) {
      setAddressError('Enter a valid HTTP or HTTPS website address.');
      return;
    }
    setAddressError(null);
    dispatch({ type: 'navigate', page: nextPage });
  };

  return (
    <aside
      className="flex min-h-[65vh] min-w-0 flex-col overflow-hidden rounded-xl border border-seek-border bg-white shadow-sm md:sticky md:top-4 md:h-[calc(100vh-7rem)] md:min-h-[34rem]"
      aria-label="Integrated browser"
    >
      <div className="flex items-center justify-between gap-2 border-b border-seek-border px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-full bg-seek-accent" aria-hidden="true" />
          <span className="truncate text-xs font-medium text-gray-500">SEEK browser</span>
          {state.mode === 'reader' && (
            <span className="rounded bg-seek-soft px-1.5 py-0.5 text-[10px] text-seek-accent">
              Reader Mode
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onBackToResults}
            className="rounded px-2 py-1 text-xs text-seek-accent hover:bg-seek-soft md:hidden"
          >
            Back to results
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close browser panel"
            title="Close browser panel"
            className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1 border-b border-seek-border p-2">
        <button
          type="button"
          onClick={() => dispatch({ type: 'back' })}
          disabled={!canGoBack(state)}
          aria-label="Back"
          title="Back"
          className="rounded p-2 text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => dispatch({ type: 'forward' })}
          disabled={!canGoForward(state)}
          aria-label="Forward"
          title="Forward"
          className="rounded p-2 text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => dispatch({ type: 'refresh' })}
          aria-label="Refresh"
          title="Refresh"
          className="rounded p-2 text-gray-600 hover:bg-gray-100"
        >
          <RotateCw className="h-4 w-4" aria-hidden="true" />
        </button>

        <form onSubmit={submitAddress} className="flex min-w-[12rem] flex-1 items-center gap-1">
          <label className="sr-only" htmlFor="seek-browser-address">Website address</label>
          <input
            id="seek-browser-address"
            type="url"
            value={address}
            onChange={(event) => {
              setAddressDraft(event.target.value);
              setAddressDraftPageUrl(page.url);
              setAddressError(null);
            }}
            className="min-w-0 flex-1 rounded-full border border-seek-border bg-gray-50 px-3 py-2 text-xs text-gray-700 outline-none focus:border-seek-accent focus:ring-1 focus:ring-seek-accent"
            aria-invalid={Boolean(addressError)}
            aria-describedby={addressError ? 'seek-browser-address-error' : undefined}
          />
          <button
            type="submit"
            className="rounded-full bg-seek-accent px-3 py-2 text-xs font-medium text-white hover:bg-[#2d4d3c]"
          >
            Go
          </button>
        </form>
      </div>

      {addressError && (
        <p id="seek-browser-address-error" className="px-3 py-2 text-xs text-red-700" role="alert">
          {addressError}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-seek-border bg-gray-50 px-3 py-2">
        <p className="min-w-0 truncate text-xs text-gray-500" title={page.title}>
          {page.title}
        </p>
        <div className="flex shrink-0 items-center gap-3">
          {state.mode !== 'reader' && (
            <button
              type="button"
              onClick={() => dispatch({ type: 'reader' })}
              className="inline-flex items-center gap-1 text-xs font-medium text-seek-accent hover:underline"
            >
              <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
              Try Reader Mode
            </button>
          )}
          <a
            href={page.url}
            target="_blank"
            rel="noopener noreferrer"
            referrerPolicy="no-referrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-seek-accent"
          >
            Open original
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        </div>
      </div>

      {state.mode === 'reader' && (
        <div className="min-h-0 flex-1 overflow-y-auto bg-[#fbfbf8] p-5 sm:p-8">
          {state.status === 'loading' && (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-gray-500" role="status">
              <Loader2 className="h-4 w-4 animate-spin text-seek-accent" aria-hidden="true" />
              Loading Reader Mode…
            </div>
          )}
          {state.status === 'error' && (
            <div className="mx-auto max-w-lg py-12 text-center" role="alert">
              <h2 className="font-serif text-xl font-semibold text-gray-800">Reader Mode unavailable</h2>
              <p className="mt-2 text-sm leading-relaxed text-gray-600">{state.error}</p>
              <button
                type="button"
                onClick={() => dispatch({ type: 'refresh' })}
                className="mt-5 rounded-lg border border-seek-border px-4 py-2 text-sm text-seek-accent hover:bg-seek-soft"
              >
                Try again
              </button>
            </div>
          )}
          {state.status === 'ready' && state.readerPage && (
            <article className="mx-auto max-w-2xl text-gray-800">
              <p className="text-xs font-semibold uppercase tracking-wide text-seek-accent">
                SEEK Reader · simplified text view
              </p>
              <h1 className="mt-3 font-serif text-3xl font-semibold leading-tight">
                {state.readerPage.title}
              </h1>
              <p className="mt-2 text-sm text-gray-500">
                {state.readerPage.site_name}
                {state.readerPage.published_at && ` · ${state.readerPage.published_at}`}
              </p>
              <p className="mt-2 break-all text-xs text-gray-400">{state.readerPage.url}</p>
              <div className="mt-7 space-y-4">
                {state.readerPage.blocks.map((block, index) => {
                  if (block.type === 'heading') {
                    const Heading = block.level === 1 ? 'h2' : block.level === 2 ? 'h3' : 'h4';
                    return (
                      <Heading key={`heading-${index}`} className="font-serif text-xl font-semibold">
                        {block.text}
                      </Heading>
                    );
                  }
                  if (block.type === 'list') {
                    const List = block.ordered ? 'ol' : 'ul';
                    return (
                      <List
                        key={`list-${index}`}
                        className={`space-y-1 pl-6 text-[15px] leading-7 ${
                          block.ordered ? 'list-decimal' : 'list-disc'
                        }`}
                      >
                        {block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}
                      </List>
                    );
                  }
                  if (block.type === 'image' && isSafeReaderImage(block.src, readerPageUrl)) {
                    return (
                      <figure key={`image-${index}`}>
                        <img
                          src={block.src}
                          alt={block.alt}
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="mx-auto max-h-96 rounded-lg object-contain"
                        />
                      </figure>
                    );
                  }
                  return (
                    <p key={`paragraph-${index}`} className="whitespace-pre-line text-[15px] leading-7">
                      {block.text}
                    </p>
                  );
                })}
              </div>
              <p className="mt-8 border-t border-seek-border pt-4 text-xs leading-relaxed text-gray-500">
                Reader Mode is a simplified, non-interactive text view. It is not the original website.
              </p>
            </article>
          )}
        </div>
      )}

      {state.mode === 'embedded' && (
        <div className="relative min-h-0 flex-1 bg-gray-100">
          {state.status === 'loading' && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/90" role="status">
              <span className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-3 text-sm text-gray-600 shadow">
                <Loader2 className="h-4 w-4 animate-spin text-seek-accent" aria-hidden="true" />
                Loading website…
              </span>
            </div>
          )}
          <iframe
            key={`${page.url}-${state.reloadKey}`}
            title={`Website: ${page.title}`}
            src={page.url}
            sandbox="allow-scripts allow-forms"
            referrerPolicy="no-referrer"
            onLoad={() => dispatch({ type: 'iframe-loaded', url: page.url })}
            onError={() => dispatch({ type: 'iframe-failed', url: page.url })}
            className="h-full min-h-[60vh] w-full border-0 md:min-h-0"
          />
          <p className="absolute bottom-2 left-2 right-2 rounded bg-white/95 px-3 py-2 text-center text-[11px] text-gray-500 shadow-sm">
            Some websites block embedding. If the page is blank or blocked, choose “Try Reader Mode”.
          </p>
        </div>
      )}

      {state.mode === 'unavailable' && (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center bg-[#fbfbf8] p-8 text-center">
          <h2 className="font-serif text-xl font-semibold text-gray-800">This website is unavailable here</h2>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-gray-600">
            {state.error || 'The site blocked embedding and could not be displayed in Reader Mode.'}
          </p>
          <p className="mt-3 max-w-lg break-all text-xs text-gray-400">{page.url}</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <button
              type="button"
              onClick={() => dispatch({ type: 'reader' })}
              className="rounded-lg bg-seek-accent px-4 py-2 text-sm font-medium text-white hover:bg-[#2d4d3c]"
            >
              Try Reader Mode
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-seek-border px-4 py-2 text-sm text-gray-700 hover:bg-white"
            >
              Return to results
            </button>
          </div>
        </div>
      )}
    </aside>
  );
};

export default BrowserPanel;
