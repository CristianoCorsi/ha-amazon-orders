<script lang="ts">
  import { onMount } from 'svelte';
  import '@fontsource-variable/manrope';
  import '../app.css';
  import { api, isMock } from '$lib/api';
  import { initialLocale, type Locale } from '$lib/i18n';
  import { observeTheme } from '$lib/theme';
  import type { Status } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Overview from '$lib/views/Overview.svelte';
  import Orders from '$lib/views/Orders.svelte';
  import Detail from '$lib/views/Detail.svelte';
  import Deadlines from '$lib/views/Deadlines.svelte';
  import Statistics from '$lib/views/Statistics.svelte';
  import Settings from '$lib/views/Settings.svelte';
  let locale = $state<Locale>('en'),
    theme = $state('auto'),
    route = $state('/'),
    status = $state<Status | null>(null),
    statusError = $state('');
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  const screen = $derived(route.split('/')[1]?.split('?')[0] || 'overview');
  const detailId = $derived(
    screen === 'orders' && route.split('/')[2]
      ? decodeURIComponent(route.split('/')[2].split('?')[0])
      : ''
  );
  const nav = $derived([
    { id: 'overview', label: tr('Overview', 'Panoramica') },
    { id: 'orders', label: tr('Orders', 'Ordini') },
    { id: 'deadlines', label: tr('Deadlines', 'Scadenze') },
    { id: 'statistics', label: tr('Statistics', 'Statistiche') },
    { id: 'settings', label: tr('Settings', 'Impostazioni') }
  ]);
  const title = $derived(
    detailId
      ? tr('Order details', 'Dettagli ordine')
      : (nav.find((n) => n.id === screen)?.label ?? tr('Not found', 'Pagina non trovata'))
  );
  const subtitle = $derived(
    screen === 'overview'
      ? tr('A clearer view of what comes home.', 'I tuoi acquisti, tutto sotto controllo.')
      : screen === 'orders'
        ? tr(
            'Find it. Remember it. Keep track of it.',
            'Trova un acquisto e ritrova ogni dettaglio.'
          )
        : screen === 'deadlines'
          ? tr('A little ahead of the important dates.', 'Un passo avanti alle date importanti.')
          : screen === 'statistics'
            ? tr('The full picture, beyond the parcel.', 'Il quadro completo, oltre il pacco.')
            : screen === 'settings'
              ? tr(
                  'Connected to your home. In your control.',
                  'Connesso alla tua casa. Sotto il tuo controllo.'
                )
              : ''
  );
  function updateRoute() {
    route = location.hash.slice(1) || '/';
    window.scrollTo({ top: 0 });
  }
  async function refreshStatus() {
    try {
      status = await api.status();
      statusError = '';
    } catch (e) {
      statusError = (e as Error).message;
    }
  }
  function setLocale(value: Locale) {
    locale = value;
    document.documentElement.lang = value;
    try {
      localStorage.setItem('amazon-orders-language', value);
    } catch {
      /* private mode */
    }
  }
  function setTheme(value: string) {
    theme = value;
    try {
      localStorage.setItem('amazon-orders-theme', value);
    } catch {
      /* private mode */
    }
    window.dispatchEvent(new Event('amazon-theme-change'));
  }
  onMount(() => {
    locale = initialLocale();
    document.documentElement.lang = locale;
    try {
      theme = localStorage.getItem('amazon-orders-theme') || 'auto';
    } catch {
      /* private mode */
    }
    const cleanup = observeTheme(() => theme);
    updateRoute();
    refreshStatus();
    const timer = setInterval(refreshStatus, 15000);
    window.addEventListener('hashchange', updateRoute);
    return () => {
      cleanup();
      clearInterval(timer);
      window.removeEventListener('hashchange', updateRoute);
    };
  });
</script>

<svelte:head
  ><title>{title} · Amazon Orders</title><meta
    name="description"
    content="Your Amazon order history, returns and warranties. Read-only, local-first, at home in Home Assistant."
  /></svelte:head
>
<a
  class="skip-link"
  href="#main-content"
  onclick={(e) => {
    e.preventDefault();
    document.getElementById('main-content')?.focus();
  }}>{tr('Skip to content', 'Vai al contenuto')}</a
