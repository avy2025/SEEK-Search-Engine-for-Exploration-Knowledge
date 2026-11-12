/* AI Answers UI/API contract checks using Node's built-in test runner. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../src/', import.meta.url);
const readSource = (file) => readFile(new URL(file, root), 'utf8');

test('AI Answers uses its dedicated Tavily-to-Gemini endpoint', async () => {
  const [app, api, modes] = await Promise.all([
    readSource('App.tsx'),
    readSource('lib/api.ts'),
    readSource('lib/modes.ts'),
  ]);
  assert.match(modes, /id: 'ai', label: 'AI Answers', hint: 'Tavily web research and a cited Gemini answer'/);
  assert.match(app, /searchMode === 'ai'/);
  assert.match(app, /AIAnswerPanel response={aiResults}/);
  assert.match(app, /Try Live Internet Search/);
  assert.match(api, /\/api\/ai-answer/);
  assert.match(api, /fetchAIAnswerUsage/);
});

test('AI answer rendering includes clickable citations, expandable sources and copy', async () => {
  const panel = await readSource('components/AIAnswerPanel.tsx');
  for (const required of ['target="_blank"', 'source.url', '<details', '<summary', 'Copy answer']) {
    assert.ok(panel.includes(required), `AI answer UI must include ${required}`);
  }
  assert.match(panel, /navigator\.clipboard\.writeText/);
  assert.match(panel, /response\.usage\.requests_remaining/);
});

test('AI Answers has explicit loading, provider and quota error copy', async () => {
  const app = await readSource('App.tsx');
  for (const code of [
    'gemini_not_configured',
    'gemini_authentication_error',
    'gemini_quota_exhausted',
    'gemini_rate_limited',
    'gemini_model_unavailable',
    'tavily_credits_exhausted',
    'research_no_results',
    'seek_daily_ai_limit',
  ]) {
    assert.ok(app.includes(code), `${code} must have user-facing error copy`);
  }
  assert.match(app, /Tavily research and Gemini synthesis/);
  assert.match(app, /No answer was generated without successful web research/);
});
