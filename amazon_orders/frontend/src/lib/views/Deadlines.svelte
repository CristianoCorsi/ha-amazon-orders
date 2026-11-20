<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { api } from '$lib/api';
  import type { Deadline } from '$lib/types';
  import { date, type Locale } from '$lib/i18n';
  import Icon from '$lib/components/Icon.svelte';
  import DataState from '$lib/components/DataState.svelte';
  import ProductImage from '$lib/components/ProductImage.svelte';
  import Countdown from '$lib/components/Countdown.svelte';
  let { locale, initialKind = 'return' }: { locale: Locale; initialKind?: string } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  let kind = $state(untrack(() => initialKind)),
    within = $state('90'),
    busy = $state(true),
    error = $state(''),
    ready = $state(false);
  let deadlines = $state<Deadline[]>([]);
  const groups = $derived([...new Set(deadlines.map((d) => d.deadline.slice(0, 7)))]);
  let request = 0;
  async function load() {
    const current = ++request;
    busy = true;
    error = '';
    try {
      const d = await api.deadlines(kind, Number(within));
      if (current === request) deadlines = d.items;
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
    void kind;
    void within;
    if (ready) load();
  });
</script>

<div class="view-controls">
  <div class="segmented" aria-label={tr('Deadline type', 'Tipo scadenza')}>
    <button
      class:active={kind === 'return'}
      aria-pressed={kind === 'return'}
      onclick={() => (kind = 'return')}
      ><Icon name="return" size={19} />{tr('Return windows', 'Finestre di reso')}</button
    ><button
      class:active={kind === 'warranty'}
      aria-pressed={kind === 'warranty'}
      onclick={() => (kind = 'warranty')}
      ><Icon name="warranty" size={19} />{tr('Warranties', 'Garanzie')}</button
    >
  </div>
  <label class="sort-control"
    >{tr('Show next', 'Prossimi')}<select bind:value={within}
      ><option value="30">30 {tr('days', 'giorni')}</option><option value="90"
        >90 {tr('days', 'giorni')}</option
      ><option value="365">{tr('12 months', '12 mesi')}</option><option value="1095"
        >{tr('3 years', '3 anni')}</option
      ></select
    ></label
  >
</div>
<div class="info-strip">
  <Icon name="info" size={20} />
  <p>
    {kind === 'return'
      ? tr(
          'Return dates come from Amazon, not a fixed 30-day estimate. Returned and cancelled items are excluded.',
          'Le date dei resi arrivano da Amazon, non da una stima fissa di 30 giorni. Articoli restituiti e annullati sono esclusi.'
        )
      : tr(
          'A 2-year warranty starts on delivery, or the order date when delivery is unknown. Your overrides take priority.',
          'La garanzia di 2 anni parte dalla consegna, o dall’ordine se la consegna è sconosciuta. Le tue modifiche hanno priorità.'
        )}
  </p>
</div>
<DataState {busy} {error} {locale} retry={load}>
  {#if deadlines.length}<div class="timeline">
      {#each groups as group}<section class="timeline-month">
          <h2>
            <span class="timeline-dot"></span>{new Intl.DateTimeFormat(locale, {
              month: 'long',
              year: 'numeric'
            }).format(new Date(group + '-15T12:00:00'))}
          </h2>
          <div class="panel">
            {#each deadlines.filter((d) => d.deadline.startsWith(group)) as d}<a
                class="timeline-row"
                href={`#/orders/${d.order_number}`}
                ><div class="date-tile">
                  <strong>{Number(d.deadline.slice(8))}</strong><span
                    >{new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(
                      new Date(d.deadline + 'T12:00:00')
                    )}</span
                  >
                </div>
                <ProductImage src={d.item.image_link} title={d.item.title} />
                <div class="timeline-content">
                  <strong>{d.item.title}</strong><span>{d.item.seller}</span><small
                    >{tr('Order', 'Ordine')} {d.order_number}</small
                  >
                </div>
                <Countdown deadline={d.deadline} kind={d.kind} {locale} /><span class="row-chevron"
                  ><Icon name="chevron" size={20} /></span
                ></a
              >{/each}
          </div>
        </section>{/each}
    </div>
  {:else}<div class="empty-state">
      <span class="empty-icon"><Icon name="warranty" size={36} /></span>
      <h2>{tr('You’re all clear', 'Nessuna scadenza in vista')}</h2>
      <p>
        {tr(
          'No active deadlines in this window. Choose a longer period to see what’s further ahead.',
          'Non ci sono scadenze attive in questo periodo. Seleziona un intervallo più lungo per vedere le successive.'
        )}
      </p>
    </div>{/if}
</DataState>
