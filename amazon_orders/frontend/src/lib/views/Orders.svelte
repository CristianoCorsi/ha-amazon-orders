<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Order, Seller } from '$lib/types';
  import type { Locale } from '$lib/i18n';
  import Icon from '$lib/components/Icon.svelte';
  import DataState from '$lib/components/DataState.svelte';
  import OrderRow from '$lib/components/OrderRow.svelte';
  let { locale }: { locale: Locale } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  let q = $state(''),
    status = $state(''),
    seller = $state(''),
    from = $state(''),
    to = $state(''),
    min = $state(''),
    max = $state(''),
    sort = $state('date_desc');
  let showFilters = $state(false),
    busy = $state(true),
    loadingMore = $state(false),
    error = $state('');
  let orders = $state<Order[]>([]),
    sellers = $state<Seller[]>([]),
    total = $state(0),
    page = $state(1),
    ready = $state(false);
  let request = 0;
  const filters = $derived({ q, status, seller, from, to, min, max, sort, page_size: 12 });
  async function load(more = false) {
    const current = ++request;
    if (more) loadingMore = true;
    else busy = true;
    error = '';
    try {
      const data = await api.orders({ ...filters, page: more ? page + 1 : 1 });
      if (current !== request) return;
      orders = more ? [...orders, ...data.items] : data.items;
      total = data.total;
      page = data.page;
    } catch (e) {
      if (current === request) error = (e as Error).message;
    } finally {
      if (current === request) {
        busy = false;
        loadingMore = false;
      }
    }
  }
  onMount(() => {
    ready = true;
    api
      .sellers(new Date().getFullYear())
      .then((s) => (sellers = s.items))
      .catch(() => {});
  });
  $effect(() => {
    const currentFilters = filters;
    if (!ready) return;
    const timer = setTimeout(() => {
      void currentFilters;
      load();
    }, 300);
    return () => clearTimeout(timer);
  });
  function reset() {
    q = '';
    status = '';
    seller = '';
    from = '';
    to = '';
    min = '';
    max = '';
    sort = 'date_desc';
  }
  async function exportCsv() {
    try {
      const url = await api.exportCsv(filters);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'amazon-orders.csv';
      a.click();
      if (url.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<div class="toolbar">
  <div class="search-field">
    <Icon name="search" /><label class="sr-only" for="order-search"
      >{tr('Search orders', 'Cerca ordini')}</label
    ><input
      id="order-search"
      type="search"
      bind:value={q}
      placeholder={tr(
        'Search a product, seller or order number',
        'Cerca prodotto, venditore o numero ordine'
      )}
    /><kbd>/</kbd>
  </div>
  <button
    class="button secondary"
    class:selected={showFilters}
    onclick={() => (showFilters = !showFilters)}
    aria-expanded={showFilters}
    ><Icon name="filter" size={19} />{tr(
      'Filters',
      'Filtri'
    )}{#if status || seller || from || to || min || max}<span class="filter-dot"
      ></span>{/if}</button
  ><button
    class="icon-button export-action"
    aria-label={tr('Export filtered orders as CSV', 'Esporta ordini filtrati in CSV')}
    onclick={exportCsv}><Icon name="download" /></button
  >
</div>
{#if showFilters}<section
    class="filter-panel panel"
    aria-label={tr('Order filters', 'Filtri ordini')}
  >
    <div class="field">
      <label for="status">{tr('Item status', 'Stato articolo')}</label><select
        id="status"
        bind:value={status}
        ><option value="">{tr('All statuses', 'Tutti gli stati')}</option><option value="keep"
          >{tr('Keeping', 'Da tenere')}</option
        ><option value="to_return">{tr('To return', 'Da restituire')}</option><option
          value="returned">{tr('Returned', 'Restituito')}</option
        ><option value="cancelled">{tr('Cancelled', 'Annullato')}</option></select
      >
    </div>
    <div class="field">
      <label for="seller">{tr('Seller', 'Venditore')}</label><select id="seller" bind:value={seller}
        ><option value="">{tr('All sellers', 'Tutti i venditori')}</option
        >{#each sellers as s}<option value={s.seller}>{s.seller}</option>{/each}</select
      >
    </div>
    <div class="field">
      <label for="from">{tr('From date', 'Dal')}</label><input
        id="from"
        type="date"
        bind:value={from}
      />
    </div>
    <div class="field">
      <label for="to">{tr('To date', 'Al')}</label><input id="to" type="date" bind:value={to} />
    </div>
    <div class="field">
      <label for="min">{tr('Minimum €', 'Minimo €')}</label><input
        id="min"
        type="number"
        min="0"
        step="0.01"
        bind:value={min}
      />
    </div>
    <div class="field">
      <label for="max">{tr('Maximum €', 'Massimo €')}</label><input
        id="max"
        type="number"
        min="0"
        step="0.01"
        bind:value={max}
      />
    </div>
    <button class="text-link" onclick={reset}>{tr('Reset filters', 'Azzera filtri')}</button>
  </section>{/if}
<div class="list-heading">
  <p aria-live="polite">
    {total}
    {tr('orders', 'ordini')}{#if q}<span> {tr('matching', 'per')} “{q}”</span>{/if}
  </p>
  <label class="sort-control"
    >{tr('Sort by', 'Ordina per')}<select
      aria-label={tr('Sort orders', 'Ordina ordini')}
      bind:value={sort}
      ><option value="date_desc">{tr('Newest first', 'Più recenti')}</option><option
        value="date_asc">{tr('Oldest first', 'Meno recenti')}</option
      ><option value="price_desc">{tr('Highest price', 'Prezzo più alto')}</option></select
    ></label
  >
</div>
<DataState {busy} {error} {locale} empty={!orders.length} retry={() => load()}
  ><section class="panel order-list" aria-label={tr('Orders', 'Ordini')}>
    {#each orders as order (order.order_number)}<OrderRow {order} {locale} />{/each}
  </section>
  {#if orders.length < total}<div class="load-more">
      <button class="button secondary" disabled={loadingMore} onclick={() => load(true)}
        >{loadingMore
          ? tr('Loading…', 'Caricamento…')
          : tr('Load more orders', 'Carica altri ordini')}<Icon name="down" size={18} /></button
      ><small>{orders.length} / {total}</small>
    </div>{/if}</DataState
>
<svelte:window
  onkeydown={(e) => {
    if (
      e.key === '/' &&
      !['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)
    ) {
      e.preventDefault();
      document.getElementById('order-search')?.focus();
    }
  }}
/>
