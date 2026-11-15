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
  const values = $derived(
    Array.from({ length: 12 }, (_, i) => ({
      current: current.find((m) => Number(m.month.slice(5, 7)) === i + 1)?.spend ?? 0,
      previous: previous.find((m) => Number(m.month.slice(5, 7)) === i + 1)?.spend ?? 0
    }))
  );
  const max = $derived(Math.max(...values.flatMap((v) => [v.current, v.previous]), 100) * 1.12);
  const labels = $derived(
    Array.from({ length: 12 }, (_, i) =>
      new Intl.DateTimeFormat(locale, { month: 'short' }).format(new Date(year, i, 1))
    )
  );
</script>

<div class="chart-wrap" class:compact>
  <svg
    viewBox="0 0 660 240"
    role="img"
    aria-label={locale === 'it'
      ? `Spesa mensile ${year} a confronto con ${year - 1}`
      : `Monthly spending ${year} compared with ${year - 1}`}
  >
    {#each [0, 0.5, 1] as tick}<line
        x1="46"
        x2="650"
        y1={200 - tick * 170}
        y2={200 - tick * 170}
        stroke="var(--border)"
        stroke-dasharray="3 5"
      /><text x="35" y={204 - tick * 170} text-anchor="end" class="axis"
        >{Math.round(max * tick)}</text
      >{/each}
    {#each values as value, i}<g
        ><rect
          x={57 + i * 49.4}
          y={200 - (value.previous / max) * 170}
          width="13"
          height={Math.max((value.previous / max) * 170, 0)}
          rx="4"
          fill="var(--chart-secondary)"
          ><title>{year - 1} {labels[i]}: {money(value.previous, locale)}</title></rect
        ><rect
          x={73 + i * 49.4}
          y={200 - (value.current / max) * 170}
          width="17"
          height={Math.max((value.current / max) * 170, 0)}
          rx="4"
          fill="var(--primary)"
          ><title>{year} {labels[i]}: {money(value.current, locale)}</title></rect
        ><text x={73 + i * 49.4} y="227" text-anchor="middle" class="axis">{labels[i]}</text></g
      >{/each}
  </svg>
</div>
<div class="chart-legend">
  <span><i></i>{year}</span><span><i class="previous"></i>{year - 1}</span>
</div>
