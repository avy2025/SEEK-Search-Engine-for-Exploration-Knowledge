import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  browserReducer,
  canGoBack,
  canGoForward,
  createBrowserPage,
  initialBrowserState,
} from '../src/lib/browserState.ts';

const page = (url, title = url) => createBrowserPage(url, title, 'result excerpt');

test('opening a result selects it and switching results appends browser history', () => {
  const first = browserReducer(initialBrowserState, { type: 'navigate', page: page('https://one.example/') });
  assert.equal(first.open, true);
  assert.equal(first.history[first.index].url, 'https://one.example/');
  assert.equal(first.mode, 'embedded');
  const second = browserReducer(first, { type: 'navigate', page: page('https://two.example/') });
  assert.equal(second.history.length, 2);
  assert.equal(second.history[second.index].url, 'https://two.example/');
  assert.equal(canGoBack(second), true);
});

test('back, forward, refresh, and close update navigation state', () => {
  let state = browserReducer(initialBrowserState, { type: 'navigate', page: page('https://one.example/') });
  state = browserReducer(state, { type: 'navigate', page: page('https://two.example/') });
  state = browserReducer(state, { type: 'back' });
  assert.equal(state.history[state.index].url, 'https://one.example/');
  assert.equal(canGoForward(state), true);
  state = browserReducer(state, { type: 'forward' });
  assert.equal(state.history[state.index].url, 'https://two.example/');
  const previousReloadKey = state.reloadKey;
  state = browserReducer(state, { type: 'refresh' });
  assert.equal(state.reloadKey, previousReloadKey + 1);
  assert.equal(state.status, 'loading');
  assert.deepEqual(browserReducer(state, { type: 'close' }), initialBrowserState);
});

test('embedded load, blocked frame, Reader Mode and unavailable states are explicit', () => {
  let state = browserReducer(initialBrowserState, { type: 'navigate', page: page('https://site.example/') });
  state = browserReducer(state, { type: 'iframe-loaded', url: 'https://site.example/' });
  assert.equal(state.status, 'ready');
  state = browserReducer(state, { type: 'iframe-failed', url: 'https://site.example/' });
  assert.equal(state.mode, 'unavailable');
  state = browserReducer(state, { type: 'reader' });
  const readerPage = {
    title: 'Example',
    site_name: 'site.example',
    url: 'https://site.example/',
    published_at: null,
    blocks: [],
  };
  state = browserReducer(state, { type: 'reader-success', url: 'https://site.example/', page: readerPage });
  assert.equal(state.mode, 'reader');
  assert.equal(state.readerPage.title, 'Example');
  state = browserReducer(state, { type: 'reader-failure', url: 'https://site.example/', message: 'Unavailable' });
  assert.equal(state.mode, 'unavailable');
  assert.equal(state.error, 'Unavailable');
});

test('only HTTP and HTTPS URLs without embedded credentials are selectable', () => {
  assert.equal(page('https://good.example/path').url, 'https://good.example/path');
  assert.equal(page('javascript:alert(1)'), null);
  assert.equal(page('data:text/html,hi'), null);
  assert.equal(page('https://user:pass@good.example'), null);
  assert.equal(page('not a url'), null);
});

test('browser panel offers Reader fallback and a mobile return action', async () => {
  const source = await readFile(new URL('../src/components/BrowserPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /Try Reader Mode/);
  assert.match(source, /Some websites block embedding/);
  assert.match(source, /Back to results/);
  assert.match(source, /sandbox="allow-scripts allow-forms"/);
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(app, /md:grid-cols-\[minmax\(0,2fr\)_minmax\(0,3fr\)\]/);
  assert.match(app, /mobilePane === 'browser'/);
});
