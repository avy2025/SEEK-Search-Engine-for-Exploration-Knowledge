/* Search-history API and user-flow wiring checks using Node's built-in runner. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../src/', import.meta.url);
const readSource = (file) => readFile(new URL(file, root), 'utf8');

test('history API client exposes recording, listing, retrieval and deletion', async () => {
  const api = await readSource('lib/api.ts');
  for (const name of [
    'recordSearchHistory',
    'fetchSearchHistory',
    'fetchSearchHistoryEntry',
    'deleteSearchHistoryEntry',
    'clearSearchHistory',
  ]) {
    assert.match(api, new RegExp(`function ${name}\\(`));
  }
  assert.match(api, /\/api\/history/);
  assert.match(api, /\/api\/session/);
  assert.match(api, /withBrowserSession/);
  assert.match(api, /credentials: 'include'/);
  assert.match(api, /JSON\.stringify\(\{ query, mode, request_id: requestId \}\)/);
  assert.match(api, /encodeURIComponent\(id\)/);
  assert.match(api, /requestNoContent/);
});

test('successful user searches save once; automatic URL searches do not duplicate history', async () => {
  const app = await readSource('App.tsx');
  assert.match(app, /searchMode === 'live'/);
  assert.match(app, /searchMode === 'ai'/);
  assert.match(app, /if \(recordHistory\) void saveSearchHistory\(q, searchMode\)/);
  assert.match(app, /recordSearchHistory\(q, searchMode, crypto\.randomUUID\(\)\)/);
  assert.match(app, /runSearch\(urlQuery, urlMode, false\)/);
  assert.match(app, /runSearch\(next\.query, next\.mode, false\)/);
  assert.match(app, /onRestore=\{\(historyQuery, historyMode\)/);
});

test('history panel supports filtering, restoration, confirmation and responsive states', async () => {
  const panel = await readSource('components/SearchHistoryPanel.tsx');
  for (const text of [
    'Loading search history',
    'No searches yet',
    'Clear all search history?',
    'Previous',
    'Next',
    'aria-modal="true"',
    'aria-label="Filter search history by mode"',
    'modeLabel(entry.mode)',
    'deleteSearchHistoryEntry',
    'clearSearchHistory',
  ]) {
    assert.ok(panel.includes(text), `history UI should include ${text}`);
  }
  assert.match(panel, /w-full max-w-xl/);
  assert.match(panel, /sm:px-7/);
});
