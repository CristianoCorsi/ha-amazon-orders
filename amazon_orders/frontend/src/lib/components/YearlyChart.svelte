<script lang="ts">
  import type { YearRow } from '$lib/types';
  import { money, type Locale } from '$lib/i18n';
  let {
    years,
    selected,
    locale,
    onselect
  }: { years: YearRow[]; selected: number; locale: Locale; onselect?: (year: number) => void } =
    $props();
  // Size the drawing to the real width so text stays readable on a phone (no viewBox shrink).
  let width = $state(660);
  const W = $derived(Math.max(Math.round(width), 300));
  const H = 250,
    top = 34,
    base = 206,
    left = 46;
  const right = $derived(W - 10);
  const max = $derived(Math.max(...years.map((y) => y.spend), 100) * 1.1);
  const slot = $derived((right - left) / Math.max(years.length, 1));
  const barW = $derived(Math.min(46, slot * 0.56));
  const h = (v: number) => (Math.max(v, 0) / max) * (base - top);
  const compact = (v: number) =>
    new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: 'EUR',
      maximumFractionDigits: 0
    }).format(v);
  const x = (i: number) => left + slot * i + slot / 2;
  // Net trend line across years.
  const points = $derived(years.map((y, i) => `${x(i)},${base - h(y.net_spend)}`).join(' '));
</script>

<div class="chart-wrap yearly-chart">
  <div bind:clientWidth={width}>
  <svg
    viewBox={`0 0 ${W} ${H}`}
    role="group"
    aria-label={locale === 'it' ? 'Spesa netta per anno' : 'Net spending per year'}
  >
    {#each [0, 0.5, 1] as tick}<line
        x1={left}
        x2={right}
        y1={base - tick * (base - top)}
        y2={base - tick * (base - top)}
        stroke="var(--border)"
        stroke-dasharray="3 5"
      /><text x={left - 9} y={base + 4 - tick * (base - top)} text-anchor="end" class="axis"
        >{Math.round(max * tick)}</text
      >{/each}
    {#each years as y, i (y.year)}<g
        class="year-bar"
        class:selected={y.year === selected}
        role="button"
        tabindex="0"
        aria-label={`${y.year}: ${money(y.net_spend, locale)}`}
        onclick={() => onselect?.(y.year)}
        onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && onselect?.(y.year)}
        ><rect
          x={x(i) - barW / 2}
          y={base - h(y.spend)}
          width={barW}
          height={h(y.spend)}
          rx="6"
          fill="var(--chart-secondary)"
          ><title
            >{y.year} · {locale === 'it' ? 'ordini' : 'orders'} {money(y.spend, locale)} − {locale ===
            'it'
              ? 'rimborsi'
              : 'refunds'}
            {money(y.refunds, locale)}</title
          ></rect
        ><rect
          x={x(i) - barW / 2}
          y={base - h(y.net_spend)}
          width={barW}
          height={h(y.net_spend)}
          rx="6"
          fill="var(--primary)"
          opacity={y.year === selected ? 1 : 0.72}
        /><text x={x(i)} y={base - h(y.spend) - 8} text-anchor="middle" class="bar-value"
          >{compact(y.net_spend)}</text
        ><text x={x(i)} y={base + 22} text-anchor="middle" class="axis year-label">{y.year}</text></g
      >{/each}
    {#if years.length > 1}<polyline
        {points}
        fill="none"
        stroke="var(--text)"
        stroke-width="1.5"
        stroke-dasharray="4 4"
        opacity="0.45"
        pointer-events="none"
      />{/if}
  </svg>
  </div>
</div>
<div class="chart-legend">
  <span><i></i>{locale === 'it' ? 'Spesa netta' : 'Net spending'}</span><span
    ><i class="previous"></i>{locale === 'it' ? 'Ordini prima dei rimborsi' : 'Orders before refunds'}</span
  >
</div>

<style>
  .yearly-chart svg {
    display: block;
    width: 100%;
    height: auto;
  }
  .year-bar {
    cursor: pointer;
    outline: none;
  }
  .year-bar:focus-visible rect:last-of-type {
    stroke: var(--text);
    stroke-width: 2;
  }
  .bar-value {
    font-size: 10px;
    font-weight: 600;
    fill: var(--text-muted);
  }
  .year-bar.selected .bar-value,
  .year-bar.selected .year-label {
    fill: var(--text);
    font-weight: 700;
  }
</style>
