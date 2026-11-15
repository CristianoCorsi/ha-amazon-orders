<script lang="ts">
  import { onMount } from 'svelte';
  import { api, isMock } from '$lib/api';
  import { auth } from '$lib/auth-store';
  import AuthPanel from '$lib/components/AuthPanel.svelte';
  import type { Settings, Status } from '$lib/types';
  import { date, type Locale } from '$lib/i18n';
  import Icon from '$lib/components/Icon.svelte';
  import DataState from '$lib/components/DataState.svelte';
  let {
    locale,
    theme,
    onLocale,
    onTheme,
    onRefresh
  }: {
    locale: Locale;
    theme: string;
    onLocale: (value: Locale) => void;
    onTheme: (value: string) => void;
    onRefresh: () => Promise<void>;
  } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  let busy = $state(true),
    error = $state(''),
    actionError = $state(''),
    message = $state(''),
    acting = $state('');
  let status = $state<Status | null>(null),
    settings = $state<Settings | null>(null),
    calendarUrl = $state('');
  let scope = $state('all'),
    scopeValue = $state(''),
    purgeDialog: HTMLDialogElement;
  let demoAuth = $state(false),
    demoEmpty = $state(false),
    demoError = $state(false);
  async function load() {
    busy = true;
    error = '';
    try {
      const [s, options] = await Promise.all([api.status(), api.settings()]);
      status = s;
      settings = options;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
  async function refresh() {
    status = await api.status();
    await onRefresh();
  }
  async function act(name: string, action: () => Promise<unknown>, success: string) {
    acting = name;
    actionError = '';
    message = '';
    try {
      await action();
      await refresh();
      message = success;
    } catch (e) {
      actionError = (e as Error).message;
    } finally {
      acting = '';
    }
  }
  async function exportCsv() {
    await act(
      'export',
      async () => {
        const url = await api.exportCsv();
        const a = document.createElement('a');
        a.href = url;
        a.download = 'amazon-orders.csv';
        a.click();
        if (url.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
      tr('Export started.', 'Esportazione avviata.')
    );
  }
  async function copyCalendar() {
    try {
      await navigator.clipboard.writeText(calendarUrl);
      message = tr('Calendar URL copied.', 'URL del calendario copiato.');
    } catch {
      actionError = tr(
        'Clipboard unavailable. Select and copy the URL below.',
        'Appunti non disponibili. Seleziona e copia l’URL qui sotto.'
      );
    }
  }
  async function purge() {
    purgeDialog.close();
    await act(
      'purge',
      () => api.purge(scope === 'all' ? 'all' : `${scope}:${scopeValue}`),
      tr(
        'Cache marked for refresh. Your notes and item states are safe.',
        'Cache segnata per il rinnovo. Note e stati degli articoli sono al sicuro.'
      )
    );
    await api.settings();
  }
  async function demo() {
    const { mockControls } = await import('$lib/mock');
    mockControls.authRequired = demoAuth;
    mockControls.authInProgress = false;
    mockControls.empty = demoEmpty;
    mockControls.failRequests = demoError;
    await onRefresh();
    await auth.refresh();
    if (!demoError) status = await api.status();
  }
  onMount(() => {
    calendarUrl = new URL('calendar.ics', document.baseURI).href;
    load();
    if (isMock)
      import('$lib/mock').then(({ mockControls }) => {
        demoAuth = mockControls.authRequired;
        demoEmpty = mockControls.empty;
        demoError = mockControls.failRequests;
      });
  });
</script>

{#if actionError}<div class="alert error-alert" role="alert">
    <Icon name="error" />{actionError}<button
      class="icon-button"
      aria-label={tr('Dismiss', 'Chiudi')}
      onclick={() => (actionError = '')}><Icon name="close" size={18} /></button
    >
  </div>{/if}
{#if message}<div class="alert success-alert" role="status">
    <Icon name="success" />{message}<button
      class="icon-button"
      aria-label={tr('Dismiss', 'Chiudi')}
      onclick={() => (message = '')}><Icon name="close" size={18} /></button
    >
  </div>{/if}
<DataState {busy} {error} {locale} retry={load}>
  <div class="settings-grid">
    <AuthPanel {locale} settings />
    <section class="panel settings-card">
      <div class="section-heading">
        <div>
          <h2>{tr('Make it feel like home', 'Come a casa tua')}</h2>
          <p>{tr('Appearance & language', 'Aspetto e lingua')}</p>
        </div>
        <Icon name="theme" size={24} />
      </div>
      <div class="field">
        <label for="language">{tr('Language', 'Lingua')}</label><select
          id="language"
          value={locale}
          onchange={(e) => onLocale(e.currentTarget.value as Locale)}
          ><option value="en">English</option><option value="it">Italiano</option></select
        ><small
          >{tr(
            'Uses Home Assistant’s language until you choose one.',
            'Usa la lingua di Home Assistant finché non ne scegli una.'
          )}</small
        >
      </div>
      <div class="field">
        <label for="theme">{tr('Theme', 'Tema')}</label><select
          id="theme"
          value={theme}
          onchange={(e) => onTheme(e.currentTarget.value)}
          ><option value="auto"
            >{tr('Follow Home Assistant / system', 'Segui Home Assistant / sistema')}</option
          ><option value="light">{tr('Light', 'Chiaro')}</option><option value="dark"
            >{tr('Dark', 'Scuro')}</option
          ></select
        >
      </div>
    </section>
  </div>
  <section class="panel sync-panel">
    <div class="section-heading">
      <div>
        <h2>{tr('A careful sync, by design', 'Una sincronizzazione senza fretta')}</h2>
        <p>
          {tr(
            'One request at a time. Your place is always saved.',
            'Una richiesta alla volta. Il punto di ripresa è sempre salvato.'
          )}
        </p>
      </div>
      <span class="chip"
        ><Icon name="sync" size={16} />{$auth.status?.state === 'in_progress'
          ? tr('Sign-in in progress', 'Accesso in corso')
          : $auth.status?.state !== 'ok'
            ? tr('Sign-in needed', 'Accesso richiesto')
            : status?.state === 'backfilling'
              ? tr('Backfilling', 'Recupero storico')
              : status?.state === 'cooldown'
                ? tr('Cooling down', 'In attesa')
                : status?.state === 'idle'
                  ? tr('Up to date', 'Aggiornato')
                  : status?.state}</span
      >
    </div>
    {#if status?.last_error}<div class="alert error-alert" role="alert">
        <Icon name="error" />{status.last_error}
      </div>{/if}{#if status?.cooldown_until}<p class="info-strip">
        <Icon name="clock" size={20} />{tr('Requests paused until', 'Richieste sospese fino a')}
        {new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
          new Date(status.cooldown_until)
        )}
      </p>{/if}
    <div class="sync-content">
      <div class="backfill-detail">
        <div class="backfill-label">
          <h3>{tr('Building your history', 'Recupero dello storico')}</h3>
          <strong
            >{status?.backfill.progress != null
              ? `${status.backfill.progress}%`
              : tr('Resumable', 'Ripristinabile')}</strong
          >
        </div>
        <progress
          max="100"
          value={status?.backfill.progress ?? undefined}
          aria-label={tr('Backfill progress', 'Avanzamento recupero storico')}
        ></progress>
        <p>
          {status?.backfill.orders_processed ?? 0}
          {tr('orders imported', 'ordini importati')} / {tr('Working through', 'Recupero anno')}
          {status?.backfill.year}
        </p>
        <span class="muted-text"
          >{tr(
            'Resumes from the last saved cursor, even after a restart.',
            'Riprende dall’ultimo punto salvato, anche dopo un riavvio.'
          )}</span
        >
        <div class="button-row">
          <button
            class="button secondary"
            disabled={!!acting || $auth.status?.state !== 'ok'}
            onclick={() =>
              act(
                'backfill',
                () => api.backfill(status?.backfill.state === 'running' ? 'pause' : 'start'),
                tr('Backfill state updated.', 'Stato del recupero aggiornato.')
              )}
            ><Icon
              name={status?.backfill.state === 'running' ? 'pause' : 'play'}
              size={19}
            />{status?.backfill.state === 'running'
              ? tr('Pause backfill', 'Sospendi recupero')
              : tr('Resume backfill', 'Riprendi recupero')}</button
          ><button
            class="button primary"
            disabled={!!acting || $auth.status?.state !== 'ok'}
            onclick={() =>
              act(
                'recent',
                () => api.recent(),
                tr(
                  'Recent-order sync requested.',
                  'Sincronizzazione degli ordini recenti richiesta.'
                )
              )}
            ><Icon name="sync" size={19} />{tr('Sync recent orders', 'Sincronizza recenti')}</button
          >
        </div>
      </div>
      <dl class="key-values sync-facts">
        <div>
          <dt>{tr('Sync preset', 'Profilo sincronizzazione')}</dt>
          <dd>
            {settings?.sync_preset === 'careful'
              ? tr('Careful · 20-40 sec', 'Prudente · 20-40 sec')
              : tr('Moderate · 5-10 sec', 'Moderato · 5-10 sec')}
          </dd>
        </div>
        <div>
          <dt>{tr('Recent refresh', 'Aggiornamento recenti')}</dt>
          <dd>{tr('Every', 'Ogni')} {settings?.recent_refresh_hours} {tr('hours', 'ore')}</dd>
        </div>
        <div>
          <dt>{tr('Last sync', 'Ultima sincronizzazione')}</dt>
          <dd>
            {status?.last_recent_sync
              ? date(status.last_recent_sync, locale)
              : tr('Not yet', 'Non ancora')}
          </dd>
        </div>
        <div>
          <dt>{tr('Cached orders', 'Ordini in cache')}</dt>
          <dd>{status?.counts.orders ?? 0}</dd>
        </div>
        <div>
          <dt>{tr('Default warranty', 'Garanzia predefinita')}</dt>
          <dd>{settings?.default_warranty_months} {tr('months', 'mesi')}</dd>
        </div>
      </dl>
    </div>
  </section>
  <div class="settings-grid">
    <section class="panel settings-card">
      <div class="section-heading">
        <div>
          <h2>{tr('Take your data with you', 'Porta con te i tuoi dati')}</h2>
          <p>{tr('Open formats, no lock-in', 'Formati aperti, senza vincoli')}</p>
        </div>
        <Icon name="download" size={24} />
      </div>
      <p class="settings-description">
        {tr(
          'Export orders and items, including your local annotations. Use the Orders screen to export a filtered selection.',
          'Esporta ordini e articoli, incluse le annotazioni locali. Dalla pagina Ordini puoi esportare una selezione filtrata.'
        )}
      </p>
      <button class="button secondary" disabled={!!acting} onclick={exportCsv}
        ><Icon name="download" size={18} />{tr('Export CSV', 'Esporta CSV')}</button
      >
      <hr />
      <h3>{tr('Deadlines in your calendar', 'Le scadenze nel calendario')}</h3>
      <p class="settings-description">
        {tr(
          'Copy the ICS feed URL. For Home Assistant’s Remote Calendar integration, use the add-on’s internal hostname from its documentation, not this authenticated Ingress URL.',
          'Copia l’URL del feed ICS. Per l’integrazione Calendario remoto usa il nome host interno dell’add-on indicato nella documentazione, non questo URL Ingress autenticato.'
        )}
      </p>
      <div class="copy-field">
        <label class="sr-only" for="calendar-url"
          >{tr('Calendar feed URL', 'URL del feed calendario')}</label
        ><input
          id="calendar-url"
          readonly
          value={calendarUrl}
          onclick={(e) => e.currentTarget.select()}
        /><button
          class="icon-button"
          aria-label={tr('Copy calendar URL', 'Copia URL calendario')}
          onclick={copyCalendar}><Icon name="copy" size={20} /></button
        >
      </div>
    </section>
    <section class="panel settings-card cache-card">
      <div class="section-heading">
        <div>
          <h2>{tr('Refresh the cache', 'Rinnova la cache')}</h2>
          <p>{tr('A fresh read, not a reset', 'Una nuova lettura, non un ripristino')}</p>
        </div>
        <Icon name="purge" size={24} />
      </div>
      <p class="settings-description">
        {tr(
          'Mark cached details as stale so the next sync fetches them again. Notes, item states and warranty overrides are never deleted.',
          'Segna i dettagli in cache come obsoleti per rileggerli alla prossima sincronizzazione. Note, stati e garanzie personalizzate non vengono mai eliminati.'
        )}
      </p>
      <form
        onsubmit={(e) => {
          e.preventDefault();
          purgeDialog.showModal();
        }}
      >
        <div class="field">
          <label for="cache-scope">{tr('Scope', 'Ambito')}</label><select
            id="cache-scope"
            bind:value={scope}
            ><option value="all">{tr('All cached orders', 'Tutti gli ordini in cache')}</option
            ><option value="year">{tr('A specific year', 'Un anno specifico')}</option><option
              value="order">{tr('A specific order', 'Un ordine specifico')}</option
            ></select
          >
        </div>
        {#if scope !== 'all'}<div class="field">
            <label for="scope-value"
              >{scope === 'year' ? tr('Year', 'Anno') : tr('Order number', 'Numero ordine')}</label
            ><input
              id="scope-value"
              type="text"
              pattern={scope === 'year' ? '[0-9]{4}' : '.+'}
              required
              bind:value={scopeValue}
            />
          </div>{/if}<button class="button danger-button" type="submit" disabled={!!acting}
          ><Icon name="refresh" size={18} />{tr(
            'Refresh cached details',
            'Rinnova dettagli in cache'
          )}</button
        >
      </form>
    </section>
  </div>
</DataState>
{#if isMock}<section class="demo-panel">
    <div>
      <h3>{tr('Demo playground', 'Scenari di prova')}</h3>
      <p>
        {tr(
          'Synthetic data only. Changes reset when you reload. No requests go to Amazon.',
          'Solo dati sintetici. Le modifiche si azzerano ricaricando. Nessuna richiesta ad Amazon.'
        )}
      </p>
    </div>
    <div class="demo-options">
      <label
        ><input type="checkbox" bind:checked={demoAuth} onchange={demo} />{tr(
          'Sign-in required',
          'Accesso richiesto'
        )}</label
      ><label
        ><input type="checkbox" bind:checked={demoEmpty} onchange={demo} />{tr(
          'Empty history',
          'Storico vuoto'
        )}</label
      ><label
        ><input type="checkbox" bind:checked={demoError} onchange={demo} />{tr(
          'Connection error',
          'Errore connessione'
        )}</label
      >
    </div>
  </section>{/if}
<dialog bind:this={purgeDialog} class="confirm-dialog" onclose={() => {}}>
  <div class="dialog-content">
    <span class="empty-icon"><Icon name="refresh" size={30} /></span>
    <h2>{tr('Fetch these details again?', 'Rileggere questi dettagli?')}</h2>
    <p>
      {tr(
        'This adds requests to the slow sync queue. It does not delete your notes, item states or warranty overrides.',
        'Aggiunge richieste alla coda di sincronizzazione lenta. Non elimina note, stati o garanzie personalizzate.'
      )}
    </p>
    <strong
      >{scope === 'all' ? tr('All orders', 'Tutti gli ordini') : `${scope}: ${scopeValue}`}</strong
    >
    <div class="dialog-actions">
      <button class="button secondary" onclick={() => purgeDialog.close()}
        >{tr('Cancel', 'Annulla')}</button
      ><button class="button primary" onclick={purge}
        >{tr('Confirm refresh', 'Conferma rinnovo')}</button
      >
    </div>
  </div>
</dialog>
