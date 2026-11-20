export type ItemStatus = 'none' | 'keep' | 'to_return' | 'returned';
export interface ItemState {
  status: ItemStatus;
  note: string;
  warranty_until_override: string | null;
  warranty_months_override: number | null;
}
export interface Item {
  id: number;
  order_number: string;
  asin: string | null;
  title: string;
  price: number | null;
  quantity: number;
  seller: string | null;
  image_link: string | null;
  link: string | null;
  return_eligible_date: string | null;
  delivered_date: string | null;
  return_deadline: string | null;
  warranty_deadline: string | null;
  item_state: ItemState;
}
export interface Shipment {
  id: number;
  status_text: string | null;
  delivered_date: string | null;
}
export interface Order {
  order_number: string;
  placed_date: string;
  /** Full cost of the order, including what was paid with Amazon/gift-card balance. */
  order_total: number | null;
  /** Amount charged to the payment card (Amazon's "Grand Total"). */
  grand_total: number | null;
  paid_with_balance: number | null;
  shipping_total: number | null;
  refund_total: number | null;
  cancelled: boolean;
  items: Item[];
  shipments: Shipment[];
}
export interface Page<T> {
  currency: string;
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface AuthStatus {
  state: 'ok' | 'auth_required' | 'in_progress';
  method: 'device' | 'cookies' | null;
  expires_hint: string | null;
  login_url?: string;
  last_error?: string;
}
export interface Status {
  currency: string;
  state: string;
  auth: AuthStatus;
  backfill: { state: string; year: number; orders_processed: number; progress: number | null };
  last_recent_sync: string | null;
  next_recent_sync: string | null;
  cooldown_until: string | null;
  last_error: string | null;
  counts: { orders: number; items: number; returns_open: number; warranties_expiring_90d: number };
}
export interface Summary {
  currency: string;
  year: number;
  spend: number;
  net_spend: number;
  orders: number;
  items: number;
  avg_order: number;
  shipping_paid: number;
  refunds: number;
  cancelled: number;
  gift_card_used: number;
  coupon_savings: number;
}
export interface Monthly {
  month: string;
  spend: number;
  refunds?: number;
  net_spend?: number;
  orders: number;
}
export interface Seller {
  seller: string;
  spend: number;
  count: number;
}
export interface Recurring {
  asin: string;
  title: string;
  count: number;
  first_date: string;
  last_date: string;
  price_min: number;
  price_max: number;
  price_last: number;
}
export interface Returns {
  count: number;
  amount: number;
  return_rate: number;
}
export interface Weekday {
  weekday: number;
  orders: number;
}
export interface Deadline {
  kind: 'return' | 'warranty';
  deadline: string;
  days_left: number;
  item: Item;
  order_number: string;
}
export interface Settings {
  sync_preset: string;
  recent_refresh_hours: number;
  backfill_until_year: string;
  default_warranty_months: number;
  return_thresholds: number[];
  warranty_thresholds: number[];
  domain: string;
}
export interface Filters {
  q?: string;
  from?: string;
  to?: string;
  seller?: string;
  status?: string;
  min?: string;
  max?: string;
  sort?: string;
  page?: number;
  page_size?: number;
}
export interface YearRow {
  year: number;
  orders: number;
  items: number;
  spend: number;
  refunds: number;
  net_spend: number;
}
export interface Yearly {
  currency: string;
  years: YearRow[];
  total: {
    spend: number;
    refunds: number;
    net_spend: number;
    orders: number;
    items: number;
    first_year: number | null;
    last_year: number | null;
  };
}
