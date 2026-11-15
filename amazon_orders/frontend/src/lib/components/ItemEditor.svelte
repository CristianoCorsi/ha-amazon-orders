<script lang="ts">
  import { untrack } from 'svelte';
  import { api } from '$lib/api';
  import type { Item, ItemStatus } from '$lib/types';
  import { date, money, daysLeft, type Locale } from '$lib/i18n';
  import Icon from './Icon.svelte';
  import ProductImage from './ProductImage.svelte';
  import Countdown from './Countdown.svelte';
  let {
    item,
    locale,
    cancelled,
    placed,
    onSaved
  }: {
    item: Item;
    locale: Locale;
    cancelled: boolean;
    placed: string;
    onSaved: () => Promise<void>;
  } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  let status = $state<ItemStatus>(untrack(() => item.item_state.status));
  let note = $state(untrack(() => item.item_state.note || ''));
  let mode = $state(
    untrack(() =>
      item.item_state.warranty_until_override
        ? 'date'
        : item.item_state.warranty_months_override
          ? 'months'
          : 'default'
    )
  );
  let until = $state(untrack(() => item.item_state.warranty_until_override || ''));
  let months = $state<number | undefined>(
    untrack(() => item.item_state.warranty_months_override || 36)
  );
  let saving = $state(false),
    error = $state(''),
    saved = $state(false);
  const inactive = $derived(cancelled || item.item_state.status === 'returned');
  const returnClosed = $derived(!item.return_deadline && (daysLeft(placed) ?? 0) < -90);
  async function save(event: SubmitEvent) {
    event.preventDefault();
    saving = true;
    error = '';
    saved = false;
    try {
      await api.updateItem(item.id, {
        status,
        note,
        warranty_until_override: mode === 'date' ? until : null,
        warranty_months_override: mode === 'months' ? (months ?? null) : null
      });
      await onSaved();
      saved = true;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<article class="panel item-detail">
  <div class="item-hero">
    <ProductImage src={item.image_link} title={item.title} large />
    <div>
      <span class="muted-text">{item.seller ?? tr('Unknown seller', 'Venditore sconosciuto')}</span>
      <h2>{item.title}</h2>
      <strong class="detail-price">{money(item.price, locale)}</strong>
      <p class="muted-text">
        {tr('Quantity', 'Quantità')}: {item.quantity}{#if item.asin}
          <span class="detail-asin">/ {item.asin}</span>{/if}
      </p>
      {#if item.link}<a href={item.link} target="_blank" rel="noreferrer" class="text-link"
          >{tr('View on Amazon', 'Vedi su Amazon')}<Icon name="external" size={17} /></a
        >{/if}
    </div>
  </div>
  <div class="deadline-cards">
    <div class="deadline-card">
      <span class="metric-label"
        ><Icon name="return" size={21} />{tr('Return window', 'Finestra di reso')}</span
      ><strong
        >{inactive
          ? tr('No active deadline', 'Nessuna scadenza attiva')
          : returnClosed
            ? tr('Closed', 'Chiusa')
            : date(item.return_deadline, locale)}</strong
      >{#if !returnClosed}<Countdown deadline={item.return_deadline} {locale} {inactive} />{/if}
      <p>{tr('The date provided by Amazon.', 'La data indicata da Amazon.')}</p>
    </div>
    <div class="deadline-card">
      <span class="metric-label"
        ><Icon name="warranty" size={21} />{tr('Warranty coverage', 'Copertura garanzia')}</span
      ><strong
        >{inactive
          ? tr('No active deadline', 'Nessuna scadenza attiva')
          : date(item.warranty_deadline, locale)}</strong
      ><Countdown deadline={item.warranty_deadline} kind="warranty" {locale} {inactive} />
      <p>
        {tr('From', 'Dal')}
        {date(item.delivered_date || placed, locale)}
        {item.item_state.warranty_months_override || 24}
        {tr('months', 'mesi')}{#if item.item_state.warranty_until_override}
          · {tr('Custom date', 'Data personalizzata')}{/if}
      </p>
    </div>
  </div>
  <form class="annotation-form" onsubmit={save}>
    <div class="section-heading">
      <div>
        <h3>{tr('Make a note of it', 'Tieni tutto a mente')}</h3>
        <p>
          {tr(
            'Only saved in this add-on. Never sent to Amazon.',
            'Salvato solo in questo add-on. Mai inviato ad Amazon.'
          )}
        </p>
      </div>
      <Icon name="warranty" size={22} />
    </div>
    <fieldset class="status-fieldset">
      <legend>{tr('What would you like to do?', 'Cosa vuoi fare?')}</legend>
      <div class="segmented item-status">
        {#each [['none', tr('Undecided', 'Da decidere')], ['keep', tr('Keep', 'Da tenere')], ['to_return', tr('To return', 'Da restituire')], ['returned', tr('Returned', 'Restituito')]] as [value, label]}<button
            type="button"
            class:active={status === value}
            aria-pressed={status === value}
            onclick={() => {
              status = value as ItemStatus;
              saved = false;
            }}
            >{#if status === value}<Icon name="check" size={17} />{/if}{label}</button
          >{/each}
      </div>
    </fieldset>
    {#if status === 'returned'}<p class="info-strip compact-info">
        <Icon name="info" size={18} />{tr(
          'This hides active deadlines. It does not start a return or request a refund.',
          'Nasconde le scadenze attive. Non avvia un reso e non richiede un rimborso.'
        )}
      </p>{/if}
    <div class="field">
      <label for={`note-${item.id}`}>{tr('Your note', 'La tua nota')}</label><textarea
        id={`note-${item.id}`}
        rows="3"
        bind:value={note}
        maxlength="4000"
        placeholder={tr(
          'Measurements, a reminder, a warranty reference…',
          'Misure, un promemoria, un riferimento alla garanzia…'
        )}
        oninput={() => (saved = false)}></textarea>
    </div>
    <div class="warranty-fields">
      <div class="field">
        <label for={`warranty-${item.id}`}>{tr('Warranty duration', 'Durata della garanzia')}</label
        ><select id={`warranty-${item.id}`} bind:value={mode} onchange={() => (saved = false)}
          ><option value="default">{tr('Standard · 2 years', 'Standard · 2 anni')}</option><option
            value="months">{tr('Custom duration', 'Durata personalizzata')}</option
          ><option value="date">{tr('Exact end date', 'Data di scadenza esatta')}</option></select
        >
      </div>
      {#if mode === 'months'}<div class="field">
          <label for={`months-${item.id}`}>{tr('Number of months', 'Numero di mesi')}</label><input
            id={`months-${item.id}`}
            type="number"
            min="1"
            max="240"
            step="1"
            required
            bind:value={months}
            oninput={() => (saved = false)}
          />
        </div>{:else if mode === 'date'}<div class="field">
          <label for={`until-${item.id}`}>{tr('Covered until', 'Coperto fino al')}</label><input
            id={`until-${item.id}`}
            type="date"
            required
            bind:value={until}
            oninput={() => (saved = false)}
          />
        </div>{/if}
    </div>
    {#if error}<p class="form-error" role="alert">{error}</p>{/if}
    <div class="form-footer">
      <span class="save-status" role="status"
        >{#if saved}<Icon name="success" size={19} />{tr(
            'Saved locally',
            'Salvato in locale'
          )}{:else}{tr(
            'Your annotations stay safe during a cache refresh.',
            'Le annotazioni restano al sicuro durante il rinnovo della cache.'
          )}{/if}</span
      ><button type="submit" class="button primary" disabled={saving}
        ><Icon name="check" size={18} />{saving
          ? tr('Saving…', 'Salvataggio…')
          : tr('Save changes', 'Salva modifiche')}</button
      >
    </div>
  </form>
</article>
