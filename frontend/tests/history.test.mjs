/* Search-history API and user-flow wiring checks using Node's built-in runner. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import test from 'node:test';

register('./ts-resolve.mjs', import.meta.url);

const root = new URL('../src/', import.meta.url);
const readSource = (file) => readFile(new URL(file, root), 'utf8');
const { groupSearchHistory } = await import('../src/lib/historyGroups.ts');

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
    'aria-label="Search history"',
    "groupSearchHistory(entries)",
    'modeLabel(entry.mode)',
    'deleteSearchHistoryEntry',
    'clearSearchHistory',
  ]) {
    assert.ok(panel.includes(text), `history UI should include ${text}`);
  }
  assert.match(panel, /w-full max-w-xl/);
  assert.match(panel, /sm:px-7/);
});

test('history grouping sorts newest first and separates relative date buckets', () => {
  const now = new Date(2026, 10, 16, 12);
  const makeEntry = (id, day, hour = 12) => ({
    id,
    query: id,
    mode: 'web',
    status: 'completed',
    created_at: new Date(2026, 10, day, hour).toISOString(),
  });
  const groups = groupSearchHistory([
    makeEntry('older', 7),
    makeEntry('today-later', 16, 11),
    makeEntry('week', 10),
    makeEntry('yesterday', 15),
    makeEntry('today-earlier', 16, 9),
  ], now);

  assert.deepEqual(groups.map((group) => group.label), [
    'Today',
    'Yesterday',
    'Previous 7 Days',
    new Date(2026, 10, 7).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    }),
  ]);
  assert.deepEqual(groups[0].entries.map((entry) => entry.id), [
    'today-later',
    'today-earlier',
  ]);
});

test('history entry restoration passes its original query and mode to search', async () => {
  const app = await readSource('App.tsx');
  const panel = await readSource('components/SearchHistoryPanel.tsx');
  assert.match(panel, /onClick=\{\(\) => onRestore\(entry\.query, entry\.mode\)\}/);
  assert.match(app, /onRestore=\{\(historyQuery, historyMode\) => \{[\s\S]*?handleSearch\(historyQuery, historyMode\)/);
});
