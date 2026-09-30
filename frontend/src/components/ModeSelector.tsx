import React, { useRef } from 'react';
import { BookOpen, BrainCircuit, FlaskConical, Search } from 'lucide-react';
import { MODE_OPTIONS, type SearchMode } from '../lib/modes';

interface ModeSelectorProps {
  value: SearchMode;
  onChange: (mode: SearchMode) => void;
  disabled?: boolean;
}

const MODE_ICON: Record<SearchMode, React.ComponentType<{ className?: string }>> = {
  web: Search,
  ai: BrainCircuit,
  research: FlaskConical,
  code: BookOpen,
};

/**
 * Specialized search-mode selector (Phase 9).
 *
 * - `radiogroup` semantics so screen readers announce the choice;
 * - roving `tabindex` + Arrow/Home/End keys (single tab stop, standard
 *   radiogroup keyboard model);
 * - horizontally scrollable on small screens instead of overflowing.
 */
export const ModeSelector: React.FC<ModeSelectorProps> = ({ value, onChange, disabled }) => {
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({});

  const focusMode = (mode: SearchMode) => {
    buttons.current[mode]?.focus();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const index = MODE_OPTIONS.findIndex((option) => option.id === value);
    if (index < 0) return;
    let next = index;
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        next = (index + 1) % MODE_OPTIONS.length;
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        next = (index - 1 + MODE_OPTIONS.length) % MODE_OPTIONS.length;
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = MODE_OPTIONS.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const target = MODE_OPTIONS[next];
    onChange(target.id);
    focusMode(target.id);
  };

  return (
    <div className="w-full max-w-2xl">
      <div
        role="radiogroup"
        aria-label="SEEK search mode"
        onKeyDown={handleKeyDown}
        className="flex w-full gap-1.5 overflow-x-auto rounded-xl border border-seek-border bg-seek-card/70 p-1.5 sm:w-auto sm:overflow-visible"
      >
        {MODE_OPTIONS.map((option) => {
          const Icon = MODE_ICON[option.id];
          const selected = option.id === value;
          return (
            <button
              key={option.id}
              ref={(node) => {
                buttons.current[option.id] = node;
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={`${option.label}: ${option.hint}`}
              tabIndex={selected ? 0 : -1}
              disabled={disabled}
              onClick={() => onChange(option.id)}
              className={[
                'inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent',
                'disabled:cursor-not-allowed disabled:opacity-60',
                selected
                  ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow-sm'
                  : 'text-gray-300 hover:bg-seek-dark hover:text-gray-100',
              ].join(' ')}
            >
              <Icon className="h-4 w-4" />
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
      <p className="mt-2 px-1 text-xs text-gray-500" aria-live="polite">
        {MODE_OPTIONS.find((option) => option.id === value)?.hint}
      </p>
    </div>
  );
};

export default ModeSelector;