import { describe, it, expect, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { createAuthController, loginProxyUrl } from './auth';
import type { AuthStatus } from './types';
const required: AuthStatus = { state: 'auth_required', method: null, expires_hint: null };
afterEach(() => vi.useRealTimers());
describe('Amazon device sign-in', () => {
  it('opens a tab before the async request and retains a copyable link when blocked', async () => {
    const transport = {
      authStatus: vi.fn(async () => ({ ...required, state: 'in_progress' as const })),
      authStart: vi.fn(async () => ({ url: 'http://ha.local:8098/auth/proxy/demo/' })),
      authLogout: vi.fn()
    };
    const auth = createAuthController(transport);
    const open = vi.fn(() => {
      expect(transport.authStart).not.toHaveBeenCalled();
      return null;
    });
    await auth.start(open);
    expect(open).toHaveBeenCalledOnce();
    expect(get(auth).popupBlocked).toBe(true);
    expect(get(auth).url).toBe('http://ha.local:8098/auth/proxy/demo/');
    expect(get(auth).status?.state).toBe('in_progress');
    auth.stop();
  });
  it('signs out and reads back auth_required without keeping the login token', async () => {
    let status: AuthStatus = { ...required, state: 'ok', method: 'device' };
    const transport = {
      authStatus: vi.fn(async () => status),
      authStart: vi.fn(),
      authLogout: vi.fn(async () => {
        status = required;
        return { ok: true };
      })
    };
    const auth = createAuthController(transport);
    await auth.refresh();
    await auth.logout();
    expect(transport.authLogout).toHaveBeenCalledOnce();
    expect(get(auth).status).toEqual(required);
    expect(get(auth).url).toBe('');
    auth.stop();
  });
  it('accepts only absolute credential-free HTTP login links', () => {
    expect(loginProxyUrl('http://homeassistant.local:8098/auth/proxy/demo/')).toBe(
      'http://homeassistant.local:8098/auth/proxy/demo/'
    );
    for (const value of [
      '/auth/proxy/demo/',
      'javascript:alert(1)',
      'data:text/html,x',
      'https://user:password@ha.local/'
    ])
      expect(() => loginProxyUrl(value)).toThrow();
  });
  it('keeps polling after a temporary status error and cancels pending work on stop', async () => {
    vi.useFakeTimers();
    const transport = {
      authStatus: vi
        .fn()
        .mockResolvedValueOnce({ ...required, state: 'in_progress' })
        .mockRejectedValueOnce(new Error('offline'))
        .mockResolvedValue(required),
      authStart: vi.fn(),
      authLogout: vi.fn()
    };
    const auth = createAuthController(transport);
    await auth.refresh();
    await vi.advanceTimersByTimeAsync(3000);
    expect(get(auth).error).toBe('offline');
    await vi.advanceTimersByTimeAsync(3000);
    expect(get(auth).status?.state).toBe('auth_required');
    expect(get(auth).completed).toBe(false);
    auth.stop();
    await vi.advanceTimersByTimeAsync(3000);
    expect(transport.authStatus).toHaveBeenCalledTimes(3);
  });
  it('closes the reserved popup and surfaces start failures without polling', async () => {
    const popup = { opener: {}, close: vi.fn(), location: { href: '' }, closed: false };
    const transport = {
      authStatus: vi.fn(),
      authStart: vi.fn(async () => {
        throw new Error('unavailable');
      }),
      authLogout: vi.fn()
    };
    const auth = createAuthController(transport);
    await auth.start(() => popup as unknown as Window);
    expect(popup.opener).toBeNull();
    expect(popup.close).toHaveBeenCalledOnce();
    expect(get(auth).busy).toBe(false);
    expect(get(auth).error).toBe('unavailable');
    expect(transport.authStatus).not.toHaveBeenCalled();
    auth.stop();
  });
  it('ignores stale status replies and maintains only one poll timer', async () => {
    vi.useFakeTimers();
    let resolveFirst!: (value: AuthStatus) => void;
    const transport = {
      authStatus: vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<AuthStatus>((resolve) => {
              resolveFirst = resolve;
            })
        )
        .mockResolvedValue({ ...required, state: 'in_progress' }),
      authStart: vi.fn(),
      authLogout: vi.fn()
    };
    const auth = createAuthController(transport);
    const first = auth.refresh();
    await auth.refresh();
    resolveFirst(required);
    await first;
    expect(get(auth).status?.state).toBe('in_progress');
    expect(vi.getTimerCount()).toBe(1);
    auth.stop();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('polls an in-progress login every three seconds and stops on success', async () => {
    vi.useFakeTimers();
    let status: AuthStatus = {
      ...required,
      state: 'in_progress',
      login_url: 'http://ha.local:8098/auth/proxy/demo/'
    };
    const transport = {
      authStatus: vi.fn(async () => status),
      authStart: vi.fn(),
      authLogout: vi.fn()
    };
    const auth = createAuthController(transport);
    await auth.refresh();
    expect(get(auth).status?.state).toBe('in_progress');
    expect(get(auth).url).toBe(status.login_url);
    await vi.advanceTimersByTimeAsync(2999);
    expect(transport.authStatus).toHaveBeenCalledTimes(1);
    status = { ...required, state: 'ok', method: 'device' };
    await vi.advanceTimersByTimeAsync(1);
    expect(get(auth).completed).toBe(true);
    expect(get(auth).url).toBe('');
    await vi.advanceTimersByTimeAsync(6000);
    expect(transport.authStatus).toHaveBeenCalledTimes(2);
    auth.stop();
  });
});
