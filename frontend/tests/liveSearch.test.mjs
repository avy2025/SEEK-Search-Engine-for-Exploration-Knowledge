/* Live-search UI/API contract checks using Node's built-in test runner. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../src/', import.meta.url);
const readSource = (file) => readFile(new URL(file, root), 'utf8');

test('Live Internet Search is wired to its dedicated backend route', async () => {
  const [app, api, modes] = await Promise.all([
    readSource('App.tsx'),
    readSource('lib/api.ts'),
    readSource('lib/modes.ts'),
  ]);
  assert.match(modes, /id: 'live', label: 'Live Internet Search'/);
  assert.match(app, /searchMode === 'live'/);
  assert.match(api, /\/api\/live-search/);
  assert.match(api, /include_domains/);
  assert.match(api, /exclude_domains/);
  assert.match(api, /\/api\/live-search\/usage/);
});

test('live view covers loading, provider errors, budget status and result fields', async () => {
  const [app, results, filters] = await Promise.all([
    readSource('App.tsx'),
    readSource('components/LiveSearchResults.tsx'),
    readSource('components/LiveSearchFilters.tsx'),
  ]);
  for (const code of [
    'tavily_authentication_error',
    'tavily_rate_limited',
    'tavily_credits_exhausted',
    'tavily_timeout',
    'tavily_unavailable',
  ]) {
    assert.ok(app.includes(code), `${code} must have an explicit user-facing label`);
  }
  assert.ok(app.includes('through Tavily'));
  for (const field of ['title', 'url', 'domain', 'snippet', 'score', 'favicon', 'cached']) {
    assert.ok(results.includes(`result.${field}`) || results.includes(`response.${field}`), field);
  }
  assert.match(results, /Cached from/);
  assert.match(filters, /sm:grid-cols-2/, 'domain filters must reflow on small screens');
  assert.match(filters, /includeDomains/);
  assert.match(filters, /excludeDomains/);
});
