<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Item, Monthly, Recurring, Returns, Seller, Summary, Weekday } from '$lib/types';
  import { date, money, type Locale } from '$lib/i18n';
  import Icon from '$lib/components/Icon.svelte';
  import DataState from '$lib/components/DataState.svelte';
  import ProductImage from '$lib/components/ProductImage.svelte';
  import SpendChart from '$lib/components/SpendChart.svelte';
  let { locale }: { locale: Locale } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  const thisYear = new Date().getFullYear();
  let year = $state(thisYear),
    ready = $state(false),
    busy = $state(true),
    error = $state('');
  let summary = $state<Summary | null>(null),
    previous = $state<Summary | null>(null),
    monthly = $state<Monthly[]>([]),
    sellers = $state<Seller[]>([]),
    top = $state<Item[]>([]),
    recurring = $state<Recurring[]>([]),
    returns = $state<Returns | null>(null),
    weekday = $state<Weekday[]>([]),
    heatmap = $state<{ month: string; weekday: number; orders: number }[]>([]);
  const weekdays = $derived(
    Array.from({ length: 7 }, (_, i) =>
      new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2026, 0, 5 + i))
    )
  );
  const change = $derived(
    previous?.spend ? ((summary?.spend ?? 0) / previous.spend - 1) * 100 : null
  );
  const sellerMax = $derived(Math.max(...sellers.map((s) => s.spend), 1));
  const weekdayMax = $derived(Math.max(...weekday.map((w) => w.orders), 1));
  let request = 0;
  async function load() {
    const current = ++request;
    busy = true;
    error = '';
    try {
      const [s, p, m, se, t, r, re, w] = await Promise.all([
        api.summary(year),
        api.summary(year - 1),
        api.monthly(`${year - 1}-01-01`, `${year}-12-31`),
        api.sellers(year),
        api.topItems(year),
        api.recurring(),
        api.returns(year),
        api.weekday()
      ]);
      if (current !== request) return;
      summary = s;
      previous = p;
      monthly = m.items;
      sellers = se.items;
      top = t.items;
      recurring = r.items;
      returns = re;
      weekday = w.items;
      heatmap = w.heatmap;
    } catch (e) {
      if (current === request) error = (e as Error).message;
    } finally {
      if (current === request) busy = false;
    }
  }
  onMount(() => {
    ready = true;
  });
  $effect(() => {
    void year;
    if (ready) load();
  });
</script>

