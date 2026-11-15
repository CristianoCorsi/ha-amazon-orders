<script lang="ts">
  import {
    mdiViewDashboardOutline,
    mdiPackageVariantClosed,
    mdiCalendarClockOutline,
    mdiChartBar,
    mdiCogOutline,
    mdiMagnify,
    mdiArrowRight,
    mdiArrowLeft,
    mdiChevronRight,
    mdiSync,
    mdiShieldCheckOutline,
    mdiKeyboardReturn,
    mdiCheck,
    mdiClose,
    mdiDownload,
    mdiOpenInNew,
    mdiContentCopy,
    mdiPause,
    mdiPlay,
    mdiAlertCircleOutline,
    mdiLogout,
    mdiThemeLightDark,
    mdiTranslate,
    mdiFilterVariant,
    mdiClockOutline,
    mdiDotsHorizontal,
    mdiInformationOutline,
    mdiDeleteOutline,
    mdiCalendarOutline,
    mdiCheckCircleOutline,
    mdiRefresh,
    mdiArrowTopRight,
    mdiLinkVariant,
    mdiChevronDown,
    mdiTrendingDown,
    mdiTrendingUp
  } from '@mdi/js';
  let { name, size = 24 }: { name: string; size?: number } = $props();
  const icons: Record<string, string> = {
    overview: mdiViewDashboardOutline,
    orders: mdiPackageVariantClosed,
    deadlines: mdiCalendarClockOutline,
    statistics: mdiChartBar,
    settings: mdiCogOutline,
    search: mdiMagnify,
    right: mdiArrowRight,
    back: mdiArrowLeft,
    chevron: mdiChevronRight,
    sync: mdiSync,
    warranty: mdiShieldCheckOutline,
    return: mdiKeyboardReturn,
    check: mdiCheck,
    close: mdiClose,
    download: mdiDownload,
    external: mdiOpenInNew,
    copy: mdiContentCopy,
    pause: mdiPause,
    play: mdiPlay,
    error: mdiAlertCircleOutline,
    logout: mdiLogout,
    theme: mdiThemeLightDark,
    language: mdiTranslate,
    filter: mdiFilterVariant,
    clock: mdiClockOutline,
    more: mdiDotsHorizontal,
    info: mdiInformationOutline,
    purge: mdiDeleteOutline,
    calendar: mdiCalendarOutline,
    success: mdiCheckCircleOutline,
    refresh: mdiRefresh,
    arrow: mdiArrowTopRight,
    link: mdiLinkVariant,
    down: mdiChevronDown,
    decrease: mdiTrendingDown,
    increase: mdiTrendingUp
  };
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="currentColor"
  aria-hidden="true"
  focusable="false"><path d={icons[name] ?? icons.orders} /></svg
>
