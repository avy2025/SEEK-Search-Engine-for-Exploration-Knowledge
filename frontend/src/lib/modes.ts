/* Specialized SEEK search modes (Phase 9).
 *
 * The identifiers below are the single source of truth for the UI and MUST stay
 * in sync with `backend/search/modes.py` (served live by `GET /api/search/modes`):
 *
 *   web      -> broad hybrid retrieval, ranked results, no generated answer
 *   ai       -> Phase 8 RAG answer + citations + supporting hits
 *   research -> wider retrieval, source diversification, richer snippets,
 *               optional grounded synthesis
 *   code     -> lexical-leaning technical search with documentation priority
 *               and code snippets extracted from indexed documents
 */

export type SearchMode = 'web' | 'ai' | 'research' | 'code';

export const SEARCH_MODES: readonly SearchMode[] = ['web', 'ai', 'research', 'code'];

export const DEFAULT_SEARCH_MODE: SearchMode = 'web';

export interface ModeOption {
  id: SearchMode;
  label: string;
  hint: string;
}

export const MODE_OPTIONS: readonly ModeOption[] = [
  { id: 'web', label: 'Web Search', hint: 'Hybrid ranked results across every SEEK source' },
  { id: 'ai', label: 'AI Answers', hint: 'Grounded answer from SEEK sources with citations' },
  { id: 'research', label: 'Research', hint: 'Wider, source-diversified evidence and synthesis' },
  { id: 'code', label: 'Code Docs', hint: 'Technical sources, docs priority and code snippets' },
];

export function isSearchMode(value: string | null | undefined): value is SearchMode {
  return !!value && (SEARCH_MODES as readonly string[]).includes(value);
}

export function modeLabel(mode: SearchMode): string {
  return MODE_OPTIONS.find((option) => option.id === mode)?.label ?? 'Web Search';
}

export function modeHint(mode: SearchMode): string {
  return MODE_OPTIONS.find((option) => option.id === mode)?.hint ?? '';
}