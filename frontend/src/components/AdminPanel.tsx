import React, { useCallback, useEffect, useState } from 'react';
import {
  fetchCrawlJobs,
  fetchIndexStatus,
  rebuildIndex,
  refreshIndex,
  startCrawl,
  type CrawlJobSummary,
} from '../lib/api';

const panelClass = 'rounded-xl border border-seek-border bg-white p-5 sm:p-6';
const inputClass =
  'w-full rounded-lg border border-seek-border bg-seek-dark px-3 py-2 text-sm text-seek-ink placeholder:text-gray-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent';
const buttonClass =
  'rounded-lg border border-seek-border px-3 py-2 text-sm font-medium text-seek-ink transition hover:bg-seek-dark focus:outline-none focus-visible:ring-2 focus-visible:ring-seek-accent disabled:cursor-not-allowed disabled:opacity-50';

function readable(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export const AdminPanel: React.FC = () => {
  const [urls, setUrls] = useState('');
  const [maxPages, setMaxPages] = useState('25');
  const [maxDepth, setMaxDepth] = useState('2');
  const [jobs, setJobs] = useState<CrawlJobSummary[]>([]);
  const [indexStatus, setIndexStatus] = useState<Record<string, unknown> | null>(null);
  const [dashboardErrors, setDashboardErrors] = useState<string[]>([]);
  const [operation, setOperation] = useState('');
  const [actionError, setActionError] = useState('');
  const [operationResult, setOperationResult] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    const [jobsResult, indexResult] = await Promise.allSettled([
      fetchCrawlJobs(),
      fetchIndexStatus(),
    ]);
    const errors: string[] = [];
    if (jobsResult.status === 'fulfilled') {
      setJobs(jobsResult.value.jobs);
    } else {
      errors.push(`Crawl jobs: ${jobsResult.reason instanceof Error ? jobsResult.reason.message : 'request failed'}`);
    }
    if (indexResult.status === 'fulfilled') {
      setIndexStatus(indexResult.value);
    } else {
      errors.push(`Index status: ${indexResult.reason instanceof Error ? indexResult.reason.message : 'request failed'}`);
    }
    setDashboardErrors(errors);
  }, []);

  useEffect(() => {
    void loadDashboard();
    const interval = window.setInterval(() => void loadDashboard(), 10000);
    return () => window.clearInterval(interval);
  }, [loadDashboard]);

  const runOperation = async (
    label: string,
    action: () => Promise<Record<string, unknown>>,
  ) => {
    setOperation(label);
    setActionError('');
    setOperationResult(null);
    try {
      const result = await action();
      setOperationResult(readable(result));
      await loadDashboard();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The operation failed.');
    } finally {
      setOperation('');
    }
  };

  const handleCrawl = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const seedUrls = urls.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
    if (seedUrls.length === 0) {
      setActionError('Enter at least one seed URL.');
      return;
    }
    setOperation('Starting crawl');
    setActionError('');
    setOperationResult(null);
    try {
      const result = await startCrawl({
        urls: seedUrls,
        max_pages: Number(maxPages),
        max_depth: Number(maxDepth),
        respect_robots: true,
      });
      setOperationResult(readable(result));
      await loadDashboard();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The crawl could not be started.');
    } finally {
      setOperation('');
    }
  };

  const busy = Boolean(operation);

  return (
    <section className="mx-auto mb-8 w-full max-w-3xl space-y-4" aria-label="Sources and indexing">
      <div className={panelClass}>
        <h2 className="text-lg font-semibold text-seek-ink">Add sources</h2>
        <p className="mt-1 text-sm leading-relaxed text-gray-400">
          Crawl pages from websites you are permitted to index. SEEK respects robots.txt.
        </p>
        <form className="mt-4 space-y-3" onSubmit={handleCrawl}>
          <label className="block text-sm font-medium text-gray-300" htmlFor="crawl-urls">
            Seed URLs (one per line)
          </label>
          <textarea
            id="crawl-urls"
            className={`${inputClass} min-h-24 resize-y`}
            value={urls}
            onChange={(event) => setUrls(event.target.value)}
            placeholder={'https://example.com/docs\nhttps://another.example/guide'}
            required
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm text-gray-300">
              Maximum pages
              <input
                className={`${inputClass} mt-1`}
                type="number"
                min="1"
                max="1000"
                value={maxPages}
                onChange={(event) => setMaxPages(event.target.value)}
                required
              />
            </label>
            <label className="text-sm text-gray-300">
              Maximum link depth
              <input
                className={`${inputClass} mt-1`}
                type="number"
                min="0"
                max="32"
                value={maxDepth}
                onChange={(event) => setMaxDepth(event.target.value)}
                required
              />
            </label>
          </div>
          <button className={buttonClass} type="submit" disabled={busy}>
            {operation === 'Starting crawl' ? 'Starting…' : 'Start crawl'}
          </button>
        </form>
        <p className="mt-3 text-xs leading-relaxed text-gray-500">
          Crawl-job history is currently held in backend memory and is cleared when the backend restarts.
        </p>
      </div>

      <div className={panelClass}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-seek-ink">Index management</h2>
            <p className="mt-1 text-sm text-gray-400">
              Refresh checks for document changes; rebuild recreates the lexical index.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className={buttonClass}
              type="button"
              disabled={busy}
              onClick={() => void runOperation('Refreshing index', refreshIndex)}
            >
              Refresh index
            </button>
            <button
              className={buttonClass}
              type="button"
              disabled={busy}
              onClick={() => void runOperation('Rebuilding index', rebuildIndex)}
            >
              Rebuild index
            </button>
          </div>
        </div>
        {indexStatus && (
          <pre className="mt-4 max-h-64 overflow-auto rounded-lg bg-seek-dark p-3 text-xs leading-relaxed text-gray-300">
            {readable(indexStatus)}
          </pre>
        )}
      </div>

      <div className={panelClass}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-seek-ink">Crawl activity</h2>
            <p className="mt-1 text-sm text-gray-400">
              {jobs.length} job{jobs.length === 1 ? '' : 's'} ·{' '}
              {jobs.reduce((total, job) => total + job.pages_crawled, 0)} pages crawled
            </p>
          </div>
          <button className={buttonClass} type="button" disabled={busy} onClick={() => void loadDashboard()}>
            Refresh status
          </button>
        </div>
        {dashboardErrors.length > 0 && (
          <div className="mt-3 text-sm text-red-700" role="alert">
            {dashboardErrors.map((message) => <p key={message}>{message}</p>)}
          </div>
        )}
        {jobs.length === 0 ? (
          <p className="mt-4 text-sm text-gray-500">No crawl jobs are available.</p>
        ) : (
          <ul className="mt-4 divide-y divide-seek-border">
            {jobs.map((job) => (
              <li className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm" key={job.job_id}>
                <code className="font-mono text-xs text-gray-400">{job.job_id}</code>
                <span className="rounded-full bg-seek-dark px-2.5 py-1 text-xs text-gray-300">
                  {job.status}
                </span>
                <span className="text-gray-500">
                  {job.pages_crawled} page{job.pages_crawled === 1 ? '' : 's'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {(actionError || operation) && (
        <p className={actionError ? 'text-sm text-red-700' : 'text-sm text-gray-400'} role={actionError ? 'alert' : 'status'}>
          {actionError || `${operation}…`}
        </p>
      )}
      {operationResult && (
        <pre className="max-h-48 overflow-auto rounded-lg border border-seek-border bg-white p-3 text-xs text-gray-500" role="status">
          {operationResult}
        </pre>
      )}
    </section>
  );
};

export default AdminPanel;
