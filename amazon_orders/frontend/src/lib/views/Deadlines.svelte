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
  // Selection survives switching tabs: key = "<kind>:<item id>".
  let selected = $state<Record<string, Deadline>>({});
  let reminders = $state(true),
    exporting = $state(false),
    exportError = $state('');
  const keyOf = (d: Deadline) => `${d.kind}:${d.item.id}`;
  const count = $derived(Object.keys(selected).length);
  const allVisibleSelected = $derived(
    deadlines.length > 0 && deadlines.every((d) => keyOf(d) in selected)
  );
  function toggle(d: Deadline) {
    const k = keyOf(d);
    if (k in selected) {
      const { [k]: _, ...rest } = selected;
      selected = rest;
    } else selected = { ...selected, [k]: d };
  }
  function toggleAll() {
    if (allVisibleSelected) {
      const next = { ...selected };
      for (const d of deadlines) delete next[keyOf(d)];
      selected = next;
    } else selected = { ...selected, ...Object.fromEntries(deadlines.map((d) => [keyOf(d), d])) };
  }
  async function exportIcs() {
    exporting = true;
    exportError = '';
    try {
      const blob = await api.exportDeadlines(
        Object.values(selected).map((d) => ({ item_id: d.item.id, kind: d.kind })),
        reminders
      );
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement('a'), {
        href: url,
        download: 'amazon-deadlines.ics'
      });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) {
      exportError = (e as Error).message;
    } finally {
      exporting = false;
    }
  }
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
      class:active={kind === 'all'}
      aria-pressed={kind === 'all'}
      onclick={() => (kind = 'all')}
      ><Icon name="deadlines" size={19} />{tr('All', 'Tutte')}</button
    ><button
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
    {kind === 'all'
      ? tr(
          'Return windows (last day to start a return) and warranty end dates. Select deadlines to add them to your calendar.',
          'Finestre di reso (ultimo giorno per avviare un reso) e fine delle garanzie. Seleziona le scadenze per aggiungerle al tuo calendario.'
        )
      : kind === 'return'
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
<div class="selection-bar" class:active={count > 0} role="region" aria-label={tr('Export to calendar', 'Esporta nel calendario')}>
  <label class="select-all"
    ><input
      type="checkbox"
      checked={allVisibleSelected}
      indeterminate={!allVisibleSelected && deadlines.some((d) => keyOf(d) in selected)}
      disabled={!deadlines.length}
      onchange={toggleAll}
    />{tr('Select all shown', 'Seleziona tutte quelle mostrate')}</label
  >
  <span class="selection-count" aria-live="polite"
    >{count
      ? tr(`${count} selected`, `${count} selezionate`)
      : tr('Select deadlines to export', 'Seleziona le scadenze da esportare')}</span
  >
  <label class="reminder-toggle" title={tr('Adds calendar reminders at the add-on thresholds', 'Aggiunge promemoria alle soglie configurate nell’add-on')}
    ><input type="checkbox" bind:checked={reminders} />{tr('Reminders', 'Promemoria')}</label
  >
  {#if count}<button class="button secondary" onclick={() => (selected = {})}
      >{tr('Clear', 'Azzera')}</button
    >{/if}
  <button class="button primary" disabled={!count || exporting} onclick={exportIcs}
    ><Icon name="calendar" size={18} />{exporting
      ? tr('Exporting…', 'Esportazione…')
      : tr('Export .ics', 'Esporta .ics')}</button
  >
</div>
{#if exportError}<div class="alert error-alert" role="alert">
    <Icon name="error" size={20} /><span>{exportError}</span>
  </div>{/if}
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
            {#each deadlines.filter((d) => d.deadline.startsWith(group)) as d (keyOf(d))}<div
                class="timeline-item"
                class:selected={keyOf(d) in selected}
                ><label class="row-select"
                  ><input
                    type="checkbox"
                    checked={keyOf(d) in selected}
                    onchange={() => toggle(d)}
                    aria-label={`${tr('Select', 'Seleziona')} ${d.item.title}`}
                  /></label
                ><a class="timeline-row" href={`#/orders/${d.order_number}`}
                ><div class="date-tile">
                  <strong>{Number(d.deadline.slice(8))}</strong><span
                    >{new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(
                      new Date(d.deadline + 'T12:00:00')
                    )}</span
                  >
                </div>
                <ProductImage src={d.item.image_link} title={d.item.title} />
                <div class="timeline-content">
                  <strong>{d.item.title}</strong><span
                    >{#if kind === 'all'}<em class="kind-tag" class:warranty={d.kind === 'warranty'}
                        >{d.kind === 'return'
                          ? tr('Return window', 'Finestra di reso')
                          : tr('Warranty', 'Garanzia')}</em
                      >{/if}{d.item.seller}</span
                  ><small
                    >{tr('Order', 'Ordine')} {d.order_number}</small
                  >
                </div>
                <Countdown deadline={d.deadline} kind={d.kind} {locale} /><span class="row-chevron"
                  ><Icon name="chevron" size={20} /></span
                ></a
              ></div>{/each}
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
