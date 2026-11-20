<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Deadline, Monthly, Order, Status, Summary } from '$lib/types';
  import { date, money, type Locale } from '$lib/i18n';
  import Icon from '$lib/components/Icon.svelte';
  import Countdown from '$lib/components/Countdown.svelte';
  import DataState from '$lib/components/DataState.svelte';
  import OrderRow from '$lib/components/OrderRow.svelte';
  import ProductImage from '$lib/components/ProductImage.svelte';
  import SpendChart from '$lib/components/SpendChart.svelte';
  let { locale, status }: { locale: Locale; status: Status | null } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  const year = new Date().getFullYear();
  let busy = $state(true),
    error = $state('');
  let summary = $state<Summary | null>(null),
    previousSummary = $state<Summary | null>(null);
  let monthly = $state<Monthly[]>([]),
    deadlines = $state<Deadline[]>([]),
    orders = $state<Order[]>([]);
  const net = (s: { spend: number; net_spend?: number } | null | undefined) =>
    s ? (s.net_spend ?? s.spend) : 0;
  const monthRow = $derived(
    monthly.find((m) => m.month === new Date().toLocaleDateString('en-CA').slice(0, 7)) ?? null
  );
  const monthSpend = $derived(monthRow ? (monthRow.net_spend ?? monthRow.spend) : 0);
  const change = $derived(
    net(previousSummary) ? (net(summary) / net(previousSummary) - 1) * 100 : null
  );
  async function load() {
    busy = true;
    error = '';
    try {
      const [s, p, m, d, o] = await Promise.all([
        api.summary(year),
        api.summary(year - 1),
        api.monthly(`${year - 1}-01-01`, `${year}-12-31`),
        api.deadlines('all', 90),
        api.orders({ page_size: 4 })
      ]);
      summary = s;
      previousSummary = p;
      monthly = m.items;
      deadlines = d.items;
      orders = o.items;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
  onMount(load);
</script>

{#snippet spending()}
  <div class="overview-spend">
    <div class="metric primary-metric">
      <span class="metric-label"
        ><Icon name="statistics" size={20} />{tr('Spent this month', 'Spesa del mese')}</span
      ><strong>{money(monthSpend, locale)}</strong><span
        >{new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(
          new Date()
        )}</span
      >
    </div>
    <div class="metric">
      <span class="metric-label">{tr('Spent this year', 'Spesa dell’anno')}</span><strong
        >{money(net(summary), locale)}</strong
      ><span
        >{#if change !== null}<Icon
            name={change < 0 ? 'decrease' : 'increase'}
            size={16}
          />{Math.abs(change).toFixed(1)}% {tr(
            change < 0 ? 'less than last year' : 'more than last year',
            change < 0 ? 'in meno rispetto all’anno scorso' : 'in più rispetto all’anno scorso'
          )}{:else}{tr('Your purchase history', 'Il tuo storico acquisti')}{/if}</span
      >
    </div>
  </div>
{/snippet}

<DataState {busy} {error} {locale} retry={load}>
  <div class="overview-grid">
    <section class="panel attention-panel">
      <div class="section-heading">
        <h2>{tr('Upcoming deadlines', 'Prossime scadenze')}</h2>
      </div>
      <div class="overview-deadline-counts">
        <a class="metric metric-link" href="#/deadlines"
          ><span class="metric-label"
            ><Icon name="return" size={20} />{tr('Still returnable', 'Ancora restituibili')}</span
          ><strong
            >{status?.counts.returns_open ??
              deadlines.filter((d) => d.kind === 'return').length}<Icon
              name="arrow"
              size={24}
            /></strong
          ><span>{tr('Check before the window closes', 'Controlla prima della scadenza')}</span></a
        >
        <a class="metric metric-link" href="#/deadlines?kind=warranty"
          ><span class="metric-label"
            ><Icon name="warranty" size={20} />{tr(
              'Warranties ending',
              'Garanzie in scadenza'
            )}</span
          ><strong
            >{status?.counts.warranties_expiring_90d ?? 0}<Icon name="arrow" size={24} /></strong
          ><span>{tr('In the next 90 days', 'Nei prossimi 90 giorni')}</span></a
        >
      </div>
      {#if deadlines.length}<div class="deadline-preview">
          {#each deadlines.slice(0, 3) as d}<a
              href={`#/orders/${d.order_number}`}
              class="deadline-preview-row"
              ><ProductImage src={d.item.image_link} title={d.item.title} />
              <div>
                <strong>{d.item.title}</strong><span
                  >{tr(
                    d.kind === 'return' ? 'Start a return by' : 'Warranty until',
                    d.kind === 'return' ? 'Avvia il reso entro il' : 'Garanzia fino al'
                  )}
                  {date(d.deadline, locale)}</span
                >
              </div>
              <Countdown deadline={d.deadline} kind={d.kind} {locale} /></a
            >{/each}
        </div>{:else}<div class="quiet-empty">
          <Icon name="success" size={32} />
          <p>{tr('Nothing needs your attention.', 'Nessuna scadenza imminente.')}</p>
        </div>{/if}
      <a class="text-link panel-footer" href="#/deadlines?kind=all"
        >{tr('View all deadlines', 'Vedi tutte le scadenze')}<Icon name="right" size={18} /></a
      >
    </section>
    <section class="panel">
      <div class="section-heading">
        <div>
          <h2>{tr('Your spending, month by month', 'La spesa, mese per mese')}</h2>
          <p>{tr('This year alongside the last', 'Quest’anno a confronto con il precedente')}</p>
        </div>
        <a
          href="#/statistics"
          class="icon-button"
          aria-label={tr('All statistics', 'Tutte le statistiche')}><Icon name="right" /></a
        >
      </div>
      {@render spending()}
      <SpendChart
        current={monthly.filter((m) => m.month.startsWith(String(year)))}
        previous={monthly.filter((m) => m.month.startsWith(String(year - 1)))}
        {year}
        {locale}
        compact
      />
    </section>
  </div>
  <section class="panel recent-panel">
    <div class="section-heading">
      <div>
        <h2>{tr('Recently ordered', 'Ordini recenti')}</h2>
        <p>{tr('The latest additions to your home', 'Gli ultimi acquisti per la tua casa')}</p>
      </div>
      <a href="#/orders" class="text-link"
        >{tr('All orders', 'Tutti gli ordini')}<Icon name="right" size={18} /></a
      >
    </div>
    {#each orders as order}<OrderRow {order} {locale} />{:else}<p class="quiet-empty">
        {tr(
          'Your orders will appear after your first sync.',
          'Gli ordini appariranno dopo la prima sincronizzazione.'
        )}
      </p>{/each}
  </section>
  <div class="privacy-note">
    <Icon name="warranty" size={17} />{tr(
      'Your history stays here. Nothing you do in this app changes an Amazon order.',
      'Lo storico resta qui. Nessuna azione in questa app modifica un ordine su Amazon.'
    )}
  </div>
</DataState>