>
<aside class="sidebar">
  <a class="brand" href="#/"
    ><span class="brand-mark"><Icon name="orders" size={29} /></span><span
      >Amazon<span class="brand-second">Orders</span></span
    ></a
  >
  <div class="home-label"><span></span>HOME ASSISTANT</div>
  <nav aria-label={tr('Main navigation', 'Navigazione principale')}>
    {#each nav as item}<a
        href={`#/${item.id === 'overview' ? '' : item.id}`}
        class:active={screen === item.id}
        aria-current={screen === item.id ? 'page' : undefined}
        ><Icon name={item.id} size={23} /><span>{item.label}</span
        >{#if item.id === 'deadlines' && (status?.counts.returns_open ?? 0) > 0}<small
            >{status?.counts.returns_open}</small
          >{/if}</a
      >{/each}
  </nav>
  <div class="sidebar-bottom">
    <a href="#/settings" class="sidebar-sync"
      ><span class="sync-symbol"><Icon name="sync" size={21} /></span><strong
        >{status?.state === 'auth_required'
          ? tr('Sign-in needed', 'Accesso richiesto')
          : status?.backfill.state === 'running'
            ? tr('History in progress', 'Storico in recupero')
            : tr('History, up to date', 'Storico aggiornato')}</strong
      ><span
        >{status?.backfill.orders_processed ?? 0} {tr('orders imported', 'ordini importati')}</span
      ><progress
        max="100"
        value={status?.backfill.progress ?? undefined}
        aria-label={tr('Backfill progress', 'Avanzamento recupero storico')}
      ></progress><small
        >{tr('Slow by design. Always resumable.', 'Senza fretta. Sempre ripristinabile.')}</small
      ></a
    >
    <div class="local-label">
      <Icon name="warranty" size={16} />{tr(
        'Read-only. Yours to keep.',
        'Sola lettura. Tutto tuo.'
      )}
    </div>
  </div>
</aside>
<div class="app-shell">
  <header class="topbar">
    <div class="breadcrumb">
      <Icon name="orders" size={19} /><span>Amazon Orders</span><Icon
        name="chevron"
        size={16}
      /><span>{title}</span>
    </div>
    <div class="topbar-actions">
      {#if isMock}<span class="demo-badge">{tr('Demo data', 'Dati demo')}</span>{/if}<button
        class="icon-button"
        aria-label={tr('Switch language', 'Cambia lingua')}
        onclick={() => setLocale(locale === 'en' ? 'it' : 'en')}
        ><Icon name="language" size={21} /></button
      ><button
        class="icon-button"
        aria-label={tr('Toggle color theme', 'Cambia tema')}
        onclick={() =>
          setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark')}
        ><Icon name="theme" size={22} /></button
      >
    </div>
  </header>
  <main id="main-content" tabindex="-1">
    <div class="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {#if screen === 'overview'}<a class="sync-pill" href="#/settings"
          ><span class="status-dot" class:needs-auth={status?.auth.state !== 'ok'}></span>{status
            ?.auth.state === 'auth_required'
            ? tr('Sign in to sync', 'Accedi per sincronizzare')
            : tr('Synced with your home', 'Connesso alla tua casa')}<Icon
            name="chevron"
            size={16}
          /></a
        >{/if}
    </div>
    {#if status?.auth.state === 'auth_required' && screen !== 'settings'}<a
        href="#/settings"
        class="alert auth-alert"
        ><Icon name="error" /><span
          >{tr(
            'Your Amazon session needs a fresh sign-in. Your saved history is still here.',
            'La sessione Amazon richiede un nuovo accesso. Lo storico salvato resta disponibile.'
          )}</span
        ><strong>{tr('Sign in', 'Accedi')}<Icon name="right" size={18} /></strong></a
      >{/if}
    {#if statusError}<div class="alert error-alert" role="alert">
        <Icon name="error" size={20} /><span>{statusError}</span><button
          class="text-link"
          onclick={refreshStatus}>{tr('Retry', 'Riprova')}</button
        >
      </div>{/if}
    {#key route}{#if screen === 'overview'}<Overview
          {locale}
          {status}
        />{:else if screen === 'orders' && detailId}<Detail
          {locale}
          id={detailId}
        />{:else if screen === 'orders'}<Orders
          {locale}
        />{:else if screen === 'deadlines'}<Deadlines
          {locale}
          initialKind={route.includes('kind=warranty') ? 'warranty' : 'return'}
        />{:else if screen === 'statistics'}<Statistics
          {locale}
        />{:else if screen === 'settings'}<Settings
          {locale}
          {theme}
          onLocale={setLocale}
          onTheme={setTheme}
          onRefresh={refreshStatus}
        />{:else}<div class="empty-state">
          <h2>{tr('This page isn’t here.', 'Questa pagina non esiste.')}</h2>
          <a class="button primary" href="#/">{tr('Back to overview', 'Torna alla panoramica')}</a>
        </div>{/if}{/key}
  </main>
  <footer class="app-footer">
    <span>Amazon Orders</span><span
      >{tr('At home in Home Assistant', 'A casa in Home Assistant')}</span
    >
  </footer>
</div>
<nav class="bottom-nav" aria-label={tr('Mobile navigation', 'Navigazione mobile')}>
  {#each nav as item}<a
      href={`#/${item.id === 'overview' ? '' : item.id}`}
      class:active={screen === item.id}
      aria-current={screen === item.id ? 'page' : undefined}
      ><span><Icon name={item.id} size={23} /></span><small>{item.label}</small></a
    >{/each}
</nav>
