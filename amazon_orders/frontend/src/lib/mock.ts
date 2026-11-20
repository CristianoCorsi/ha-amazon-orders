// SYNTHETIC DEMO ONLY. No customer data, sessions or Amazon traffic.
import {
  mdiHeadphones,
  mdiDeskLamp,
  mdiCoffeeMaker,
  mdiKeyboardOutline,
  mdiSpeaker,
  mdiBookOpenPageVariant,
  mdiFlowerOutline,
  mdiUsbFlashDrive,
  mdiWaterOutline,
  mdiMonitor,
  mdiPackageVariantClosed
} from '@mdi/js';
import type {
  AuthStatus,
  Deadline,
  Filters,
  Item,
  ItemState,
  Order,
  Status,
  Summary
} from './types';
const today = new Date();
today.setHours(12, 0, 0, 0);
const year = today.getFullYear();
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function offset(days: number) {
  const d = new Date(today);
  d.setDate(d.getDate() + days);
  return iso(d);
}
function months(date: string, amount: number) {
  const d = new Date(date + 'T12:00:00');
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + amount);
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  d.setDate(Math.min(day, last));
  return iso(d);
}
const products = [
  ['Aurora Studio · Wireless headphones', 'Sonic Grove', 89.9, mdiHeadphones, '#e2e9f0', '#4e647a'],
  ['Lampada da scrivania Luma Air', 'Casa Luminosa', 46.5, mdiDeskLamp, '#efe8d9', '#857144'],
  [
    'Filtro caffè riutilizzabile, set da 2',
    'Bottega Quotidiana',
    18.9,
    mdiCoffeeMaker,
    '#e9dfd8',
    '#84654e'
  ],
  [
    'Tastiera meccanica Quiet Type 75',
    'Forma Digital',
    124.99,
    mdiKeyboardOutline,
    '#e2e4ec',
    '#656a8e'
  ],
  ['Pebble Mini · Altoparlante Bluetooth', 'Sonic Grove', 39.95, mdiSpeaker, '#dcece8', '#4a776d'],
  [
    'Quaderno rilegato, carta avorio A5',
    'Carta & Storie',
    14.8,
    mdiBookOpenPageVariant,
    '#eadfe3',
    '#8c5f73'
  ],
  [
    'Vaso in ceramica Terra, verde salvia',
    'Casa Luminosa',
    28.5,
    mdiFlowerOutline,
    '#e3e9db',
    '#657b4c'
  ],
  ['Pocket Drive · USB-C 128 GB', 'Forma Digital', 24.9, mdiUsbFlashDrive, '#e1e7ed', '#536b7e'],
  ['Borraccia termica Flow 750 ml', 'Sentiero Goods', 32.9, mdiWaterOutline, '#dce9ed', '#467a8a'],
  ['Monitor Arcview 27 pollici QHD', 'Forma Digital', 279.0, mdiMonitor, '#e2e8ec', '#546b7a'],
  [
    'Sacchetti per aspirapolvere, 8 pezzi',
    'Bottega Quotidiana',
    16.49,
    mdiPackageVariantClosed,
    '#ece5db',
    '#827157'
  ]
] as const;
export function placeholder(index = 0): string {
  const p = products[index % products.length];
  return (
    'data:image/svg+xml,' +
    encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160"><rect width="160" height="160" rx="26" fill="${p[4]}"/><circle cx="80" cy="86" r="55" fill="white" opacity=".25"/><path d="${p[3]}" transform="translate(34 30) scale(3.85)" fill="${p[5]}"/></svg>`
    )
  );
}
export const fallbackImage = placeholder(10);
const orders: Order[] = Array.from({ length: 96 }, (_, i) => {
  const placed = i < 8 ? offset(-[13, 25, 6, 41, 29, 55, 8, 18][i]) : offset(-75 - (i - 8) * 10);
  const cancelled = i === 6 || i % 23 === 12;
  const orderNumber = `DEMO-${String(1048 - i).padStart(5, '0')}`;
  const index = i % products.length;
  const product = products[index];
  const state: ItemState = {
    status: i === 1 ? 'to_return' : i % 19 === 4 ? 'returned' : i % 4 === 0 ? 'keep' : 'none',
    note: i === 1 ? 'Controllare le dimensioni sulla scrivania.' : '',
    warranty_until_override: null,
    warranty_months_override: i === 3 ? 36 : null
  };
  const delivered = offset(Math.round((Date.parse(placed) - today.getTime()) / 86400000) + 2);
  const returnDate = i < 8 ? offset([2, 5, 9, 15, 25, 30, 7, 42][i]) : null;
  const item: Item = {
    id: i + 1,
    order_number: orderNumber,
    asin: `DEMO${String(index).padStart(6, '0')}`,
    title: product[0],
    seller: product[1],
    price: product[2],
    quantity: 1,
    image_link: placeholder(index),
    link: null,
    delivered_date: delivered,
    return_eligible_date: returnDate,
    return_deadline: cancelled || state.status === 'returned' ? null : returnDate,
    warranty_deadline:
      cancelled || state.status === 'returned'
        ? null
        : months(delivered, state.warranty_months_override || 24),
    item_state: state
  };
  return {
    order_number: orderNumber,
    placed_date: placed,
    order_total: cancelled ? null : product[2] + (i % 9 === 2 ? 3.99 : 0),
    // Every 7th order is paid with Amazon balance: the card was charged 0.
    grand_total: cancelled ? null : i % 7 === 3 ? 0 : product[2] + (i % 9 === 2 ? 3.99 : 0),
    paid_with_balance: !cancelled && i % 7 === 3 ? product[2] + (i % 9 === 2 ? 3.99 : 0) : null,
    shipping_total: i % 9 === 2 ? 3.99 : 0,
    refund_total: state.status === 'returned' ? product[2] : 0,
    cancelled,
    items: [item],
    shipments: [
      {
        id: i + 1,
        status_text: cancelled ? 'Cancelled' : 'Delivered',
        delivered_date: cancelled ? null : delivered
      }
    ]
  };
});
const scenario =
  typeof location === 'undefined' ? null : new URLSearchParams(location.search).get('mock_auth');