<div class="view-controls">
  <p class="muted-text">{tr('Understand what comes home.', 'Conosci meglio i tuoi acquisti.')}</p>
  <label class="year-select"
    ><Icon name="calendar" size={19} /><span class="sr-only">{tr('Year', 'Anno')}</span><select
      bind:value={year}
      >{#each Array.from({ length: 10 }, (_, i) => thisYear - i) as y}<option value={y}>{y}</option
        >{/each}</select
    ></label
  >
</div>
<DataState {busy} {error} {locale} retry={load}>
  <section class="metrics stats-metrics">
    <div class="metric primary-metric">
      <span class="metric-label">{tr('Total spending', 'Spesa totale')}</span><strong
        >{money(summary?.spend, locale)}</strong
      ><span
        >{#if change !== null}<Icon
            name={change < 0 ? 'decrease' : 'increase'}
            size={16}
          />{Math.abs(change).toFixed(1)}% {tr(
            change < 0 ? 'less than' : 'more than',
            change < 0 ? 'in meno del' : 'in più del'
          )}
          {year - 1}{:else}{year}{/if}</span
      >
    </div>
    <div class="metric">
      <span class="metric-label">{tr('Orders placed', 'Ordini effettuati')}</span><strong
        >{summary?.orders ?? 0}</strong
      ><span>{summary?.items ?? 0} {tr('items in your history', 'articoli nello storico')}</span>
    </div>
    <div class="metric">
      <span class="metric-label">{tr('Average order', 'Ordine medio')}</span><strong
        >{money(summary?.avg_order, locale)}</strong
      ><span>{tr('Excluding cancelled orders', 'Esclusi gli ordini annullati')}</span>
    </div>
    <div class="metric">
      <span class="metric-label">{tr('Shipping paid', 'Spese di spedizione')}</span><strong
        >{money(summary?.shipping_paid, locale)}</strong
      ><span>{tr('Across all orders this year', 'Su tutti gli ordini dell’anno')}</span>
    </div>
  </section>
  <section class="panel full-chart">
    <div class="section-heading">
      <div>
        <h2>{tr('The shape of your spending', 'L’andamento della spesa')}</h2>
        <p>{tr('Monthly totals, year over year', 'Totali mensili, anno su anno')}</p>
      </div>
      <span class="chip muted">EUR</span>
    </div>
    <SpendChart
      current={monthly.filter((m) => m.month.startsWith(String(year)))}
      previous={monthly.filter((m) => m.month.startsWith(String(year - 1)))}
      {year}
      {locale}
    />
    <details class="chart-data">
      <summary>{tr('View chart data', 'Visualizza i dati del grafico')}</summary>
      <div class="table-scroll">
        <table>
          <caption class="sr-only">{tr('Monthly spending', 'Spesa mensile')}</caption><thead
            ><tr
              ><th>{tr('Month', 'Mese')}</th><th>{tr('Spending', 'Spesa')}</th><th
                >{tr('Orders', 'Ordini')}</th
              ></tr
            ></thead
          ><tbody
            >{#each monthly as m}<tr
                ><td>{m.month}</td><td>{money(m.spend, locale)}</td><td>{m.orders}</td></tr
              >{/each}</tbody
          >
        </table>
      </div>
    </details>
  </section>
  <div class="stats-grid">
    <section class="panel">
      <div class="section-heading">
        <div>
          <h2>{tr('Where you shop', 'Dove acquisti')}</h2>
          <p>{tr('Spending by seller', 'Spesa per venditore')}</p>
        </div>
        <Icon name="orders" size={22} />
      </div>
      <div class="seller-list">
        {#each sellers as seller, i}<div class="seller-row">
            <span class="seller-rank">{String(i + 1).padStart(2, '0')}</span>
            <div>
              <div class="seller-label">
                <strong>{seller.seller}</strong><strong>{money(seller.spend, locale)}</strong>
              </div>
              <div class="seller-bar" style={`--bar: ${(seller.spend / sellerMax) * 100}%`}></div>
              <small>{seller.count} {tr('purchases', 'acquisti')}</small>
            </div>
          </div>{:else}<p class="quiet-empty">
            {tr('No spending in this year.', 'Nessuna spesa in questo anno.')}
          </p>{/each}
      </div>
    </section>
    <section class="panel">
      <div class="section-heading">
        <div>
          <h2>{tr('The bigger purchases', 'Gli acquisti importanti')}</h2>
          <p>{tr('Your highest-priced items', 'Gli articoli dal prezzo più alto')}</p>
        </div>
        <Icon name="arrow" size={22} />
      </div>
      {#each top as item}<a class="compact-product" href={`#/orders/${item.order_number}`}
          ><ProductImage src={item.image_link} title={item.title} />
          <div><strong>{item.title}</strong><span>{item.seller}</span></div>
          <strong>{money(item.price, locale)}</strong></a
        >{:else}<p class="quiet-empty">
          {tr('No items to show.', 'Nessun articolo da mostrare.')}
        </p>{/each}
    </section>
  </div>
  <div class="stats-grid">
    <section class="panel">
      <div class="section-heading">
        <div>
          <h2>{tr('Bought again', 'Acquisti ricorrenti')}</h2>
          <p>
            {tr(
              'Familiar favourites across your history',
              'Gli articoli acquistati più volte nello storico'
            )}
          </p>
        </div>
        <Icon name="sync" size={22} />
      </div>
      {#each recurring as item}<div class="recurring-row">
          <span class="count-bubble">{item.count}×</span>
          <div>
            <strong>{item.title}</strong><small
              >{date(item.first_date, locale)} → {date(item.last_date, locale)}</small
            ><span
              >{tr('Price range', 'Fascia di prezzo')}: {money(item.price_min, locale)} - {money(
                item.price_max,
                locale
              )}</span
            >
          </div>
          <div class="recurring-price">
            <strong>{money(item.price_last, locale)}</strong><small
              >{tr('last paid', 'ultimo prezzo')}</small
            >
          </div>
        </div>{:else}<p class="quiet-empty">
          {tr('No recurring purchases yet.', 'Nessun acquisto ricorrente per ora.')}
        </p>{/each}
    </section>
    <section class="panel refund-panel">
      <div class="section-heading">
        <div>
          <h2>{tr('Returns & savings', 'Resi e risparmi')}</h2>
          <p>{tr('The other side of your spending', 'L’altro lato della spesa')}</p>
        </div>
        <Icon name="return" size={22} />
      </div>
      <div class="refund-feature">
        <span>{tr('Refunded', 'Rimborsato')}</span><strong>{money(returns?.amount, locale)}</strong
        ><span
          >{returns?.count ?? 0}
          {tr('returns', 'resi')} / {new Intl.NumberFormat(locale, {
            style: 'percent',
            maximumFractionDigits: 1
          }).format(returns?.return_rate ?? 0)}
          {tr('return rate', 'tasso di reso')}</span
        >
      </div>
      <dl class="key-values">
        <div>
          <dt>{tr('Gift cards used', 'Buoni regalo utilizzati')}</dt>
          <dd>{money(summary?.gift_card_used, locale)}</dd>
        </div>
        <div>
          <dt>{tr('Coupon savings', 'Risparmio con coupon')}</dt>
          <dd>{money(summary?.coupon_savings, locale)}</dd>
        </div>
        <div>
          <dt>{tr('Cancelled orders', 'Ordini annullati')}</dt>
          <dd>{summary?.cancelled ?? 0}</dd>
        </div>
      </dl>
    </section>
  </div>
  <section class="panel weekday-panel">
    <div class="section-heading">
      <div>
        <h2>{tr('Your shopping rhythm', 'Il ritmo dei tuoi acquisti')}</h2>
        <p>
          {tr(
            'Orders by weekday, across your history',
            'Ordini per giorno della settimana, su tutto lo storico'
          )}
        </p>
      </div>
      <Icon name="calendar" size={22} />
    </div>
    <div
      class="weekday-bars"
      role="img"
      aria-label={tr('Orders by weekday', 'Ordini per giorno della settimana')}
    >
      {#each weekday as w}<div>
          <span>{w.orders}</span>
          <div class="weekday-column" style={`--height: ${(w.orders / weekdayMax) * 100}%`}></div>
          <strong>{weekdays[w.weekday]}</strong>
        </div>{/each}
    </div>
    <div class="heatmap">
      <h3>{tr('Monthly pattern, all years', 'Distribuzione mensile, tutti gli anni')}</h3>
      <p class="muted-text">
        {tr(
          'Orders per weekday and month. Darker cells mean more orders.',
          'Ordini per giorno e mese. Le celle più scure indicano più ordini.'
        )}
      </p>
      <!-- Keyboard focus lets small-screen users scroll the data table without a pointer. -->
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div
        class="heatmap-scroll"
        tabindex="0"
        role="region"
        aria-label={tr(
          'Monthly order counts, scroll horizontally on small screens',
          'Ordini mensili, scorri in orizzontale sugli schermi piccoli'
        )}
      >
        <table class="heatmap-table">
          <caption class="sr-only"
            >{tr(
              'Orders by month and weekday, all years',
              'Ordini per mese e giorno della settimana, tutti gli anni'
            )}</caption
          >
          <thead
            ><tr
              ><th scope="col"><span class="sr-only">{tr('Weekday', 'Giorno')}</span></th
              >{#each Array.from({ length: 12 }, (_, i) => i + 1) as month}<th scope="col"
                  >{new Intl.DateTimeFormat(locale, { month: 'short' }).format(
                    new Date(year, month - 1, 1)
                  )}</th
                >{/each}</tr
            ></thead
          >
          <tbody
            >{#each weekdays as day, index}<tr
                ><th scope="row">{day}</th
                >{#each Array.from({ length: 12 }, (_, i) => i + 1) as month}{@const count =
                    heatmap.find(
                      (h) =>
                        h.month.slice(-2) === String(month).padStart(2, '0') && h.weekday === index
                    )?.orders ?? 0}<td
                    ><span class="heatmap-cell" style={`--intensity:${Math.min(count / 3, 1)}`}
                      >{count}</span
                    ></td
                  >{/each}</tr
              >{/each}</tbody
          >
        </table>
      </div>
    </div>
  </section>
</DataState>
