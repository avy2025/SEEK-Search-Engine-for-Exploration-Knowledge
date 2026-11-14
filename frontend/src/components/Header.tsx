import React from 'react';
import { History } from 'lucide-react';
import { HealthBadge, BackendStatus } from './HealthBadge';

interface HeaderProps {
  backendStatus: BackendStatus;
  onHome: () => void;
  historyOpen: boolean;
  onHistory: () => void;
}

/** Top bar: SEEK brand (clickable to return home) + backend status badge. */
export const Header: React.FC<HeaderProps> = ({
  backendStatus,
  onHome,
  historyOpen,
  onHistory,
}) => (
  <header className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-5 py-5 sm:px-8">
    <button
      type="button"
      onClick={onHome}
      className="group flex items-baseline gap-2 rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
      aria-label="SEEK home"
    >
      <span className="text-xl font-semibold tracking-tight text-seek-ink">
        SEEK
      </span>
      <span className="hidden text-sm text-gray-400 transition-colors group-hover:text-gray-300 sm:inline">
        Search &amp; discovery
      </span>
    </button>
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={onHistory}
        aria-expanded={historyOpen}
        aria-controls="seek-search-history"
        className="inline-flex items-center gap-2 rounded-lg border border-seek-border bg-white px-3 py-2 text-sm font-medium text-gray-300 transition hover:text-seek-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
      >
        <History className="h-4 w-4" aria-hidden="true" />
        <span className="hidden sm:inline">Search history</span>
        <span className="sm:hidden">History</span>
      </button>
      <HealthBadge status={backendStatus} />
    </div>
  </header>
);

export default Header;