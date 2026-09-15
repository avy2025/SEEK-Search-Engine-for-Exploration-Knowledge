import React from 'react';
import { HealthBadge, BackendStatus } from './HealthBadge';

interface HeaderProps {
  backendStatus: BackendStatus;
  onHome: () => void;
}

/** Top bar: SEEK brand (clickable to return home) + backend status badge. */
export const Header: React.FC<HeaderProps> = ({ backendStatus, onHome }) => (
  <header className="mx-auto flex w-full max-w-4xl items-center justify-between gap-4 px-4 py-5 sm:px-6">
    <button
      type="button"
      onClick={onHome}
      className="group flex items-baseline gap-2 rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent"
      aria-label="SEEK home"
    >
      <span className="bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 bg-clip-text text-xl font-extrabold tracking-tight text-transparent">
        SEEK
      </span>
      <span className="hidden text-sm font-medium text-gray-400 transition-colors group-hover:text-gray-300 sm:inline">
        Search Engine
      </span>
    </button>
    <HealthBadge status={backendStatus} />
  </header>
);

export default Header;