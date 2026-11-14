import React, { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import {
  clearSearchHistory,
  deleteSearchHistoryEntry,
  fetchSearchHistory,
  type SearchHistoryEntry,
} from '../lib/api';
import { ALL_SEARCH_MODES, modeLabel, type AppSearchMode } from '../lib/modes';

const PAGE_SIZE = 20;

interface SearchHistoryPanelProps {
  open: boolean;
  refreshToken: number;
  writeError?: string | null;
  onClose: () => void;
  onRestore: (query: string, mode: AppSearchMode) => void;
}

export const SearchHistoryPanel: React.FC<SearchHistoryPanelProps> = ({
  open,
  refreshToken,
  writeError,
  onClose,
  onRestore,
}) => {
  const [entries, setEntries] = useState<SearchHistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [modeFilter, setModeFilter] = useState<AppSearchMode | 'all'>('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchSearchHistory(
        PAGE_SIZE,
        page * PAGE_SIZE,
        modeFilter === 'all' ? undefined : modeFilter,
      );
      setEntries(result.items);
      setTotal(result.total);
      if (page > 0 && result.items.length === 0 && result.total <= page * PAGE_SIZE) {
        setPage(Math.max(0, Math.ceil(result.total / PAGE_SIZE) - 1));
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Search history could not be loaded.',
      );
    } finally {
      setLoading(false);
    }
  }, [modeFilter, page]);

  useEffect(() => {
    if (open) void loadHistory();
  }, [loadHistory, open, refreshToken]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, open]);

  const removeEntry = async (id: string) => {
    setPendingDelete(id);
    setError(null);
    try {
      await deleteSearchHistoryEntry(id);
      await loadHistory();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'The history entry could not be deleted.',
      );
    } finally {
      setPendingDelete(null);
    }
  };

  const removeAll = async () => {
    setError(null);
    try {
      await clearSearchHistory();
      setConfirmClear(false);
      setPage(0);
      await loadHistory();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Search history could not be cleared.',
      );
    }
  };

  if (!open) return null;

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onMouseDown={onClose}>
      <div className="absolute inset-0 bg-black/40" aria-hidden="true" />
      <section
        id="seek-search-history"
        role="dialog"
        aria-modal="true"
        aria-labelledby="seek-history-title"
        className="relative flex h-full w-full max-w-xl flex-col border-l border-seek-border bg-seek-dark shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-seek-border px-5 py-5 sm:px-7">
          <div>
            <h2 id="seek-history-title" className="text-lg font-semibold text-seek-ink">
              Search history
            </h2>
            <p className="mt-1 text-sm text-gray-400">
              Re-run a search in its original SEEK mode.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close search history"
            className="rounded-md p-2 text-gray-400 hover:bg-white hover:text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        <div className="flex items-center justify-between gap-3 border-b border-seek-border px-5 py-4 sm:px-7">
          <label className="flex min-w-0 items-center gap-2 text-sm text-gray-400">
            <span className="shrink-0">Mode</span>
            <select
              value={modeFilter}
              onChange={(event) => {
                setModeFilter(event.target.value as AppSearchMode | 'all');
                setPage(0);
              }}
              className="min-w-0 rounded-md border border-seek-border bg-white px-2 py-1.5 text-sm text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
              aria-label="Filter search history by mode"
            >
              <option value="all">All modes</option>
              {ALL_SEARCH_MODES.map((searchMode) => (
                <option key={searchMode} value={searchMode}>{modeLabel(searchMode)}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={total === 0 || loading}
            onClick={() => setConfirmClear(true)}
            className="shrink-0 rounded-md px-2 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-600"
          >
            Clear history
          </button>
        </div>

        {(writeError || error) && (
          <div role="alert" className="mx-5 mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 sm:mx-7">
            {writeError && <p>{writeError}</p>}
            {error && <p>{error}</p>}
            {error && (
              <button
                type="button"
                onClick={() => void loadHistory()}
                className="mt-2 font-medium underline"
              >
                Try again
              </button>
            )}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 sm:px-7">
          {loading && (
            <p role="status" aria-live="polite" className="py-8 text-center text-sm text-gray-400">
              Loading search history…
            </p>
          )}
          {!loading && !error && entries.length === 0 && (
            <div className="py-12 text-center">
              <h3 className="font-medium text-seek-ink">No searches yet</h3>
              <p className="mt-2 text-sm text-gray-400">
                Searches you complete will appear here.
              </p>
            </div>
          )}
          {!loading && entries.length > 0 && (
            <ul className="space-y-3">
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-start gap-3 rounded-lg border border-seek-border bg-white p-3 sm:p-4"
                >
                  <button
                    type="button"
                    onClick={() => onRestore(entry.query, entry.mode)}
                    className="min-w-0 flex-1 rounded text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
                    aria-label={`Run "${entry.query}" in ${modeLabel(entry.mode)}`}
                  >
                    <span className="block break-words font-medium text-seek-ink">{entry.query}</span>
                    <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-400">
                      <span>{modeLabel(entry.mode)}</span>
                      <span aria-hidden="true">·</span>
                      <time dateTime={entry.created_at}>
                        {new Date(entry.created_at).toLocaleString()}
                      </time>
                      <span aria-hidden="true">·</span>
                      <span>{entry.status}</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeEntry(entry.id)}
                    disabled={pendingDelete === entry.id}
                    aria-label={`Delete "${entry.query}" from history`}
                    className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-gray-400 hover:bg-red-50 hover:text-red-700 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-600"
                  >
                    {pendingDelete === entry.id ? 'Deleting…' : 'Delete'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="flex items-center justify-between gap-4 border-t border-seek-border px-5 py-4 text-sm sm:px-7">
          <span className="text-gray-400">
            {total ? `${total} ${total === 1 ? 'search' : 'searches'}` : ' '}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page === 0 || loading}
              onClick={() => setPage((current) => current - 1)}
              className="rounded-md border border-seek-border bg-white px-3 py-1.5 text-seek-ink disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
            >
              Previous
            </button>
            <span className="text-xs text-gray-400">{page + 1} / {pageCount}</span>
            <button
              type="button"
              disabled={page + 1 >= pageCount || loading}
              onClick={() => setPage((current) => current + 1)}
              className="rounded-md border border-seek-border bg-white px-3 py-1.5 text-seek-ink disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
            >
              Next
            </button>
          </div>
        </footer>

        {confirmClear && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40 p-5">
            <div
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="seek-history-clear-title"
              aria-describedby="seek-history-clear-description"
              className="w-full max-w-sm rounded-xl border border-seek-border bg-white p-5 shadow-xl"
            >
              <h3 id="seek-history-clear-title" className="font-semibold text-seek-ink">
                Clear all search history?
              </h3>
              <p id="seek-history-clear-description" className="mt-2 text-sm text-gray-400">
                This permanently removes every saved search.
              </p>
              <div className="mt-5 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmClear(false)}
                  className="rounded-md border border-seek-border px-3 py-2 text-sm text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void removeAll()}
                  className="rounded-md bg-red-700 px-3 py-2 text-sm font-medium text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-red-600"
                >
                  Clear history
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default SearchHistoryPanel;
