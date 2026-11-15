<script lang="ts">
  import { daysLeft, type Locale } from '$lib/i18n';
  import Icon from './Icon.svelte';
  let {
    deadline,
    kind = 'return',
    locale,
    inactive = false
  }: {
    deadline: string | null;
    kind?: 'return' | 'warranty';
    locale: Locale;
    inactive?: boolean;
  } = $props();
  const left = $derived(daysLeft(deadline));
  const urgent = $derived(
    !inactive && left !== null && left >= 0 && left <= (kind === 'return' ? 2 : 14)
  );
  const soon = $derived(
    !inactive && left !== null && left > 0 && left <= (kind === 'return' ? 7 : 90)
  );
</script>

<span class="chip" class:urgent class:soon class:muted={inactive || left === null || left < 0}
  ><Icon name={kind} size={15} />{#if inactive}{locale === 'it'
      ? 'Non attiva'
      : 'Inactive'}{:else if left === null}{locale === 'it'
      ? 'Sconosciuta'
      : 'Unknown'}{:else if left < 0}{locale === 'it'
      ? 'Scaduta'
      : 'Closed'}{:else if left === 0}{locale === 'it' ? 'Oggi' : 'Today'}{:else}{left}
    {locale === 'it' ? 'giorni' : 'days'}{/if}</span
>
