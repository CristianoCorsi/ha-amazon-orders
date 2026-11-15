import { it, expect, vi, afterEach } from 'vitest';
import { mockRequest, mockControls } from './mock';
afterEach(() => {
  vi.unstubAllGlobals();
  mockControls.authRequired = false;
  mockControls.authInProgress = false;
});
it('provides a safe synthetic device-login lifecycle with matching response shapes', async () => {
  vi.stubGlobal('location', new URL('http://localhost:5173/'));
  vi.stubGlobal('localStorage', { getItem: () => null, removeItem: vi.fn() });
  mockControls.authRequired = true;
  expect(await mockRequest('auth/status', {})).toMatchObject({
    state: 'auth_required',
    method: null
  });
  expect(await mockRequest('auth/start', { method: 'POST' })).toEqual({
    url: 'http://localhost:5173/auth-demo.html'
  });
  expect(await mockRequest('auth/status', {})).toMatchObject({ state: 'in_progress' });
  vi.stubGlobal('localStorage', { getItem: () => 'yes', removeItem: vi.fn() });
  expect(await mockRequest('auth/status', {})).toMatchObject({ state: 'ok', method: 'device' });
  expect(await mockRequest('auth/logout', { method: 'POST' })).toEqual({ ok: true });
  expect(await mockRequest('auth/status', {})).toMatchObject({
    state: 'auth_required',
    method: null
  });
});
