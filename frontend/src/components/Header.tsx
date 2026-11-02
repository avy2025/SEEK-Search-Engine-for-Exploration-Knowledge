import React from 'react';
import { HealthBadge, BackendStatus } from './HealthBadge';

interface HeaderProps {
  backendStatus: BackendStatus;
  onHome: () => void;
}

/** Top bar: SEEK brand (clickable to return home) + backend status badge. */
export const Header: React.FC<HeaderProps> = ({ backendStatus, onHome }) => (
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
    <HealthBadge status={backendStatus} />
  </header>
);

export default Header;