export interface BrowserPage {
  url: string;
  title: string;
  snippet: string;
}

export interface ReaderBlock {
  type: 'heading' | 'paragraph' | 'list' | 'image';
  text: string;
  level: number | null;
  ordered: boolean;
  items: string[];
  src: string;
  alt: string;
}

export interface ReaderPage {
  title: string;
  site_name: string;
  url: string;
  published_at: string | null;
  blocks: ReaderBlock[];
}

export type BrowserMode = 'embedded' | 'reader' | 'unavailable';
export type BrowserStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface BrowserState {
  open: boolean;
  history: BrowserPage[];
  index: number;
  mode: BrowserMode;
  status: BrowserStatus;
  reloadKey: number;
  readerPage: ReaderPage | null;
  error: string | null;
}

export type BrowserAction =
  | { type: 'navigate'; page: BrowserPage }
  | { type: 'back' }
  | { type: 'forward' }
  | { type: 'refresh' }
  | { type: 'close' }
  | { type: 'reader' }
  | { type: 'reader-success'; url: string; page: ReaderPage }
  | { type: 'reader-failure'; url: string; message: string }
  | { type: 'iframe-loaded'; url: string }
  | { type: 'iframe-failed'; url: string };

export const initialBrowserState: BrowserState = {
  open: false,
  history: [],
  index: -1,
  mode: 'embedded',
  status: 'idle',
  reloadKey: 0,
  readerPage: null,
  error: null,
};

export function createBrowserPage(
  url: string,
  title: string,
  snippet = '',
): BrowserPage | null {
  try {
    const parsed = new URL(url.trim());
    if (
      !['http:', 'https:'].includes(parsed.protocol) ||
      !parsed.hostname ||
      parsed.username ||
      parsed.password
    ) {
      return null;
    }
    return {
      url: parsed.href,
      title: title.trim() || parsed.hostname,
      snippet: snippet.trim(),
    };
  } catch {
    return null;
  }
}

function currentUrl(state: BrowserState): string | null {
  return state.history[state.index]?.url ?? null;
}

export function browserReducer(state: BrowserState, action: BrowserAction): BrowserState {
  switch (action.type) {
    case 'navigate': {
      const history = state.history.slice(0, state.index + 1);
      history.push(action.page);
      if (history.length > 50) history.shift();
      return {
        ...state,
        open: true,
        history,
        index: history.length - 1,
        mode: 'embedded',
        status: 'loading',
        reloadKey: 0,
        readerPage: null,
        error: null,
      };
    }
    case 'back':
      return state.index > 0
        ? {
            ...state,
            index: state.index - 1,
            mode: 'embedded',
            status: 'loading',
            readerPage: null,
            error: null,
          }
        : state;
    case 'forward':
      return state.index < state.history.length - 1
        ? {
            ...state,
            index: state.index + 1,
            mode: 'embedded',
            status: 'loading',
            readerPage: null,
            error: null,
          }
        : state;
    case 'refresh':
      return state.open
        ? {
            ...state,
            mode: state.mode === 'unavailable' ? 'embedded' : state.mode,
            reloadKey: state.reloadKey + 1,
            status: 'loading',
            readerPage: null,
            error: null,
          }
        : state;
    case 'close':
      return initialBrowserState;
    case 'reader':
      return state.open
        ? {
            ...state,
            mode: 'reader',
            status: 'loading',
            readerPage: null,
            error: null,
          }
        : state;
    case 'reader-success':
      return currentUrl(state) === action.url
        ? { ...state, mode: 'reader', status: 'ready', readerPage: action.page, error: null }
        : state;
    case 'reader-failure':
      return currentUrl(state) === action.url
        ? { ...state, mode: 'unavailable', status: 'error', readerPage: null, error: action.message }
        : state;
    case 'iframe-loaded':
      return currentUrl(state) === action.url && state.mode === 'embedded'
        ? { ...state, status: 'ready', error: null }
        : state;
    case 'iframe-failed':
      return currentUrl(state) === action.url && state.mode === 'embedded'
        ? {
            ...state,
            mode: 'unavailable',
            status: 'error',
            error: 'This website could not be displayed inside SEEK.',
          }
        : state;
    default:
      return state;
  }
}

export function canGoBack(state: BrowserState): boolean {
  return state.open && state.index > 0;
}

export function canGoForward(state: BrowserState): boolean {
  return state.open && state.index < state.history.length - 1;
}
