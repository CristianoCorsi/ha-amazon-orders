// Wire adapters match the Python repository API. UI models stay stable in mock mode.
import type { Deadline, Item, ItemState, Order, Page, Shipment, Status } from './types';
export interface WireItem extends Partial<Item> {
  state?: Partial<ItemState>;
  status?: ItemState['status'];
  deadlines?: { return?: { deadline: string | null }; warranty?: { deadline: string | null } };
  order?: { order_number?: string };
}
export interface WireOrder extends Omit<Partial<Order>, 'items'> {
  items?: WireItem[];
}
export interface WireOrderDetail {
  order: WireOrder;
  items: WireItem[];
  shipments: Shipment[];
}
export interface WireOrders {
  orders?: WireOrder[];
  items?: WireOrder[];
  total: number;
  page: number;
  page_size: number;
  currency: string;
}
export interface WireDeadlines {
  currency?: string;
  items?: Deadline[];
  deadlines?: (Omit<Deadline, 'item' | 'order_number'> & {
    item: WireItem;
    order?: { order_number: string };
  })[];
}
export interface WireStatus {
  state: string;
  currency?: string;
  auth: Partial<Status['auth']>;
  backfill: {
    state?: string;
    status?: string;
    year: number;
    orders_processed?: number;
    processed?: number;
    progress?: number | null;
    percent?: number | null;
  };
  counts: Partial<Status['counts']>;
  last_recent_sync?: string | null;
  last_recent?: { at: string } | null;
  next_recent_sync?: string | null;
  next_recent_at?: string | null;
  cooldown_until?: string | null;
  cooldown?: { until?: string } | null;
  last_error?: string | { message?: string; code?: string } | null;
}
/** Resolve a product link against amazon.it and keep it only if it is http(s). */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value, 'https://www.amazon.it');
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

export function normalizeItem(item: WireItem, orderNumber = ''): Item {
  return {
    id: item.id ?? 0,
    order_number: item.order_number || item.order?.order_number || orderNumber,
    asin: item.asin ?? null,
    title: item.title ?? '',
    price: item.price ?? null,
    quantity: item.quantity ?? 1,
    seller: item.seller ?? null,
    image_link: item.image_link ?? null,
    link: safeHttpUrl(item.link),
    return_eligible_date: item.return_eligible_date ?? null,
    delivered_date: item.delivered_date ?? null,
    return_deadline: item.deadlines?.return?.deadline ?? item.return_deadline ?? null,
    warranty_deadline: item.deadlines?.warranty?.deadline ?? item.warranty_deadline ?? null,
    item_state: {
      status: 'none',
      note: '',
      warranty_until_override: null,
      warranty_months_override: null,
      ...item.state,
      ...item.item_state,
      ...(item.status ? { status: item.status } : {})
    }
  };
}
export function normalizeOrder(raw: WireOrder | WireOrderDetail): Order {
  const detail = 'order' in raw ? raw : null;
  const order = detail?.order ?? (raw as WireOrder);
  return {
    order_number: order.order_number ?? '',
    placed_date: order.placed_date ?? '',
    grand_total: order.grand_total ?? null,
    shipping_total: order.shipping_total ?? null,
    refund_total: order.refund_total ?? null,
    cancelled: order.cancelled ?? false,
    items: (detail?.items ?? order.items ?? []).map((item) =>
      normalizeItem(item, order.order_number)
    ),
    shipments: detail?.shipments ?? order.shipments ?? []
  };
}
export function normalizeOrders(raw: WireOrders): Page<Order> {
  return { ...raw, items: (raw.orders ?? raw.items ?? []).map(normalizeOrder) };
}
export function normalizeDeadlines(raw: WireDeadlines): { currency: string; items: Deadline[] } {
  return {
    currency: raw.currency ?? 'EUR',
    items:
      raw.items ??
      (raw.deadlines ?? []).map((d) => ({
        ...d,
        item: normalizeItem(d.item),
        order_number: d.item.order_number ?? d.order?.order_number ?? ''
      }))
  };
}
export function normalizeStatus(raw: WireStatus, returnsOpen = 0, warranties = 0): Status {
  return {
    currency: raw.currency ?? 'EUR',
    state: raw.state,
    auth: {
      state: raw.auth.state ?? 'auth_required',
      method: raw.auth.method ?? null,
      expires_hint: raw.auth.expires_hint ?? null
    },
    backfill: {
      state: raw.backfill.state ?? raw.backfill.status ?? 'paused',
      year: raw.backfill.year,
      orders_processed: raw.backfill.orders_processed ?? raw.backfill.processed ?? 0,
      progress: raw.backfill.progress ?? raw.backfill.percent ?? null
    },
    last_recent_sync: raw.last_recent_sync ?? raw.last_recent?.at ?? null,
    next_recent_sync: raw.next_recent_sync ?? raw.next_recent_at ?? null,
    cooldown_until: raw.cooldown_until ?? raw.cooldown?.until ?? null,
    last_error:
      typeof raw.last_error === 'string'
        ? raw.last_error
        : (raw.last_error?.message ?? raw.last_error?.code ?? null),
    counts: {
      orders: raw.counts.orders ?? 0,
      items: raw.counts.items ?? 0,
      returns_open: raw.counts.returns_open ?? returnsOpen,
      warranties_expiring_90d: raw.counts.warranties_expiring_90d ?? warranties
    }
  };
}
