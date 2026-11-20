<script lang="ts">
  import type { Monthly } from '$lib/types';
  import { money, type Locale } from '$lib/i18n';
  let {
    current,
    previous = [],
    locale,
    year,
    compact = false
  }: {
    current: Monthly[];
    previous?: Monthly[];
    locale: Locale;
    year: number;
    compact?: boolean;
  } = $props();
  // Net of refunds, so the chart matches the spending totals.
  const spendOf = (m: Monthly | undefined) => (m ? (m.net_spend ?? m.spend) : 0);
  const values = $derived(
    Array.from({ length: 12 }, (_, i) => ({
      current: spendOf(current.find((m) => Number(m.month.slice(5, 7)) === i + 1)),
      previous: spendOf(previous.find((m) => Number(m.month.slice(5, 7)) === i + 1))
    }))
  );
  let width = $state(660);
  const right = $derived(Math.max(width, 220) - 8);
  const slot = $derived((right - 42) / 12);
  const bar = $derived(Math.min(16, slot * 0.3));
  const center = (i: number) => 42 + (i + 0.5) * slot;
  const amounts = $derived(values.flatMap((v) => [v.current, v.previous]));
  const max = $derived(Math.max(...amounts, 100) * 1.08);
  const min = $derived(Math.min(...amounts, 0) * 1.08);
  const ticks = $derived(min < 0 ? [min, 0, max] : [0, max / 2, max]);
  const y = (v: number) => 166 - ((v - min) / (max - min)) * 144;
  const labels = $derived(
    Array.from({ length: 12 }, (_, i) =>
      new Intl.DateTimeFormat(locale, { month: 'short' }).format(new Date(year, i, 1))
    )
  );
</script>

<div class="chart-wrap" class:compact>
  <div bind:clientWidth={width}>
    <svg
      viewBox={`0 0 ${right + 8} 196`}
      role="img"
      aria-label={locale === 'it'
        ? `Spesa mensile ${year} a confronto con ${year - 1}`
        : `Monthly spending ${year} compared with ${year - 1}`}
    >
      {#each ticks as tick}<line
          x1="42"
          x2={right}
          y1={y(tick)}
          y2={y(tick)}
          stroke="var(--border)"
          stroke-dasharray={tick === 0 ? undefined : '3 5'}
        /><text x="35" y={y(tick) + 4} text-anchor="end" class="axis"
          >{new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(
            tick
          )}</text
        >{/each}
      {#each values as value, i}
        <g>
          {#each [value.previous, value.current] as amount, series}
            <rect
              x={center(i) + (series ? 1 : -bar - 1)}
              y={Math.min(y(amount), y(0))}
              width={bar}
              height={Math.abs(y(amount) - y(0))}
              rx="2"
              fill={series ? 'var(--primary)' : 'var(--chart-secondary)'}
            >
              <title>{year - 1 + series} {labels[i]}: {money(amount, locale)}</title>
            </rect>
          {/each}
          {#if slot >= 31 || i % 2 === 0}
            <text x={center(i)} y="188" text-anchor="middle" class="axis">{labels[i]}</text>
          {/if}
        </g>
      {/each}
    </svg>
  </div>
</div>
<div class="chart-legend">
  <span><i></i>{year}</span><span><i class="previous"></i>{year - 1}</span>
</div>
