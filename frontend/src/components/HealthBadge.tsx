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
  checking: 'bg-gray-500',
  connected: 'bg-seek-accent',
  disconnected: 'bg-gray-500',
};

const STATUS_TEXT: Record<BackendStatus, string> = {
  checking: 'text-gray-400',
  connected: 'text-gray-400',
  disconnected: 'text-gray-400',
};

/** Compact backend connectivity indicator (Phase 1 feature, kept in Phase 3). */
export const HealthBadge: React.FC<HealthBadgeProps> = ({ status }) => (
  <span
    className="inline-flex items-center gap-2 text-xs"
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