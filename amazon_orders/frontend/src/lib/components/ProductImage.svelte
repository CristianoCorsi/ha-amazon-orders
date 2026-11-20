<script lang="ts">
  import Icon from './Icon.svelte';
  let {
    src,
    title,
    large = false
  }: { src?: string | null; title: string; large?: boolean } = $props();
  let failed = $state(false);
</script>

<div class:large class="product-image">
  {#if src && !failed}<img
      {src}
      alt={title}
      width={large ? 160 : 62}
      height={large ? 160 : 62}
      loading="lazy"
      onerror={() => (failed = true)}
    />{:else}<Icon name="orders" size={large ? 64 : 30} />{/if}
</div>
