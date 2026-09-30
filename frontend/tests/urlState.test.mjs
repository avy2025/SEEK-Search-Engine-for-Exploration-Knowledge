/* URL <-> search-state round-trip tests for the Phase 9 mode selector.
 *
 * Run with:  npm run test:urlstate
 * `urlState.ts` / `modes.ts` are plain TS with no runtime imports, so Node can
 * strip the types (Node >= 22.6) and exercise them without a bundler. The same
 * file is executed by tests/test_search_modes_phase9.py so the URL contract is
 * covered by `pytest` too.
 */
import assert from 'node:assert/strict';
import { register } from 'node:module';
import test from 'node:test';

// SEEK's lib modules use bundler-style extensionless imports; the hook lets
// Node resolve them to `.ts` sources while type-stripping them.
register('./ts-resolve.mjs', import.meta.url);

const { DEFAULT_SEARCH_MODE, SEARCH_MODES } = await import('../src/lib/modes.ts');
const { buildSearchPath, parseSearchState } = await import('../src/lib/urlState.ts');

test('empty URL yields the pristine default state', () => {
  const state = parseSearchState('');
  assert.equal(state.query, '');
  assert.equal(state.mode, DEFAULT_SEARCH_MODE);
  assert.equal(buildSearchPath(state), '/');
});

test('query only keeps the default mode out of the URL', () => {
  const state = parseSearchState('?q=python');
  assert.equal(state.query, 'python');
  assert.equal(state.mode, 'web');
  assert.equal(buildSearchPath(state), '/?q=python');
});

test('query + mode round-trips through the URL', () => {
  const state = parseSearchState('?q=python&mode=research');
  assert.equal(state.query, 'python');
  assert.equal(state.mode, 'research');
  assert.equal(buildSearchPath(state), '/?q=python&mode=research');
});

test('a leading ? is optional when parsing', () => {
  assert.deepEqual(parseSearchState('q=python&mode=code'), {
    query: 'python',
    mode: 'code',
  });
});

test('every specialized mode round-trips', () => {
  for (const mode of SEARCH_MODES) {
    // The default mode is intentionally omitted from the URL, so a round-trip
    // restores it from the default rather than from an explicit `mode` param.
    const expected =
      mode === DEFAULT_SEARCH_MODE
        ? '/?q=docker+container'
        : `/?q=docker+container&mode=${mode}`;
    const path = buildSearchPath({ query: 'docker container', mode });
    assert.equal(path, expected);
    assert.deepEqual(parseSearchState(path.slice(1)), {
      query: 'docker container',
      mode,
    });
  }
});

test('the default mode is omitted from the URL', () => {
  assert.equal(buildSearchPath({ query: 'python', mode: 'web' }), '/?q=python');
});

test('mode-only URLs preserve the landing-page choice', () => {
  const path = buildSearchPath({ query: '', mode: 'ai' });
  assert.equal(path, '/?mode=ai');
  assert.deepEqual(parseSearchState(path.slice(1)), { query: '', mode: 'ai' });
});

test('unknown modes fall back to the default instead of breaking the app', () => {
  const state = parseSearchState('?q=python&mode=bogus');
  assert.equal(state.mode, DEFAULT_SEARCH_MODE);
  assert.equal(state.query, 'python');
});

test('legacy retrieval modes are not treated as specialized modes', () => {
  for (const legacy of ['lexical', 'bm25', 'semantic', 'hybrid']) {
    assert.equal(parseSearchState(`?q=python&mode=${legacy}`).mode, DEFAULT_SEARCH_MODE);
  }
});

test('whitespace-only queries are normalised away', () => {
  assert.equal(parseSearchState('?q=%20%20%20').query, '');
  assert.equal(buildSearchPath({ query: '   ', mode: 'code' }), '/?mode=code');
});

test('queries with URL-significant characters stay escaped and reversible', () => {
  const tricky = 'c++ & "python" #1?';
  const path = buildSearchPath({ query: tricky, mode: 'research' });
  assert.equal(path.includes('c++ &'), false, 'raw query must not leak into the URL');
  const parsed = parseSearchState(path.slice(1));
  assert.equal(parsed.query, tricky);
  assert.equal(parsed.mode, 'research');
});