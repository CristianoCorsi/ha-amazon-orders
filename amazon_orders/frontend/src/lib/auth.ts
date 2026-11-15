import { writable } from 'svelte/store';
import type { AuthStatus } from './types';

export function loginProxyUrl(value: string): string {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
    throw new Error('Invalid sign-in URL');
  return url.href;
}
interface AuthTransport {
  authStatus: () => Promise<AuthStatus>;
  authStart: () => Promise<{ url: string }>;
  authLogout: () => Promise<unknown>;
}
interface AuthView {
  status: AuthStatus | null;
  url: string;
  busy: boolean;
  error: string;
  completed: boolean;
  popupBlocked: boolean;
}
export function createAuthController(transport: AuthTransport) {
  let view: AuthView = {
    status: null,
    url: '',
    busy: false,
    error: '',
    completed: false,
    popupBlocked: false
  };
  const store = writable(view);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  let requestId = 0;
  const update = (patch: Partial<AuthView>) => {
    view = { ...view, ...patch };
    store.set(view);
  };
  function stop() {
    generation++;
    clearTimeout(timer);
  }
  async function refresh() {
    clearTimeout(timer);
    const current = generation;
    const request = ++requestId;
    try {
      const status = await transport.authStatus();
      if (current !== generation || request !== requestId) return;
      const wasInProgress = view.status?.state === 'in_progress';
      update({
        status,
        error: '',
        completed: status.state === 'ok' && (wasInProgress || view.completed),
        url:
          status.state === 'in_progress'
            ? status.login_url
              ? loginProxyUrl(status.login_url)
              : view.url
            : ''
      });
    } catch (error) {
      if (current === generation && request === requestId)
        update({ error: (error as Error).message });
    } finally {
      if (current === generation && request === requestId && view.status?.state === 'in_progress')
        timer = setTimeout(refresh, 3000);
    }
  }
  async function start(open: () => Window | null) {
    if (view.busy) return;
    const popup = open();
    if (popup) popup.opener = null;
    stop();
    const current = generation;
    update({ busy: true, error: '', completed: false, popupBlocked: !popup });
    try {
      const result = await transport.authStart();
      if (current !== generation) {
        popup?.close();
        return;
      }
      const url = loginProxyUrl(result.url);
      update({ url, status: { state: 'in_progress', method: 'device', expires_hint: null } });
      if (popup && !popup.closed) popup.location.href = url;
      else update({ popupBlocked: true });
      await refresh();
    } catch (error) {
      popup?.close();
      if (current === generation) update({ error: (error as Error).message });
    } finally {
      if (current === generation) update({ busy: false });
    }
  }
  async function logout() {
    if (view.busy) return;
    stop();
    const current = generation;
    update({ busy: true, error: '', completed: false });
    try {
      await transport.authLogout();
      if (current === generation) await refresh();
    } catch (error) {
      if (current === generation) update({ error: (error as Error).message });
    } finally {
      if (current === generation) update({ busy: false });
    }
  }
  return { subscribe: store.subscribe, refresh, start, logout, stop };
}
