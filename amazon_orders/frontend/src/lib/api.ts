import type {
  AuthStatus,
  Filters,
  ItemState,
  Monthly,
  Page,
  Recurring,
  Returns,
  Seller,
  Settings,
  Status,
  Summary,
  Weekday,
  Yearly
} from './types';
import {
  normalizeDeadlines,
  normalizeItem,
  normalizeOrder,
  normalizeOrders,
  normalizeStatus,
  type WireDeadlines,
  type WireItem,
  type WireOrder,
  type WireOrderDetail,
  type WireOrders,
  type WireStatus
} from './wire';
export const isMock = import.meta.env.VITE_MOCK === '1';
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string
  ) {
    super(message);
  }
}
export function queryString(values: object = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  return params.size ? `?${params}` : '';
}
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (isMock) return (await import('./mock')).mockRequest(path, options) as Promise<T>;
  let response: Response;
  try {
    response = await fetch(`api/${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers }
    });
  } catch {
    throw new ApiError(
      'network',
      'The add-on could not be reached. Check your connection and try again.'
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? String(response.status),
      body?.error?.message ?? response.statusText
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
const post = <T>(path: string, body: object = {}) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const api = {
  async status() {
    const [s, r, w] = await Promise.all([
      request<WireStatus>('status'),
      request<WireDeadlines>('deadlines?kind=return&within_days=365&include_closed=false'),
      request<WireDeadlines>('deadlines?kind=warranty&within_days=90&include_closed=false')
    ]);
    return normalizeStatus(
      s,
      normalizeDeadlines(r).items.length,
      normalizeDeadlines(w).items.length
    );
  },
  authStatus: () => request<AuthStatus>('auth/status'),
  authStart: () => post<{ url: string }>('auth/start'),
  authLogout: () => post<{ ok: true }>('auth/logout'),
  orders: async (filters: Filters = {}) =>
    normalizeOrders(await request<WireOrders>(`orders${queryString(filters)}`)),
  order: async (id: string) =>
    normalizeOrder(await request<WireOrder | WireOrderDetail>(`orders/${encodeURIComponent(id)}`)),
  items: async (filters: Filters = {}) => {
    const data = await request<Page<WireItem>>(`items${queryString(filters)}`);
    return { ...data, items: data.items.map((i) => normalizeItem(i)) };
  },
  updateItem: async (id: number, state: Partial<ItemState>) =>
    normalizeItem(
      await request<WireItem>(`items/${id}/state`, { method: 'PATCH', body: JSON.stringify(state) })
    ),
  deadlines: async (kind = 'all', within_days = 365) =>
    normalizeDeadlines(
      await request<WireDeadlines>(
        `deadlines${queryString({ kind, within_days, include_closed: false })}`
      )
    ),
  summary: (year: number) => request<Summary>(`stats/summary?year=${year}`),
  monthly: async (from: string, to: string) => {
    const d = await request<{ currency: string; items?: Monthly[]; months?: Monthly[] }>(
      `stats/monthly${queryString({ from, to })}`
    );
    return { currency: d.currency, items: d.months ?? d.items ?? [] };
  },
  sellers: async (year: number) => {
    const d = await request<{
      currency: string;
      items?: Seller[];
      sellers?: (Omit<Seller, 'count'> & { items: number; orders: number })[];
    }>(`stats/sellers?year=${year}&limit=8`);
    return {
      currency: d.currency,
      items: d.items ?? d.sellers?.map((s) => ({ ...s, count: s.orders })) ?? []
    };
  },
  topItems: async (year: number) => {
    const d = await request<{ currency: string; items: WireItem[] }>(
      `stats/top-items?year=${year}&limit=5`
    );
    return { ...d, items: d.items.map((i) => normalizeItem(i)) };
  },
  recurring: async () => {
    const d = await request<{ currency: string; items?: Recurring[]; recurring?: Recurring[] }>(
      'stats/recurring?limit=5'
    );
    return { currency: d.currency, items: d.recurring ?? d.items ?? [] };
  },
  returns: async (year: number): Promise<Returns> => {
    const d = await request<Partial<Returns> & { returned_items?: number; refund_amount?: number }>(
      `stats/returns?year=${year}`
    );
    return {
      count: d.count ?? d.returned_items ?? 0,
      amount: d.amount ?? d.refund_amount ?? 0,
      return_rate: d.return_rate ?? 0
    };
  },
  weekday: async () => {
    const d = await request<{
      items?: Weekday[];
      weekdays?: Weekday[];
      heatmap: { month: number | string; weekday: number; orders: number }[];
    }>('stats/weekday');
    return {
      items: d.weekdays ?? d.items ?? [],
      heatmap: d.heatmap.map((h) => ({
        ...h,
        month: typeof h.month === 'number' ? String(h.month).padStart(2, '0') : h.month
      }))
    };
  },
  settings: () => request<Settings>('settings'),
  recent: () => post<void>('sync/recent'),
  backfill: (action: 'start' | 'pause') => post<void>('sync/backfill', { action }),
  purge: (scope: string) => post<void>('cache/purge', { scope }),
  yearly: () => request<Yearly>('stats/yearly'),
  /** Selected deadlines as an .ics file (one-off import, optionally with reminders). */
  async exportDeadlines(
    selection: { item_id: number; kind: 'return' | 'warranty' }[],
    reminders: boolean
  ): Promise<Blob> {
    if (isMock) return (await import('./mock')).mockIcs(selection);
    let response: Response;
    try {
      response = await fetch('api/deadlines/export.ics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selection, reminders })
      });
    } catch {
      throw new ApiError('network', 'The add-on could not be reached. Check your connection and try again.');
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(body?.error?.code ?? String(response.status), body?.error?.message ?? response.statusText);
    }
    return response.blob();
  },
  exportUrl: (filters: Filters = {}) => `api/export.csv${queryString(filters)}`,
  async exportCsv(filters: Filters = {}) {
    if (isMock) {
      const { mockCsv } = await import('./mock');
      return URL.createObjectURL(new Blob([mockCsv(filters)], { type: 'text/csv;charset=utf-8' }));
    }
    return this.exportUrl(filters);
  }
};
