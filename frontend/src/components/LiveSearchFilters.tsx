import React from 'react';

interface LiveSearchFiltersProps {
  includeDomains: string;
  excludeDomains: string;
  onIncludeDomainsChange: (value: string) => void;
  onExcludeDomainsChange: (value: string) => void;
}

export const LiveSearchFilters: React.FC<LiveSearchFiltersProps> = ({
  includeDomains,
  excludeDomains,
  onIncludeDomainsChange,
  onExcludeDomainsChange,
}) => (
  <details className="w-full max-w-3xl rounded-lg border border-seek-border bg-white px-4 py-3 text-left">
    <summary className="cursor-pointer text-sm font-medium text-gray-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent">
      Optional domain filters
    </summary>
    <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
      <label className="min-w-0 text-xs text-gray-400">
        Include domains
        <input
          value={includeDomains}
          onChange={(event) => onIncludeDomainsChange(event.target.value)}
          placeholder="docs.example.com, example.org"
          autoComplete="off"
          className="mt-1 w-full min-w-0 rounded-md border border-seek-border bg-seek-dark px-3 py-2 text-sm text-seek-ink outline-none focus:border-seek-accent focus-visible:ring-2 focus-visible:ring-seek-accent"
        />
      </label>
      <label className="min-w-0 text-xs text-gray-400">
        Exclude domains
        <input
          value={excludeDomains}
          onChange={(event) => onExcludeDomainsChange(event.target.value)}
          placeholder="spam.example"
          autoComplete="off"
          className="mt-1 w-full min-w-0 rounded-md border border-seek-border bg-seek-dark px-3 py-2 text-sm text-seek-ink outline-none focus:border-seek-accent focus-visible:ring-2 focus-visible:ring-seek-accent"
        />
      </label>
    </div>
    <p className="mt-2 text-xs text-gray-500">Enter hostnames only, separated by commas.</p>
  </details>
);

export default LiveSearchFilters;
