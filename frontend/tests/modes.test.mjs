/* Specialized-mode catalog tests (Phase 10).
 *
 * Run with:  npm run test:frontend
 *
 * `src/lib/modes.ts` is the UI half of the mode contract that
 * `backend/search/modes.py` owns on the server. These tests pin the properties
 * the rest of the frontend relies on: one option per mode, non-empty copy, a
 * default that is part of the catalog, and a type guard that rejects both legacy
 * retrieval modes and junk. The cross-language half of the same contract (the
 * ids must equal the backend enum) is asserted by
 * `tests/test_regression_phase10.py`, so both sides are covered.
 */
import assert from 'node:assert/strict';
import { register } from 'node:module';
import test from 'node:test';

register('./ts-resolve.mjs', import.meta.url);

const {
  DEFAULT_SEARCH_MODE,
  MODE_OPTIONS,
  SEARCH_MODES,
  isSearchMode,
  modeHint,
  modeLabel,
} = await import('../src/lib/modes.ts');

const LEGACY_RETRIEVAL_MODES = ['lexical', 'bm25', 'semantic', 'hybrid'];

test('the catalog holds exactly the four specialized modes', () => {
  assert.deepEqual([...SEARCH_MODES], ['web', 'ai', 'research', 'code']);
});

test('the default mode is part of the catalog', () => {
  assert.ok(SEARCH_MODES.includes(DEFAULT_SEARCH_MODE));
  assert.equal(DEFAULT_SEARCH_MODE, 'web');
});

test('every mode has exactly one option with distinct, non-empty copy', () => {
  assert.deepEqual(
    MODE_OPTIONS.map((option) => option.id),
    [...SEARCH_MODES],
  );
  const ids = MODE_OPTIONS.map((option) => option.id);
  assert.equal(new Set(ids).size, ids.length, 'mode ids must be unique');

  for (const option of MODE_OPTIONS) {
    assert.ok(option.label.trim().length > 0, `${option.id} needs a label`);
    assert.ok(option.hint.trim().length > 0, `${option.id} needs a hint`);
  }
  const labels = MODE_OPTIONS.map((option) => option.label);
  assert.equal(new Set(labels).size, labels.length, 'labels must be distinguishable');
});

test('isSearchMode accepts every specialized mode', () => {
  for (const mode of SEARCH_MODES) {
    assert.equal(isSearchMode(mode), true, mode);
  }
});

test('isSearchMode rejects legacy retrieval modes, junk and empty values', () => {
  for (const legacy of LEGACY_RETRIEVAL_MODES) {
    assert.equal(isSearchMode(legacy), false, legacy);
  }
  for (const value of ['', ' ', 'WEB', 'Web', 'web ', 'webx', 'x', null, undefined]) {
    assert.equal(isSearchMode(value), false, String(value));
  }
});

test('label and hint lookups resolve, and degrade instead of throwing', () => {
  for (const option of MODE_OPTIONS) {
    assert.equal(modeLabel(option.id), option.label);
    assert.equal(modeHint(option.id), option.hint);
  }
  // A mode the catalog does not know must still render something usable.
  assert.equal(modeLabel('bogus'), 'Web Search');
  assert.equal(modeHint('bogus'), '');
});