export const mockControls = {
  authRequired: scenario === 'auth_required' || scenario === 'duplicate_device',
  duplicateDevice: scenario === 'duplicate_device',
  authInProgress: scenario === 'in_progress',
  failRequests: false,
  empty: false
};
function mockAuthStatus(): AuthStatus {
  if (mockControls.authInProgress) {
    try {
      if (localStorage.getItem('amazon-orders-demo-complete') === 'yes') {
        localStorage.removeItem('amazon-orders-demo-complete');
        mockControls.authInProgress = false;
        mockControls.authRequired = false;
      }
    } catch {
      /* storage disabled: the demo controls still work */
    }
  }
  return {
    state: mockControls.authInProgress
      ? 'in_progress'
      : mockControls.authRequired
        ? 'auth_required'
        : 'ok',
    method: mockControls.authRequired && !mockControls.authInProgress ? null : 'device',
    expires_hint: null,
    ...(mockControls.duplicateDevice && !mockControls.authInProgress ? { last_error: 'duplicate_device' } : {}),
    ...(mockControls.authInProgress
      ? { login_url: new URL('auth-demo.html', location.href).href }
      : {})
  };
}
let backfillState = 'running';
let lastSync = new Date(today.getTime() - 18 * 60000).toISOString();
function filtered(filters: Filters): Order[] {
  let result = mockControls.empty
    ? []
    : orders.filter((o) => {
        const item = o.items[0];
        const text = `${o.order_number} ${item.title} ${item.seller}`.toLowerCase();
        return (
          (!filters.q || text.includes(filters.q.toLowerCase())) &&
          (!filters.from || o.placed_date >= filters.from) &&
          (!filters.to || o.placed_date <= filters.to) &&
          (!filters.seller || item.seller === filters.seller) &&
          (!filters.status ||
            (filters.status === 'cancelled'
              ? o.cancelled
              : !o.cancelled && item.item_state.status === filters.status)) &&
          (!filters.min || (o.order_total ?? 0) >= Number(filters.min)) &&
          (!filters.max || (o.order_total ?? 0) <= Number(filters.max))
        );
      });
  result = [...result].sort((a, b) =>
    filters.sort === 'date_asc'
      ? a.placed_date.localeCompare(b.placed_date)
      : filters.sort === 'price_desc'
        ? (b.grand_total ?? 0) - (a.grand_total ?? 0)
        : b.placed_date.localeCompare(a.placed_date)
  );
  return result;
}
function yearOrders(y: number) {
  return filtered({ from: `${y}-01-01`, to: `${y}-12-31` });
}
function summary(y: number): Summary {
  const list = yearOrders(y);
  const active = list.filter((o) => !o.cancelled);
  const spend = active.reduce((s, o) => s + (o.order_total ?? 0), 0);
  return {
    currency: 'EUR',
    year: y,
    spend,
    net_spend: spend - active.reduce((s, o) => s + (o.refund_total ?? 0), 0),
    orders: active.length,
    items: active.length,
    avg_order: active.length ? spend / active.length : 0,
    shipping_paid: active.reduce((s, o) => s + (o.shipping_total ?? 0), 0),
    refunds: active.reduce((s, o) => s + (o.refund_total ?? 0), 0),
    cancelled: list.filter((o) => o.cancelled).length,
    gift_card_used: active.length ? 75 : 0,
    coupon_savings: active.length ? 23.5 : 0
  };
}
function status(): Status {
  return {
    currency: 'EUR',
    state: mockControls.authRequired
      ? 'auth_required'
      : backfillState === 'running'
        ? 'backfilling'
        : 'idle',
    auth: mockAuthStatus(),
    backfill: { state: backfillState, year: year - 2, orders_processed: 96, progress: 68 },
    last_recent_sync: lastSync,
    next_recent_sync: new Date(Date.now() + 6 * 3600000).toISOString(),
    cooldown_until: null,
    last_error: null,
    counts: {
      orders: mockControls.empty ? 0 : 96,
      items: mockControls.empty ? 0 : 96,
      returns_open: mockControls.empty ? 0 : deadlines('return', 365).length,
      warranties_expiring_90d: mockControls.empty ? 0 : deadlines('warranty', 90).length
    }
  };
}
function deadlines(kind: string, within: number): Deadline[] {
  return (mockControls.empty ? [] : orders)
    .flatMap((o) =>
      o.items.flatMap((item) => {
        if (o.cancelled || item.item_state.status === 'returned') return [];
        return (['return', 'warranty'] as const).flatMap((k) => {
          const d = k === 'return' ? item.return_deadline : item.warranty_deadline;
          const left = d
            ? Math.round((Date.parse(d + 'T12:00:00') - today.getTime()) / 86400000)
            : -1;
          return d && left >= 0 && left <= within && (kind === 'all' || k === kind)
            ? [{ kind: k, deadline: d, days_left: left, item, order_number: o.order_number }]
            : [];
        });
      })
    )
    .sort((a, b) => a.deadline.localeCompare(b.deadline));
}
export async function mockRequest(path: string, options: RequestInit): Promise<unknown> {
  await new Promise((resolve) => setTimeout(resolve, 180));
  if (mockControls.failRequests)
    throw new Error('Demo: connection interrupted. Disable the error scenario in Settings.');
  const [route, query = ''] = path.split('?');
  const p = new URLSearchParams(query);
  const y = Number(p.get('year') || year);
  const body = options.body ? JSON.parse(String(options.body)) : {};
  if (route === 'status') return status();
  if (route === 'auth/status') return mockAuthStatus();
  if (route === 'auth/start') {
    try {
      localStorage.removeItem('amazon-orders-demo-complete');
    } catch {
      /* demo only */
    }
    mockControls.authInProgress = true;
    return { url: new URL('auth-demo.html', location.href).href };
  }
  if (route === 'auth/logout') {
    mockControls.authRequired = true;
    mockControls.authInProgress = false;
    return { ok: true };
  }
  if (route === 'settings')
    return {
      sync_preset: 'careful',
      recent_refresh_hours: 6,
      backfill_until_year: '',
      default_warranty_months: 24,
      return_thresholds: [7, 2, 0],
      warranty_thresholds: [180, 90, 60, 30, 14, 5],
      domain: 'amazon.it'
    };
  if (route === 'orders' || route === 'items') {
    const result = filtered(Object.fromEntries(p) as Filters);
    const page = Number(p.get('page') || 1);
    const pageSize = Number(p.get('page_size') || 12);
    return {
      currency: 'EUR',
      items: result
        .slice((page - 1) * pageSize, page * pageSize)
        .map((o) => (route === 'items' ? o.items[0] : o)),
      total: result.length,
      page,
      page_size: pageSize
    };
  }
  if (route.startsWith('orders/')) {
    const order = orders.find((o) => o.order_number === decodeURIComponent(route.split('/')[1]));
    if (!order) throw new Error('Order not found');
    return structuredClone(order);
  }
  if (/items\/\d+\/state/.test(route)) {
    const item = orders.flatMap((o) => o.items).find((i) => i.id === Number(route.split('/')[1]));
    if (!item) throw new Error('Item not found');
    Object.assign(item.item_state, body);
    const cancelled = orders.find((o) => o.order_number === item.order_number)?.cancelled;
    item.return_deadline =
      item.item_state.status === 'returned' || cancelled ? null : item.return_eligible_date;
    item.warranty_deadline =
      item.item_state.status === 'returned' || cancelled
        ? null
        : item.item_state.warranty_until_override ||
          months(item.delivered_date!, item.item_state.warranty_months_override || 24);
    return structuredClone(item);
  }
  if (route === 'deadlines')
    return {
      currency: 'EUR',
      items: deadlines(p.get('kind') || 'all', Number(p.get('within_days') || 365))
    };
  if (route === 'stats/yearly') {
    const ys = [...new Set(orders.map((o) => Number(o.placed_date.slice(0, 4))))].sort();
    const rows = ys.map((yy) => {
      const s = summary(yy);
      return { year: yy, orders: s.orders, items: s.items, spend: s.spend, refunds: s.refunds, net_spend: s.net_spend };
    });
    const sum = (k: 'spend' | 'refunds' | 'net_spend' | 'orders' | 'items') =>
      rows.reduce((t, r) => t + r[k], 0);
    return {
      currency: 'EUR',
      years: rows,
      total: {
        spend: sum('spend'), refunds: sum('refunds'), net_spend: sum('net_spend'),
        orders: sum('orders'), items: sum('items'),
        first_year: ys[0] ?? null, last_year: ys.at(-1) ?? null
      }
    };
  }
  if (route === 'stats/summary') return summary(y);
  if (route === 'stats/monthly') {
    const from = p.get('from') || `${year - 1}-01-01`;
    const to = p.get('to') || `${year}-12-31`;
    const rows = [];
    for (let yy = Number(from.slice(0, 4)); yy <= Number(to.slice(0, 4)); yy++)
      for (let m = 1; m <= 12; m++) {
        const month = `${yy}-${String(m).padStart(2, '0')}`;
        if (month < from.slice(0, 7) || month > to.slice(0, 7)) continue;
        const list = yearOrders(yy).filter((o) => !o.cancelled && o.placed_date.startsWith(month));
        rows.push({
          month,
          spend: list.reduce((s, o) => s + (o.order_total ?? 0), 0),
          net_spend: list.reduce((s, o) => s + (o.order_total ?? 0) - (o.refund_total ?? 0), 0),
          orders: list.length
        });
      }
    return { currency: 'EUR', items: rows };
  }
  if (route === 'stats/sellers') {
    const sellers = [
      ...new Set(
        yearOrders(y)
          .filter((o) => !o.cancelled)
          .map((o) => o.items[0].seller)
      )
    ];
    return {
      currency: 'EUR',
      items: sellers
        .map((seller) => {
          const list = yearOrders(y).filter((o) => !o.cancelled && o.items[0].seller === seller);
          return {
            seller,
            spend: list.reduce((s, o) => s + (o.order_total ?? 0), 0),
            count: list.length
          };
        })
        .sort((a, b) => b.spend - a.spend)
    };
  }
  if (route === 'stats/top-items')
    return {
      currency: 'EUR',
      items: yearOrders(y)
        .filter((o) => !o.cancelled)
        .flatMap((o) => o.items)
        .sort((a, b) => (b.price ?? 0) - (a.price ?? 0))
        .slice(0, 5)
    };
  if (route === 'stats/recurring')
    return {
      currency: 'EUR',
      items: mockControls.empty
        ? []
        : products.slice(2, 7).map((p, i) => ({
            asin: `DEMO${String(i + 2).padStart(6, '0')}`,
            title: p[0],
            count: 7 - i,
            first_date: offset(-610 - i * 10),
            last_date: offset(-18 - i * 4),
            price_min: p[2] - 2,
            price_max: p[2] + 4,
            price_last: p[2]
          }))
    };
  if (route === 'stats/returns') {
    const s = summary(y);
    const count = yearOrders(y).filter(
      (o) => !o.cancelled && o.items[0].item_state.status === 'returned'
    ).length;
    return { count, amount: s.refunds, return_rate: s.orders ? count / s.orders : 0 };
  }
  if (route === 'stats/weekday') {
    const list = filtered({}).filter((o) => !o.cancelled);
    return {
      items: Array.from({ length: 7 }, (_, weekday) => ({
        weekday,
        orders: list.filter(
          (o) => (new Date(o.placed_date + 'T12:00:00').getDay() + 6) % 7 === weekday
        ).length
      })),
      heatmap: Array.from({ length: 12 }, (_, m) =>
        Array.from({ length: 7 }, (_, weekday) => ({
          month: `${year}-${String(m + 1).padStart(2, '0')}`,
          weekday,
          orders: yearOrders(year).filter(
            (o) =>
              !o.cancelled &&
              new Date(o.placed_date + 'T12:00:00').getMonth() === m &&
              (new Date(o.placed_date + 'T12:00:00').getDay() + 6) % 7 === weekday
          ).length
        }))
      ).flat()
    };
  }
  if (route === 'sync/recent') {
    lastSync = new Date().toISOString();
    return {};
  }
  if (route === 'sync/backfill') {
    backfillState = body.action === 'pause' ? 'paused' : 'running';
    return {};
  }
  if (route === 'cache/purge') return { scope: body.scope, annotations_preserved: true };
  throw new Error(`Unimplemented demo endpoint: ${route}`);
}
export function mockCsv(filters: Filters): string {
  const escape = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  return (
    '\ufefforder_number,placed_date,title,seller,price,status\r\n' +
    filtered(filters)
      .map((o) =>
        [
          o.order_number,
          o.placed_date,
          o.items[0].title,
          o.items[0].seller,
          o.items[0].price,
          o.items[0].item_state.status
        ]
          .map(escape)
          .join(',')
      )
      .join('\r\n')
  );
}

export async function mockIcs(selection: { item_id: number; kind: string }[]): Promise<Blob> {
  const events = selection
    .map((s) => `BEGIN:VEVENT\r\nUID:demo-${s.item_id}-${s.kind}\r\nSUMMARY:Demo ${s.kind}\r\nEND:VEVENT`)
    .join('\r\n');
  return new Blob([`BEGIN:VCALENDAR\r\nVERSION:2.0\r\n${events}\r\nEND:VCALENDAR\r\n`], {
    type: 'text/calendar'
  });
}
