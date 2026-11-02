import React from 'react';
import { Loader2, SearchIcon } from 'lucide-react';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  loading: boolean;
  autoFocus: boolean;
  onSearch: (query: string) => void;
}

/**
 * Prominent search box. Submits on Enter or button click; empty/whitespace
 * queries are ignored on the client and never reach the API.
 */
export const SearchBar: React.FC<SearchBarProps> = ({
  value,
  onChange,
  loading,
  autoFocus,
  onSearch,
}) => {
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || loading) return;
    onSearch(trimmed);
  };

  return (
    <form
      role="search"
      onSubmit={handleSubmit}
      className="w-full max-w-3xl"
      aria-label="Search SEEK"
    >
      <label htmlFor="seek-search-input" className="sr-only">
        Search the SEEK index
      </label>
      <div className="flex w-full items-stretch gap-2">
        <div className="relative flex-1">
          <SearchIcon
            className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-500"
            aria-hidden="true"
          />
          <input
            id="seek-search-input"
            name="q"
            type="search"
            autoFocus={autoFocus}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="search"
            disabled={loading}
            placeholder="Search the index…"
            className="w-full rounded-lg border border-seek-border bg-white py-4 pl-12 pr-4 text-seek-ink outline-none transition placeholder:text-gray-500 focus:border-seek-accent focus-visible:ring-2 focus-visible:ring-seek-accent disabled:opacity-60"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg bg-seek-accent px-5 py-3.5 text-sm font-medium text-white transition-colors hover:bg-[#2d4d3c] focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              <span>Searching</span>
            </>
          ) : (
            <>
              <SearchIcon className="h-4 w-4" aria-hidden="true" />
              <span>Search</span>
            </>
          )}
        </button>
      </div>
    </form>
  );
};

export default SearchBar;