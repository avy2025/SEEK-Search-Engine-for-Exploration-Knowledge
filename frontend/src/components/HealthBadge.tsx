import React from 'react';

export type BackendStatus = 'checking' | 'connected' | 'disconnected';

interface HealthBadgeProps {
  status: BackendStatus;
}

const STATUS_LABEL: Record<BackendStatus, string> = {
  checking: 'Backend: Checking…',
  connected: 'Backend: Connected',
  disconnected: 'Backend: Unavailable',
};

const STATUS_DOT: Record<BackendStatus, string> = {
  checking: 'bg-amber-400',
  connected: 'bg-emerald-400',
  disconnected: 'bg-rose-500',
};

const STATUS_TEXT: Record<BackendStatus, string> = {
  checking: 'text-amber-400',
  connected: 'text-emerald-400',
  disconnected: 'text-rose-400',
};

/** Compact backend connectivity indicator (Phase 1 feature, kept in Phase 3). */
export const HealthBadge: React.FC<HealthBadgeProps> = ({ status }) => (
  <span
    className="inline-flex items-center gap-2 rounded-full border border-seek-border bg-seek-card px-3 py-1.5 text-xs font-medium"
    title="FastAPI backend connectivity"
  >
    <span
      className={`h-2 w-2 rounded-full ${STATUS_DOT[status]} ${status === 'checking' ? 'animate-pulse' : ''}`}
      aria-hidden="true"
    />
    <span className={STATUS_TEXT[status]}>{STATUS_LABEL[status]}</span>
  </span>
);

export default HealthBadge;