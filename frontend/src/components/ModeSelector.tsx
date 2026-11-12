import React, { useRef } from 'react';
import { BookOpen, BrainCircuit, FlaskConical, Globe2, Search } from 'lucide-react';
import { MODE_OPTIONS, type AppSearchMode } from '../lib/modes';

interface ModeSelectorProps {
  value: AppSearchMode;
  onChange: (mode: AppSearchMode) => void;
  disabled?: boolean;
}

const MODE_ICON: Record<AppSearchMode, React.ComponentType<{ className?: string }>> = {
  web: Search,
  ai: BrainCircuit,
  research: FlaskConical,
  code: BookOpen,
  live: Globe2,
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

  const focusMode = (mode: AppSearchMode) => {
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
    <div className="w-full max-w-3xl">
      <div
        role="radiogroup"
        aria-label="SEEK search mode"
        onKeyDown={handleKeyDown}
        className="flex w-full gap-1 overflow-x-auto border-b border-seek-border py-1 lg:w-auto lg:overflow-visible"
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
                'inline-flex shrink-0 items-center gap-2 border-b-2 px-3 py-3 text-sm transition-colors',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent',
                'disabled:cursor-not-allowed disabled:opacity-60',
                selected
                  ? 'border-seek-accent font-medium text-seek-accent'
                  : 'border-transparent text-gray-400 hover:text-seek-ink',
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