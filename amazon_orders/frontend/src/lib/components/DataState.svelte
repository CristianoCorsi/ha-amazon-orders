<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  let {
    busy = false,
    error = '',
    empty = false,
    locale,
    retry,
    children
  }: {
    busy?: boolean;
    error?: string;
    empty?: boolean;
    locale: 'en' | 'it';
    retry?: () => void;
    children: Snippet;
  } = $props();
</script>

{#if busy}<div
    class="skeleton-group"
    role="status"
    aria-label={locale === 'it' ? 'Caricamento' : 'Loading'}
  >
    <div class="skeleton skeleton-wide"></div>
    <div class="skeleton-grid">
      <div class="skeleton"></div>
      <div class="skeleton"></div>
    </div>
    <div class="skeleton skeleton-wide"></div>
  </div>
{:else if error}<div class="empty-state" role="alert">
    <span class="empty-icon danger"><Icon name="error" size={32} /></span>
    <h2>{locale === 'it' ? 'Impossibile caricare i dati' : 'Couldn’t load your data'}</h2>
    <p>{error}</p>
    {#if retry}<button class="button primary" onclick={retry}
        ><Icon name="refresh" size={18} />{locale === 'it' ? 'Riprova' : 'Try again'}</button
      >{/if}
  </div>
{:else if empty}<div class="empty-state">
    <span class="empty-icon"><Icon name="orders" size={36} /></span>
    <h2>{locale === 'it' ? 'Nessun ordine qui, per ora' : 'No orders here, yet'}</h2>
    <p>
      {locale === 'it'
        ? 'Modifica i filtri oppure avvia una sincronizzazione dalle impostazioni.'
        : 'Try different filters, or start a sync in Settings to bring your orders here.'}
    </p>
  </div>
{:else}{@render children()}{/if}
