<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Order } from '$lib/types';
  import { date, money, orderAmount, type Locale } from '$lib/i18n';
  import Icon from '$lib/components/Icon.svelte';
  import DataState from '$lib/components/DataState.svelte';
  import ItemEditor from '$lib/components/ItemEditor.svelte';
  let { locale, id }: { locale: Locale; id: string } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  let busy = $state(true),
    error = $state(''),
    order = $state<Order | null>(null);
  async function refresh() {
    order = await api.order(id);
  }
  async function load() {
    busy = true;
    error = '';
    try {
      await refresh();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
  onMount(load);
</script>

<a href="#/orders" class="text-link back-link"
  ><Icon name="back" size={19} />{tr('Back to orders', 'Torna agli ordini')}</a
>
<DataState {busy} {error} {locale} retry={load}
  >{#if order}<div class="order-summary">
      <div>
        <span class="muted-text">{tr('Order', 'Ordine')}</span>
        <h2>{order.order_number}</h2>
        {#if order.cancelled}<span class="chip muted">{tr('Cancelled', 'Annullato')}</span>{/if}
        <p>
          {tr('Placed', 'Effettuato il')}
          {date(order.placed_date, locale)}<span>
            / {order.cancelled
              ? tr('Cancelled', 'Annullato')
              : order.shipments.length && order.shipments.every((s) => s.delivered_date)
                ? tr('Delivered', 'Consegnato')
                : tr('Delivery status unknown', 'Stato della consegna sconosciuto')}</span
          >
        </p>
      </div>
      <div class="order-summary-total">
        <span>{tr('Order total', 'Totale ordine')}</span><strong
          class:cancelled-amount={order.cancelled}
          class:struck-amount={order.cancelled && order.order_total != null}
          >{orderAmount(order.order_total, order.cancelled, locale)}</strong
        ><small>{tr('Shipping', 'Spedizione')}: {money(order.shipping_total, locale)}</small>
        {#if order.paid_with_balance}<small
            >{tr('Paid with Amazon balance', 'Pagato con saldo Amazon')}: {money(
              order.paid_with_balance,
              locale
            )}</small
          >{/if}
        {#if order.refund_total}<small class="refund-amount"
            >{tr('Refunded', 'Rimborsato')}: −{money(order.refund_total, locale)}</small
          >{/if}
      </div>
    </div>
    {#each order.items as item (item.id)}<ItemEditor
        {item}
        {locale}
        cancelled={order.cancelled}
        placed={order.placed_date}
        onSaved={refresh}
      />{/each}{/if}</DataState
>
