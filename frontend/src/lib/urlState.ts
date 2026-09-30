/* URL <-> search-state mapping (Phase 9).
 *
 * Pure functions only: no DOM, no React, no fetch. Keeping them here means the
 * query + mode round-trip through the address bar (deep links, refresh,
 * back/forward navigation) is testable in isolation.
 *
 * URL contract:
 *   /                          -> empty query, default mode
 *   /?q=python                 -> query, default mode
 *   /?q=python&mode=research   -> query + specialized mode
 *   /?mode=ai                  -> mode only (landing page remembers the choice)
 */

import { DEFAULT_SEARCH_MODE, isSearchMode, type SearchMode } from './modes';

export interface SearchState {
  query: string;
  mode: SearchMode;
}

/** Parse `window.location.search` (or any query string) into a search state. */
export function parseSearchState(search: string): SearchState {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  const rawMode = params.get('mode');
  return {
    query: (params.get('q') ?? '').trim(),
    mode: isSearchMode(rawMode) ? rawMode : DEFAULT_SEARCH_MODE,
  };
}

/**
 * Build the in-app path for a search state. Returns `/` for the pristine landing
 * view so the initial URL stays clean.
 */
export function buildSearchPath(state: SearchState): string {
  const query = state.query.trim();
  if (!query && state.mode === DEFAULT_SEARCH_MODE) return '/';
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (state.mode !== DEFAULT_SEARCH_MODE) params.set('mode', state.mode);
  const qs = params.toString();
  return qs ? `/?${qs}` : '/';
}