import { it, expect } from 'vitest';
import { normalizeItem, normalizeOrders, normalizeDeadlines, normalizeStatus } from './wire';
it('adapts nested backend item annotations and deadlines without fabricating dates', () => {
  const item = normalizeItem({
    id: 7,
    title: 'Synthetic lamp',
    state: { status: 'keep', note: 'Test' },
    deadlines: { return: { deadline: '2026-11-20' }, warranty: { deadline: '2029-11-01' } },
    order: { order_number: 'SYNTH-7' }
  });
  expect(item.item_state.status).toBe('keep');
  expect(item.return_deadline).toBe('2026-11-20');
  expect(item.order_number).toBe('SYNTH-7');
  expect(normalizeItem({ id: 8, title: 'Unknown' }).warranty_deadline).toBeNull();
});
it('rejects script links returned in product metadata', () => {
  expect(normalizeItem({ id: 9, title: 'Synthetic', link: 'javascript:alert(1)' }).link).toBeNull();
});
it('adapts paginated orders and compact list items', () => {
  const page = normalizeOrders({
    currency: 'EUR',
    orders: [
      {
        order_number: 'SYNTH-7',
        placed_date: '2026-11-01',
        items: [{ id: 7, title: 'Synthetic lamp', status: 'to_return' }]
      }
    ],
    total: 1,
    page: 1,
    page_size: 12
  });
  expect(page.items[0].items[0].item_state.status).toBe('to_return');
  expect(page.items[0].items[0].order_number).toBe('SYNTH-7');
});
it('adapts deadline envelopes and backfill cursors', () => {
  const dl = normalizeDeadlines({
    deadlines: [
      {
        kind: 'return',
        deadline: '2026-11-20',
        days_left: 5,
        item: { id: 7, title: 'Lamp', order_number: 'SYNTH-7' }
      }
    ]
  });
  expect(dl.items[0].order_number).toBe('SYNTH-7');
  const status = normalizeStatus(
    {
      state: 'idle',
      auth: { state: 'ok' },
      backfill: { status: 'paused', processed: 32, year: 2024, percent: null },
      counts: { orders: 32, items: 40 },
      last_recent: { at: '2026-11-15T10:00:00' }
    },
    6,
    2
  );
  expect(status.backfill.state).toBe('paused');
  expect(status.backfill.progress).toBeNull();
  expect(status.backfill.orders_processed).toBe(32);
  expect(status.counts.returns_open).toBe(6);
  expect(status.last_recent_sync).toBe('2026-11-15T10:00:00');
});
