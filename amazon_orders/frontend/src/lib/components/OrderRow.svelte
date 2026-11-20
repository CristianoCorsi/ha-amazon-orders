<script lang="ts">
  import type { Order } from '$lib/types';
  import { date, orderAmount, type Locale } from '$lib/i18n';
  import Icon from './Icon.svelte';
  import ProductImage from './ProductImage.svelte';
  import Countdown from './Countdown.svelte';
  let { order, locale }: { order: Order; locale: Locale } = $props();
  const item = $derived(order.items[0]);
</script>

<a class="order-row" href={`#/orders/${encodeURIComponent(order.order_number)}`}>
  <ProductImage src={item?.image_link} title={item?.title ?? order.order_number} />
  <div class="order-row-main">
    <strong>{item?.title ?? order.order_number}</strong><span
      >{item?.seller ??
        (locale === 'it' ? 'Venditore sconosciuto' : 'Unknown seller')}{#if order.items.length > 1}
        · +{order.items.length - 1} {locale === 'it' ? 'articoli' : 'items'}{/if}</span
    ><small
      >{date(order.placed_date, locale)}
      <span class="order-number">/ {order.order_number}</span></small
    >
  </div>
  <div class="order-row-state">
    {#if order.cancelled}<span class="chip muted"
        >{locale === 'it' ? 'Annullato' : 'Cancelled'}</span
      >{:else if item?.item_state.status === 'returned'}<span class="chip muted"
        ><Icon name="check" size={14} />{locale === 'it' ? 'Restituito' : 'Returned'}</span
      >{:else if item?.return_deadline}<Countdown
        deadline={item.return_deadline}
        {locale}
      />{:else if item?.item_state.status === 'keep'}<span class="chip"
        ><Icon name="check" size={14} />{locale === 'it' ? 'Da tenere' : 'Keeping'}</span
      >{/if}
  </div>
  <strong
    class="order-price"
    class:cancelled-amount={order.cancelled}
    class:struck-amount={order.cancelled && order.order_total != null}
    >{orderAmount(order.order_total, order.cancelled, locale)}</strong
  ><span class="row-chevron"><Icon name="chevron" size={20} /></span>
</a>
