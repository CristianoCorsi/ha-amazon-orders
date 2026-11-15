<script lang="ts">
  import { auth } from '$lib/auth-store';
  import { isMock } from '$lib/api';
  import type { Locale } from '$lib/i18n';
  import Icon from './Icon.svelte';
  let { locale, settings = false }: { locale: Locale; settings?: boolean } = $props();
  const tr = (en: string, it: string) => (locale === 'it' ? it : en);
  let dialog: HTMLDialogElement;
  let copied = $state(false);
  const authState = $derived($auth.status?.state);
  async function copyLink() {
    copied = false;
    try {
      await navigator.clipboard.writeText($auth.url);
      copied = true;
    } catch {
      document.querySelector<HTMLInputElement>('#amazon-login-url')?.select();
    }
  }
  async function logout() {
    dialog.close();
    await auth.logout();
  }
</script>

<section
  class="panel settings-card auth-card"
  aria-label={tr('Amazon sign-in', 'Accesso ad Amazon')}
>
  <div class="section-heading">
    <div>
      <h2>{tr('Your Amazon connection', 'La connessione ad Amazon')}</h2>
      <p>amazon.it</p>
    </div>
    <span class="status-orb" class:warning={authState === 'auth_required'}
      ><Icon
        name={authState === 'ok' ? 'warranty' : authState === 'in_progress' ? 'sync' : 'orders'}
        size={25}
      /></span
    >
  </div>
  <h3 class="connection-heading">
    {authState === 'ok'
      ? $auth.completed
        ? tr('You’re connected', 'La connessione è pronta')
        : tr('Connected, and read-only', 'Connesso, in sola lettura')
      : authState === 'in_progress'
        ? tr('Finish signing in on Amazon', 'Completa l’accesso su Amazon')
        : authState === 'auth_required'
          ? tr('Connect your Amazon account', 'Collega il tuo account Amazon')
          : tr('Checking your connection', 'Verifica della connessione')}
  </h3>
  <p class="auth-description">
    {tr(
      'Sign in on Amazon’s own page in a new tab with your password and 2FA code.',
      'Accedi sulla pagina di Amazon in una nuova scheda con password e codice di verifica a due fattori.'
    )}
    {tr(
      'The add-on registers a device in Amazon’s “Your devices” list and renews the session automatically.',
      'L’add-on registra un dispositivo nell’elenco “I tuoi dispositivi” di Amazon e rinnova la sessione automaticamente.'
    )}
    {tr(
      'The sign-in page only works on your home network or VPN.',
      'La pagina di accesso funziona solo dalla rete di casa o tramite VPN.'
    )}
  </p>
  {#if authState === 'in_progress'}
    <div class="auth-progress" role="status">
      <Icon name="sync" size={20} /><span
        >{tr(
          'Waiting for Amazon. This page checks automatically every 3 seconds.',
          'In attesa di Amazon. Questa pagina verifica lo stato ogni 3 secondi.'
        )}</span
      >
    </div>
  {:else if authState === 'ok'}
    <p class="auth-success" role="status">
      <Icon name="success" size={19} />{tr(
        'Session ready. Your saved history and notes stay on this add-on.',
        'Sessione pronta. Storico e note restano in questo add-on.'
      )}
    </p>
  {/if}
  {#if $auth.error}<div class="alert error-alert" role="alert">
      <Icon name="error" size={20} /><span
        >{tr(
          'Could not update the Amazon connection. Please try again.',
          'Impossibile aggiornare la connessione ad Amazon. Riprova.'
        )}<small class="error-detail">{$auth.error}</small></span
      >
    </div>{/if}
  <div class="button-row">
    {#if authState === 'auth_required'}
      <button
        class="button primary"
        disabled={$auth.busy}
        onclick={() => auth.start(() => window.open('about:blank', '_blank'))}
        >{$auth.busy ? tr('Opening…', 'Apertura…') : tr('Sign in', 'Accedi')}<Icon
          name="external"
          size={17}
        /></button
      >
    {:else if authState === 'ok' && settings}
      <button class="button secondary" disabled={$auth.busy} onclick={() => dialog.showModal()}
        ><Icon name="logout" size={17} />{tr(
          'Sign out and remove device',
          'Esci e rimuovi dispositivo'
        )}</button
      >
    {/if}
    {#if authState !== 'ok' || settings}<button
        class="text-link"
        disabled={$auth.busy}
        onclick={auth.refresh}
        >{tr('Check status', 'Verifica stato')}<Icon name="refresh" size={17} /></button
      >{/if}
  </div>
  {#if $auth.url}
    <div class="auth-link-fallback">
      <p>
        {$auth.popupBlocked
          ? tr(
              'The new tab was blocked. Open or copy this link on your home network.',
              'La nuova scheda è stata bloccata. Apri o copia questo link dalla rete di casa.'
            )
          : tr(
              'Tab closed? Open the sign-in page again or copy the link.',
              'Scheda chiusa? Riapri la pagina di accesso o copia il link.'
            )}
      </p>
      <a class="text-link" href={$auth.url} target="_blank" rel="noopener noreferrer"
        >{tr('Open sign-in page', 'Apri pagina di accesso')}<Icon name="external" size={16} /></a
      >
      <div class="copy-field">
        <label class="sr-only" for="amazon-login-url">{tr('Sign-in link', 'Link di accesso')}</label
        ><input
          id="amazon-login-url"
          readonly
          value={$auth.url}
          onclick={(e) => e.currentTarget.select()}
        /><button
          class="icon-button"
          aria-label={tr('Copy sign-in link', 'Copia link di accesso')}
          onclick={copyLink}><Icon name="copy" size={20} /></button
        >
      </div>
      {#if copied}<p role="status">{tr('Link copied.', 'Link copiato.')}</p>{/if}
    </div>
  {/if}
  {#if isMock && authState === 'in_progress'}<p class="auth-demo-note">
      {tr(
        'Demo only. Use the synthetic sign-in tab to finish; no credentials or Amazon requests.',
        'Solo demo. Completa dalla scheda di accesso simulata; nessuna credenziale o richiesta ad Amazon.'
      )}
    </p>{/if}
</section>
<dialog
  bind:this={dialog}
  class="confirm-dialog"
  aria-labelledby="logout-title"
  aria-describedby="logout-description"
>
  <div class="dialog-content">
    <span class="empty-icon"><Icon name="logout" size={30} /></span>
    <h2 id="logout-title">
      {tr('Sign out and remove device?', 'Uscire e rimuovere il dispositivo?')}
    </h2>
    <p id="logout-description">
      {tr(
        'The add-on will remove its registered Amazon device and stop syncing until you sign in again. Saved orders, notes and warranty overrides are kept.',
        'L’add-on rimuoverà il dispositivo registrato su Amazon e interromperà la sincronizzazione fino al prossimo accesso. Ordini salvati, note e garanzie personalizzate restano disponibili.'
      )}
    </p>
    <div class="dialog-actions">
      <button class="button secondary" onclick={() => dialog.close()}
        >{tr('Cancel', 'Annulla')}</button
      ><button class="button danger-button" onclick={logout}
        >{tr('Sign out and remove device', 'Esci e rimuovi dispositivo')}</button
      >
    </div>
  </div>
</dialog>
