<script setup lang="ts">
import { JIcon, provideIconDefaults } from "@jannchie/icons-vue";
import { fetch } from "void/client";
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { formatEpisode, formatTime, imageUrl } from "../format";
import { type Locale, LOCALE_NAMES, LOCALES, localePath, provideLocale, stripLocale } from "../i18n";
import { ICONS } from "../icons";
import { onShortcuts } from "../keyboard";
import LogoMark from "./LogoMark.vue";
import { cycleTheme, initTheme, themePref } from "../theme";
import { bangumiInView, searchBangumi } from "../bangumi-index";
import { fetchDetail } from "../detail";
import type { BangumiDetail } from "../server/bangumi";
import "../theme.css";

/** 首页与作品页 /b/:id 共用的整个应用；服务端渲染出面板内容（利于 SEO），地图只在浏览器里挂载 */
const props = defineProps<{
  /** 页面语言，由 URL 决定（简体中文无前缀，其余为 /zh-hant、/ja、/en） */
  lang: Locale;
  initialDetail?: BangumiDetail | null;
  /** 概览里展示的热门作品 */
  popular?: { id: number; cn: string | null; title: string | null; en: string | null; cover: string | null; pointCount: number }[];
}>();

provideIconDefaults({ size: 16 });
const { locale, t, pickName, subName, markOf, cityOf, categoryOf, localName } = provideLocale(props.lang);

/** 换语言就是去另一种语言的同一个页面（服务端按语言渲染），作品、地标、搜索词、视野都保留 */
function switchLocale(next: Locale) {
  location.href = localePath(next, stripLocale(location.pathname)) + location.search + location.hash;
}

// 名称里有假名就标为日语，让日文原名始终用日文字体（汉字在中日文字体里字形不同）
const KANA = /[぀-ヿ]/;
const setLang = (el: HTMLElement) => (KANA.test(el.textContent ?? "") ? (el.lang = "ja") : el.removeAttribute("lang"));
const vAutoLang = { mounted: setLang, updated: setLang };

const THEME_LABEL = { auto: "themeAuto", light: "themeLight", dark: "themeDark" } as const;

// 图片偶尔会因为图床限流或网络抖动加载失败：隔一会儿重试两次，仍失败就显示占位底色，不出现破图图标
function retryImage(e: Event) {
  const img = e.target as HTMLImageElement;
  const tries = Number(img.dataset.tries ?? 0);
  if (tries >= 2) {
    img.classList.add("img-failed");
    return;
  }
  img.dataset.tries = String(tries + 1);
  const url = new URL(img.src);
  url.searchParams.set("retry", String(tries + 1));
  setTimeout(() => (img.src = url.href), 800 * (tries + 1));
}

// maplibre 体积大且只在浏览器里用，单独分包，也不进服务端 bundle
const PilgrimMap = defineAsyncComponent(() => import("./PilgrimMap.vue"));
const mounted = ref(false);

/** 苹果设备用 Apple 地图，其余用 Google 地图（服务端渲染时先按 Google 出链接，挂载后再判断） */
const appleMaps = ref(false);
const mapsUrl = (p: { lat: number; lng: number; name: string | null; cn: string | null }) =>
  appleMaps.value
    ? `https://maps.apple.com/?ll=${p.lat},${p.lng}&q=${encodeURIComponent(pickName({ cn: p.cn, original: p.name, i18n: p.i18n }) || `${p.lat},${p.lng}`)}`
    : `https://www.google.com/maps/search/?api=1&query=${p.lat}%2C${p.lng}`;

interface SearchResult {
  bangumis: Awaited<ReturnType<typeof searchBangumi>>;
  points: Awaited<ReturnType<typeof fetchSearch>>["points"];
}
const fetchSearch = (q: string) => fetch("/v1/search", { query: { q } });

const detail = shallowRef<BangumiDetail | null>(props.initialDetail ?? null);
const focusPointId = ref<string | null>(null);
const query = ref("");
const results = shallowRef<SearchResult | null>(null);
const searching = ref(false);

const selected = computed(() =>
  detail.value
    ? {
        bangumiId: detail.value.id,
        color: detail.value.color,
        points: detail.value.points.map((p) => ({ id: p.id, name: pickName({ cn: p.cn, original: p.name, i18n: p.i18n }), lng: p.lng, lat: p.lat })),
      }
    : null,
);

// 地标列表分批渲染：首屏（含服务端渲染）只出前一批，滚到底再追加；上千个地标的作品也不卡
const PAGE = 60;
const visibleCount = ref(PAGE);
const visiblePoints = computed(() => detail.value?.points.slice(0, visibleCount.value) ?? []);
const moreSentinel = ref<HTMLElement>();
let moreObserver: IntersectionObserver | undefined;
watch(moreSentinel, (el) => {
  moreObserver?.disconnect();
  if (!el) return;
  moreObserver = new IntersectionObserver(([e]) => {
    if (e.isIntersecting) visibleCount.value += PAGE * 2;
  }, { rootMargin: "400px" });
  moreObserver.observe(el);
});

// 作品标题区滚出可视范围时，列表顶部浮出作品名
const titleRow = ref<HTMLElement>();
const headHidden = ref(false);
function onDetailScroll(e: Event) {
  const row = titleRow.value;
  headHidden.value = !!row && row.getBoundingClientRect().bottom < (e.target as HTMLElement).getBoundingClientRect().top;
}

async function select(bangumiId: number, pointId: string | null = null) {
  if (detail.value?.id !== bangumiId) {
    detail.value = await fetchDetail(bangumiId);
    visibleCount.value = PAGE;
    headHidden.value = false;
  }
  const index = pointId ? detail.value.points.findIndex((p) => p.id === pointId) : -1;
  if (index >= visibleCount.value) visibleCount.value = index + PAGE;
  if (sheet.value === "peek") sheet.value = "half";
  focusPointId.value = pointId;
  await nextTick(); // 新作品的列表要等渲染后才能滚动到选中项
  if (pointId) document.getElementById(`p-${pointId}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function clearSelection() {
  detail.value = null;
  focusPointId.value = null;
  headHidden.value = false;
}

// ---- 手机端底部抽屉：peek 只露出搜索框，half 半屏，full 接近全屏；拖动把手切换 ----
type Sheet = "peek" | "half" | "full";
const sheet = ref<Sheet>(props.initialDetail ? "half" : "peek");
let drag: { y: number; height: number } | null = null;
const dragHeight = ref<number | null>(null);
function onHandleDown(e: PointerEvent) {
  drag = { y: e.clientY, height: panel.value!.getBoundingClientRect().height };
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}
function onHandleMove(e: PointerEvent) {
  // 位移很小时仍算轻点，不进入拖动
  if (drag && (dragHeight.value != null || Math.abs(e.clientY - drag.y) > 6)) {
    dragHeight.value = Math.max(72, drag.height + drag.y - e.clientY);
  }
}
function onHandleUp() {
  if (!drag || dragHeight.value == null) {
    // 轻点把手：在 peek 和 half 之间切换
    sheet.value = sheet.value === "peek" ? "half" : "peek";
  } else {
    const ratio = dragHeight.value / innerHeight;
    sheet.value = ratio < 0.25 ? "peek" : ratio < 0.7 ? "half" : "full";
  }
  drag = null;
  dragHeight.value = null;
}

// 搜索：输入停顿 250ms 后请求
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;
watch(query, (q) => {
  clearTimeout(timer);
  if (!q.trim()) {
    results.value = null;
    return;
  }
  timer = setTimeout(async () => {
    const id = ++seq;
    searching.value = true;
    try {
      // 作品在浏览器里模糊匹配（全语种、即时）；地标五万多条，交给服务端的全文索引
      const [bangumis, { points }] = await Promise.all([searchBangumi(q), fetchSearch(q.trim())]);
      if (id === seq) results.value = { bangumis, points };
    } finally {
      if (id === seq) searching.value = false;
    }
  }, 250);
});

async function pickResult(bangumiId: number, pointId: string | null = null) {
  query.value = "";
  results.value = null;
  await select(bangumiId, pointId);
}

// 状态写进 URL，链接即可分享、收藏：路径是作品（/b/:id 由服务端渲染，可被收录），?p 是地标，
// ?q 是搜索词（也是 OpenSearch 的入口），#map 是地图视野（由 maplibre 维护，这里原样保留）
const debouncedQuery = ref("");
let queryTimer: ReturnType<typeof setTimeout> | undefined;
watch(query, (q) => {
  clearTimeout(queryTimer);
  queryTimer = setTimeout(() => (debouncedQuery.value = q.trim()), 400);
});
watch([detail, focusPointId, debouncedQuery], () => {
  const url = new URL(localePath(locale.value, detail.value ? `/b/${detail.value.id}` : "/"), location.origin);
  if (focusPointId.value) url.searchParams.set("p", focusPointId.value);
  if (debouncedQuery.value) url.searchParams.set("q", debouncedQuery.value);
  url.hash = location.hash;
  history.replaceState(null, "", url);
  document.title = detail.value
    ? `${pickName({ cn: detail.value.cn, original: detail.value.title, en: detail.value.en, i18n: detail.value.i18n })} · ${t("brand")}`
    : t("brand");
});

// 面板浮在地图上：量出它挡住的区域，交给地图做 padding，并给地图控件留出位置
const app = ref<HTMLElement>();
const panel = ref<HTMLElement>();
const mapPadding = ref({ top: 0, right: 0, bottom: 0, left: 0 });
// 来源浮层：支持 CSS 锚点定位时由样式摆放；否则打开时按按钮位置算一次
const creditsBtn = ref<HTMLElement>();
const creditsPop = ref<HTMLElement>();
function onCreditsToggle(e: Event) {
  if ((e as ToggleEvent).newState !== "open" || CSS.supports("anchor-name: --a")) return;
  const r = creditsBtn.value!.getBoundingClientRect();
  Object.assign(creditsPop.value!.style, { left: `${r.left - 4}px`, bottom: `${innerHeight - r.top + 8}px` });
}

type Bounds = { west: number; south: number; east: number; north: number };
const inView = shallowRef<Awaited<ReturnType<typeof bangumiInView>> | null>(null);
let viewSeq = 0;
async function onView(bounds: Bounds) {
  const id = ++viewSeq;
  const list = await bangumiInView(bounds);
  if (id === viewSeq) inView.value = list;
}
const overviewList = computed(() => inView.value ?? props.popular?.map((b) => ({ ...b, inView: b.pointCount })) ?? []);

let panelObserver: ResizeObserver | undefined;

// ---- 键盘快捷键（按 ? 查看）----
const mapView = ref<{ zoomIn(): void; zoomOut(): void; locate(): void }>();
const searchInput = ref<HTMLInputElement>();
const shortcutsPop = ref<HTMLElement>();

function focusSearch() {
  searchInput.value?.focus();
  searchInput.value?.select();
}
/** Esc 逐层退出：清空搜索 → 离开输入框 → 取消选中地标 → 返回概览 */
function escape(e: KeyboardEvent) {
  if (shortcutsPop.value?.matches(":popover-open")) return false; // popover 自己会关
  if (query.value) query.value = "";
  else if (e.target === searchInput.value) searchInput.value!.blur();
  else if (focusPointId.value) focusPointId.value = null;
  else if (detail.value) clearSelection();
  else return false;
}
/** 在作品的地标之间移动；没有选中地标时从第一个开始 */
function stepPoint(delta: number) {
  const points = detail.value?.points;
  if (!points?.length) return false;
  const i = points.findIndex((p) => p.id === focusPointId.value);
  const next = i < 0 ? 0 : Math.min(points.length - 1, Math.max(0, i + delta));
  void select(detail.value!.id, points[next].id);
}
/** 搜索结果：↑↓ 在输入框与结果之间移动焦点，回车即点击 */
function stepRow(e: KeyboardEvent, delta: number) {
  const list = [...panel.value!.querySelectorAll<HTMLElement>(".row")];
  if (!list.length) return false;
  const i = list.indexOf(e.target as HTMLElement);
  if (i + delta < 0) searchInput.value?.focus();
  else list[Math.min(list.length - 1, i + delta)].focus();
}
const arrow = (delta: number) => (e: KeyboardEvent) => {
  if ((e.target as HTMLElement).closest?.(".maplibregl-map")) return false; // 地图有焦点时方向键平移地图
  return query.value.trim() ? stepRow(e, delta) : stepPoint(delta);
};

let offShortcuts: (() => void) | undefined;
function bindShortcuts() {
  offShortcuts = onShortcuts({
    "/": focusSearch,
    "mod+k": focusSearch,
    Escape: escape,
    ArrowDown: arrow(1),
    ArrowUp: arrow(-1),
    j: () => stepPoint(1),
    k: () => stepPoint(-1),
    o: () => {
      const p = detail.value?.points.find((p) => p.id === focusPointId.value);
      if (!p) return false;
      open(mapsUrl(p), "_blank", "noopener");
    },
    "+": () => mapView.value?.zoomIn(),
    "=": () => mapView.value?.zoomIn(),
    "-": () => mapView.value?.zoomOut(),
    l: () => mapView.value?.locate(),
    t: () => cycleTheme(),
    "?": () => shortcutsPop.value?.togglePopover(),
  });
}

const SHORTCUTS = computed(() => [
  { keys: ["/", "Ctrl K"], label: t("kbSearch") },
  { keys: ["Esc"], label: t("back") },
  { keys: ["J", "K", "↓", "↑"], label: t("kbPoints") },
  { keys: ["O"], label: t("openInMaps") },
  { keys: ["+", "−"], label: `${t("zoomIn")} / ${t("zoomOut")}` },
  { keys: ["L"], label: t("locate") },
  { keys: ["T"], label: t("kbTheme") },
  { keys: ["?"], label: t("shortcuts") },
]);

onMounted(() => {
  appleMaps.value = /iPhone|iPad|Macintosh/.test(navigator.userAgent);
  bindShortcuts();
  mounted.value = true;
  initTheme();
  panelObserver = new ResizeObserver(() => {
    const a = app.value!.getBoundingClientRect();
    const r = panel.value!.getBoundingClientRect();
    const beside = r.width < a.width * 0.6; // 桌面端在左侧，手机端在底部
    mapPadding.value = beside
      ? { top: 0, right: 0, bottom: 0, left: r.right - a.left }
      : { top: 0, right: 0, bottom: a.bottom - r.top, left: 0 };
  });
  panelObserver.observe(panel.value!);
  panelObserver.observe(app.value!);
  // ?p= 定位地标（作品页）；旧链接 /?b=…&p=…
  const params = new URLSearchParams(location.search);
  const b = Number(params.get("b")) || detail.value?.id;
  if (b) void select(b, params.get("p"));
  const q = params.get("q");
  if (q) {
    query.value = q;
    sheet.value = "full";
  }
  if (import.meta.env.PROD && "serviceWorker" in navigator) void navigator.serviceWorker.register("/sw.js");
});
onBeforeUnmount(() => {
  panelObserver?.disconnect();
  moreObserver?.disconnect();
  offShortcuts?.();
});
</script>

<template>
  <div ref="app" class="app" :style="{ '--panel-inset-bottom': `${mapPadding.bottom}px` }">
    <PilgrimMap
      v-if="mounted"
      ref="mapView"
      :selected="selected"
      :focus-point-id="focusPointId"
      :padding="mapPadding"
      @pick="(b, p) => select(b, p)"
      @view="onView"
    />

    <aside
      ref="panel"
      class="panel"
      :class="`sheet-${sheet}`"
      :style="dragHeight != null ? { height: `${dragHeight}px`, transition: 'none' } : undefined"
    >
      <div
        class="handle"
        @pointerdown="onHandleDown"
        @pointermove="onHandleMove"
        @pointerup="onHandleUp"
        @pointercancel="onHandleUp"
      />
      <label class="search">
        <button
          v-if="detail && !query.trim()"
          type="button"
          class="icon-btn lead"
          :title="`${t('back')} (Esc)`"
          :aria-label="t('back')"
          @click.prevent="clearSelection"
        >
          <JIcon :icon="ICONS.back" :size="18" />
        </button>
        <JIcon v-else :icon="ICONS.search" class="muted" />
        <input ref="searchInput" v-model="query" type="search" :placeholder="t('search')" :aria-label="t('search')" autocomplete="off" @focus="sheet = 'full'" />
        <button v-if="query" class="icon-btn" :title="t('clear')" :aria-label="t('clear')" @click="query = ''">
          <JIcon :icon="ICONS.clear" />
        </button>
      </label>

      <!-- 搜索结果 -->
      <section v-if="query.trim()" class="scroll">
        <div v-if="searching && !results" class="empty"><JIcon :icon="ICONS.loading" :size="28" /></div>
        <template v-else-if="results">
          <div v-if="!results.bangumis.length && !results.points.length" class="empty">
            <JIcon :icon="ICONS.noResult" :size="28" />
          </div>
          <button v-for="b in results.bangumis" :key="b.id" class="row" @click="pickResult(b.id)">
            <img @error="retryImage" v-if="b.cover" :src="imageUrl(b.cover)" class="cover-sm" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="cover-sm placeholder"><JIcon :icon="ICONS.bangumi" /></span>
            <span class="row-main">
              <strong v-auto-lang>{{ pickName({ cn: b.cn, original: b.title, en: b.en, i18n: b.i18n }) }}</strong>
              <small v-auto-lang v-if="subName({ cn: b.cn, original: b.title, en: b.en, i18n: b.i18n })">{{ subName({ cn: b.cn, original: b.title, en: b.en, i18n: b.i18n }) }}</small>
            </span>
            <span class="stat"><JIcon :icon="ICONS.point" :size="14" /><span class="tx">{{ b.pointCount }}</span></span>
          </button>
          <hr v-if="results.bangumis.length && results.points.length" />
          <button
            v-for="p in results.points"
            :key="`${p.bangumiId}:${p.id}`"
            class="row"
            @click="pickResult(p.bangumiId, p.id)"
          >
            <img @error="retryImage" v-if="p.image" :src="imageUrl(p.image)" class="thumb-sm" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="thumb-sm placeholder"><JIcon :icon="ICONS.point" /></span>
            <span class="row-main">
              <strong v-auto-lang>{{ pickName({ cn: p.cn, original: p.name, i18n: p.i18n }) }}</strong>
              <small v-auto-lang>{{ pickName({ cn: p.bangumiCn, original: p.bangumiTitle, en: p.bangumiEn, i18n: p.bangumiI18n }) }}</small>
            </span>
          </button>
        </template>
      </section>

      <!-- 作品详情 -->
      <section v-else-if="detail" :key="detail.id" class="scroll" @scroll.passive="onDetailScroll">
        <!-- 标题区滚出去后，作品名浮在列表顶部；点一下回到顶部 -->
        <div class="detail-bar" :class="{ shown: headHidden }" :aria-hidden="!headHidden">
          <button v-auto-lang type="button" class="bar-title" tabindex="-1" @click="($event.currentTarget as HTMLElement).closest('.scroll')!.scrollTo({ top: 0, behavior: 'smooth' })">
            {{ pickName({ cn: detail.cn, original: detail.title, en: detail.en, i18n: detail.i18n }) }}
          </button>
        </div>
        <div class="detail-head" :style="{ '--bangumi-color': detail.color ?? 'var(--accent)' }">
          <div ref="titleRow" class="title-row">
            <img @error="retryImage" v-if="detail.cover" :src="imageUrl(detail.cover)" class="cover" referrerpolicy="no-referrer" alt="" />
            <div class="title-main">
              <h2 v-auto-lang>{{ pickName({ cn: detail.cn, original: detail.title, en: detail.en, i18n: detail.i18n }) }}</h2>
              <p v-auto-lang v-if="subName({ cn: detail.cn, original: detail.title, en: detail.en, i18n: detail.i18n })" class="sub">
                {{ subName({ cn: detail.cn, original: detail.title, en: detail.en, i18n: detail.i18n }) }}
              </p>
              <p class="meta">
                <span v-if="detail.cat" class="stat"><JIcon :icon="ICONS.bangumi" :size="14" /><span class="tx">{{ categoryOf(detail.cat) }}</span></span>
                <span v-if="detail.city" class="stat"><JIcon :icon="ICONS.city" :size="14" /><span v-auto-lang class="tx">{{ cityOf(detail) }}</span></span>
                <span class="stat"><JIcon :icon="ICONS.point" :size="14" /><span class="tx">{{ detail.pointCount }}</span></span>
              </p>
              <p class="links">
                <a :href="`https://bgm.tv/subject/${detail.id}`" target="_blank" rel="noopener">Bangumi</a>
                <a :href="`https://www.anitabi.cn/map?bangumiId=${detail.id}`" target="_blank" rel="noopener">Anitabi</a>
                <a :href="`/v1/bangumi/${detail.id}/kml?lang=${locale}`" class="stat" :title="t('exportKml')" download>
                  <JIcon :icon="ICONS.download" :size="14" /><span class="tx">KML</span>
                </a>
              </p>
            </div>
          </div>
        </div>
        <ol class="points">
          <li
            v-for="p in visiblePoints"
            :id="`p-${p.id}`"
            :key="p.id"
            :class="{ active: p.id === focusPointId }"
            @click="select(detail.id, p.id)"
          >
            <figure v-if="p.image">
              <img @error="retryImage"
                :src="imageUrl(p.image, p.id === focusPointId ? 'h360' : 'h160')"
                loading="lazy"
                referrerpolicy="no-referrer"
                alt=""
              />
              <figcaption v-if="p.origin">
                <a :href="p.originLink ?? undefined" target="_blank" rel="noopener" @click.stop>
                  <JIcon :icon="ICONS.credit" :size="12" />{{ p.origin }}
                </a>
              </figcaption>
            </figure>
            <div class="point-body">
              <strong v-auto-lang>{{ pickName({ cn: p.cn, original: p.name, i18n: p.i18n }) }}</strong>
              <!-- 列表里只显示当前语言；展开的地标再给出当地原名，方便到现场对照 -->
              <small v-if="p.id === focusPointId && localName(p)" v-auto-lang>{{ localName(p) }}</small>
              <span v-if="p.ep || p.s" class="meta">
                <span v-if="p.ep" class="stat"><JIcon :icon="ICONS.episode" :size="14" /><span class="tx">{{ formatEpisode(p.ep) }}</span></span>
                <span v-if="p.s" class="stat"><JIcon :icon="ICONS.time" :size="14" /><span class="tx">{{ formatTime(p.s) }}</span></span>
              </span>
              <p v-if="p.id === focusPointId && markOf(p).text" v-auto-lang class="mark">{{ markOf(p).text }}</p>
              <small v-if="p.id === focusPointId && markOf(p).machine" class="mt" :title="p.mark ?? undefined">{{ t("machineTranslated") }}</small>
              <a
                v-if="p.id === focusPointId"
                :href="mapsUrl(p)"
                target="_blank"
                rel="noopener"
                class="open-maps"
                :title="t('openInMaps')"
                :aria-label="t('openInMaps')"
                @click.stop
              >
                <JIcon :icon="ICONS.navigate" :size="16" />
              </a>
            </div>
          </li>
        </ol>
        <div v-if="visibleCount < detail.points.length" ref="moreSentinel" class="more" />
      </section>

      <!-- 概览 -->
      <section v-else class="scroll overview">
        <h1><LogoMark :size="24" /><span class="tx">{{ t("brand") }}</span></h1>
        <!-- 起初是热门作品（服务端渲染的真实链接，爬虫能走到每个作品页）；地图一动就换成视野内的作品 -->
        <h2 class="section-label">{{ t(inView ? "inView" : "popular") }}</h2>
        <ul v-if="overviewList.length" class="popular">
          <li v-for="b in overviewList" :key="b.id">
            <a :href="localePath(locale, `/b/${b.id}`)" @click.prevent="select(b.id)">
              <img @error="retryImage" v-if="b.cover" :src="imageUrl(b.cover)" loading="lazy" referrerpolicy="no-referrer" alt="" />
              <span v-auto-lang class="popular-name">{{ pickName({ cn: b.cn, original: b.title, en: b.en, i18n: b.i18n }) }}</span>
              <span class="stat"><JIcon :icon="ICONS.point" :size="12" /><span class="tx">{{ b.inView }}</span></span>
            </a>
          </li>
        </ul>
      </section>

      <footer class="foot">
        <!-- OSM 要求地图署名始终可见：署名本身就是按钮，点开是全部来源、源代码与快捷键（原生 popover，点外部或 Esc 关闭） -->
        <button ref="creditsBtn" type="button" class="credits-btn" popovertarget="credits" :title="t('credits')">
          <JIcon :icon="ICONS.info" :size="14" /><span class="tx">© OpenStreetMap</span>
        </button>
        <div id="credits" ref="creditsPop" popover class="credits-pop" @toggle="onCreditsToggle">
          <a href="https://www.anitabi.cn/" target="_blank" rel="noopener">Anitabi</a>
          <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>
          <a href="https://bgm.tv/" target="_blank" rel="noopener">Bangumi</a>
          <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a>
          <a href="https://openmaptiles.org/" target="_blank" rel="noopener">© OpenMapTiles</a>
          <a href="https://openfreemap.org/" target="_blank" rel="noopener">OpenFreeMap</a>
          <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noopener">Terrain Tiles</a>
          <hr />
          <a class="stat" href="https://github.com/Jannchie/junrei" target="_blank" rel="noopener">
            <JIcon :icon="ICONS.github" :size="14" /><span class="tx">{{ t("source") }}</span>
          </a>
          <button type="button" class="stat kb-btn" popovertarget="shortcuts">
            <JIcon :icon="ICONS.keyboard" :size="14" /><span class="tx">{{ t("shortcuts") }}</span>
          </button>
        </div>
        <div id="shortcuts" ref="shortcutsPop" popover class="shortcuts-pop">
          <h3>{{ t("shortcuts") }}</h3>
          <dl>
            <template v-for="s in SHORTCUTS" :key="s.label">
              <dt><kbd v-for="k in s.keys" :key="k">{{ k }}</kbd></dt>
              <dd>{{ s.label }}</dd>
            </template>
          </dl>
        </div>
        <button
          type="button"
          class="icon-link"
          :title="t(THEME_LABEL[themePref])"
          :aria-label="t(THEME_LABEL[themePref])"
          @click="cycleTheme"
        >
          <JIcon :icon="ICONS[THEME_LABEL[themePref]]" :size="14" />
        </button>
        <label class="lang" :title="t('language')">
          <JIcon :icon="ICONS.language" :size="14" />
          <select :value="locale" :aria-label="t('language')" @change="switchLocale(($event.target as HTMLSelectElement).value as Locale)">
            <option v-for="l in LOCALES" :key="l" :value="l">{{ LOCALE_NAMES[l] }}</option>
          </select>
        </label>
      </footer>
    </aside>
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}
html,
body {
  margin: 0;
  height: 100%;
  background: var(--bg-solid);
  color: var(--fg);
}
/* 中日文共用汉字编码但字形不同，按语言挑字体：系统字体优先，再落到思源/Noto */
:root,
:lang(zh-Hans) {
  font-family: -apple-system, system-ui, "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC", "Source Han Sans SC", sans-serif;
}
:lang(zh-Hant) {
  font-family: -apple-system, system-ui, "PingFang TC", "Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans TC", "Source Han Sans TC", sans-serif;
}
:lang(ja) {
  font-family: -apple-system, system-ui, "Hiragino Sans", "Yu Gothic UI", "Meiryo UI", "Noto Sans JP", "Source Han Sans JP", sans-serif;
}
:lang(en) {
  font-family: -apple-system, system-ui, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
}
a {
  color: inherit;
}
img.img-failed {
  /* 隐藏破图图标与替代文字，只留占位底色 */
  color: transparent;
  font-size: 0;
  background: var(--hover);
}

/* 滚动条：各系统统一成细的半透明样式。标准属性给 Firefox 与新版 Chromium，
   ::-webkit-scrollbar 给 Safari 与旧版 Chromium（同时设置时 Chromium 以标准属性为准） */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--scroll-thumb) transparent;
}
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track,
::-webkit-scrollbar-corner {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--scroll-thumb);
  background-clip: padding-box;
  border: 3px solid transparent; /* 用透明边框把滑块收窄并留出边距 */
  border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover {
  background-color: var(--scroll-thumb-hover);
}
</style>

<style scoped>
.app {
  position: fixed;
  inset: 0;
}
.panel {
  position: absolute;
  top: 12px;
  left: 12px;
  bottom: 12px;
  width: 380px;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-radius: 16px;
  box-shadow: var(--shadow);
  backdrop-filter: var(--glass);
  overflow: hidden;
}
.handle {
  display: none;
}
@media (max-width: 640px) {
  .panel {
    top: auto;
    left: 0;
    right: 0;
    bottom: 0;
    width: auto;
    padding-bottom: env(safe-area-inset-bottom);
    border-radius: 16px 16px 0 0;
    transition: height 0.28s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .sheet-peek {
    height: calc(84px + env(safe-area-inset-bottom));
  }
  .sheet-half {
    height: 46dvh;
  }
  .sheet-full {
    height: calc(100dvh - 48px - env(safe-area-inset-top));
  }
  .handle {
    display: block;
    flex: none;
    height: 22px;
    margin-bottom: -10px;
    touch-action: none;
    cursor: grab;
  }
  .handle::before {
    content: "";
    display: block;
    width: 36px;
    height: 5px;
    margin: 8px auto 0;
    border-radius: 3px;
    background: var(--muted);
    opacity: 0.45;
  }
  .search input {
    font-size: 16px; /* 小于 16px 时 iOS 聚焦会自动放大页面 */
  }
}
.muted {
  color: var(--muted);
}
.stat {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-variant-numeric: tabular-nums;
}
/* 图标与文字垂直居中：把文字行盒裁到大写字母高度与基线，否则字体上下留白不对称，图标会显得偏上 */
.tx {
  text-box: trim-both cap alphabetic;
}
.icon-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  color: var(--muted);
  background: none;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}
.icon-btn:hover {
  color: var(--fg);
  background: var(--hover);
}
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px;
  padding: 0 6px 0 12px;
  background: var(--hover);
  border: 1px solid transparent;
  border-radius: 10px;
}
.search:has(.lead) {
  padding-left: 4px;
}
.search:focus-within {
  border-color: var(--accent);
}
.search input {
  flex: 1;
  min-width: 0;
  padding: 10px 0;
  font: inherit;
  font-size: 15px;
  color: inherit;
  background: none;
  border: 0;
  outline: none;
}
.search input::-webkit-search-cancel-button {
  display: none;
}
.search input::placeholder {
  color: var(--muted);
}
.scroll {
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain; /* 滚到头不带着整页回弹 */
  border-top: 1px solid var(--line);
}
.empty {
  display: grid;
  place-items: center;
  padding: 40px 0;
  color: var(--muted);
}
hr {
  margin: 6px 16px;
  border: 0;
  border-top: 1px solid var(--line);
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 16px;
  font: inherit;
  color: inherit;
  text-align: left;
  background: none;
  border: 0;
  cursor: pointer;
}
.row:hover {
  background: var(--hover);
}
.row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.row-main strong,
.row-main small {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.row-main small,
.row .stat {
  color: var(--muted);
  font-size: 12px;
}
.cover-sm {
  width: 36px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  flex: none;
}
.thumb-sm {
  width: 64px;
  height: 36px;
  object-fit: cover;
  border-radius: 4px;
  flex: none;
}
.placeholder {
  display: grid;
  place-items: center;
  color: var(--muted);
  background: var(--hover);
}
/* 高度为 0 的吸顶容器，不占位置；作品名条叠在列表上方 */
.detail-bar {
  position: sticky;
  top: 0;
  z-index: 2;
  height: 0;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}
.detail-bar.shown {
  opacity: 1;
  pointer-events: auto;
}
.bar-title {
  display: block;
  width: 100%;
  padding: 10px 16px;
  overflow: hidden;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  color: inherit;
  text-align: left;
  white-space: nowrap;
  text-overflow: ellipsis;
  /* 面板本身半透明；这条叠一层同色并模糊下方滚过的内容 */
  background: var(--bg);
  backdrop-filter: var(--glass);
  border: 0;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}
.detail-head {
  padding: 14px 16px;
  border-bottom: 3px solid var(--bangumi-color);
}
.title-row {
  display: flex;
  gap: 12px;
}
.title-main {
  min-width: 0;
}
.cover {
  width: 72px;
  height: 100px;
  object-fit: cover;
  border-radius: 6px;
  flex: none;
}
h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.3;
}
.sub {
  margin: 2px 0 0;
  font-size: 13px;
  color: var(--muted);
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--muted);
}
.links {
  display: flex;
  gap: 12px;
  margin: 8px 0 0;
  font-size: 13px;
}
.points {
  margin: 0;
  padding: 0;
  list-style: none;
}
.points li {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 6px 12px;
  align-items: start;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}
.points li:hover {
  background: var(--hover);
}
.points li:not(:has(figure)),
.points li.active {
  grid-template-columns: minmax(0, 1fr);
}
.points li:not(.active) figcaption {
  display: none;
}
.points li.active {
  background: var(--hover);
  box-shadow: inset 3px 0 0 var(--accent);
}
figure {
  position: relative;
  margin: 0;
}
figure img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 6px;
  background: var(--line);
}
figcaption {
  position: absolute;
  right: 6px;
  bottom: 6px;
  max-width: 70%;
  padding: 2px 6px;
  font-size: 11px;
  color: #fff;
  background: rgb(0 0 0 / 0.5);
  border-radius: 4px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
figcaption a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  text-decoration: none;
}
.point-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.point-body > small {
  font-size: 12px;
  color: var(--muted);
}
.point-body .meta {
  margin-top: 4px;
  font-size: 12px;
}
.more {
  height: 1px;
}
/* 选中地标标题右侧的小圆按钮，不额外占一行 */
.point-body {
  position: relative;
}
.points li.active .point-body {
  padding-right: 36px;
}
.open-maps {
  position: absolute;
  top: 0;
  right: 0;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  color: #fff;
  background: var(--accent);
  border-radius: 50%;
}
.mt {
  font-size: 11px;
  color: var(--muted);
}
.mark {
  margin: 4px 0 0;
  font-size: 13px;
  white-space: pre-wrap;
}
.overview {
  padding: 4px 16px;
}
.overview h1 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 18px;
  font-size: 20px;
}
.section-label {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}
.popular {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px 10px;
  margin: 0 0 16px;
  padding: 0;
  list-style: none;
}
.popular a {
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-decoration: none;
}
.popular img {
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  border-radius: 8px;
  background: var(--hover);
}
.popular-name {
  font-size: 12px;
  font-weight: 600;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.popular .stat {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
  font-weight: 400;
}
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 8px 16px;
  font-size: 11px;
  color: var(--muted);
  border-top: 1px solid var(--line);
}
.credits-btn {
  anchor-name: --credits;
  flex: 1;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 4px 6px;
  margin-left: -6px;
  font: inherit;
  color: inherit;
  background: none;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
  justify-self: start;
}
.icon-link {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  padding: 0;
  color: inherit;
  background: none;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}
.icon-link:hover {
  background: var(--hover);
}
.credits-btn:hover,
.credits-btn:has(+ .credits-pop:popover-open) {
  color: var(--fg);
  background: var(--hover);
}
.credits-pop {
  /* 覆盖 popover 默认的居中；位置由锚点（或 onCreditsToggle）决定 */
  position: fixed;
  inset: auto;
  margin: 0 0 8px -4px;
  position-anchor: --credits;
  position-area: top span-right;
  min-width: 160px;
  padding: 10px 12px;
  font-size: 12px;
  color: var(--muted);
  background: var(--bg);
  border: 0;
  border-radius: 12px;
  box-shadow: var(--shadow);
  backdrop-filter: var(--glass);
}
.credits-pop:popover-open {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.credits-pop hr {
  align-self: stretch;
  margin: 4px 0;
}
.credits-pop a,
.credits-pop button {
  padding: 0;
  font: inherit;
  color: inherit;
  text-decoration: none;
  background: none;
  border: 0;
  cursor: pointer;
}
.credits-pop a:hover,
.credits-pop button:hover {
  color: var(--fg);
}
/* 触屏设备没有键盘，不显示快捷键入口 */
@media (hover: none) {
  .kb-btn {
    display: none;
  }
}
.shortcuts-pop {
  padding: 16px 20px;
  color: var(--fg);
  background: var(--bg);
  border: 0;
  border-radius: 16px;
  box-shadow: var(--shadow);
  backdrop-filter: var(--glass);
}
.shortcuts-pop::backdrop {
  background: rgb(0 0 0 / 0.15);
}
.shortcuts-pop h3 {
  margin: 0 0 12px;
  font-size: 14px;
}
.shortcuts-pop dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px 16px;
  align-items: center;
  margin: 0;
  font-size: 13px;
}
.shortcuts-pop dt {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}
.shortcuts-pop dd {
  margin: 0;
  color: var(--muted);
}
kbd {
  min-width: 22px;
  padding: 2px 6px;
  font: inherit;
  font-size: 12px;
  line-height: 1.4;
  text-align: center;
  background: var(--hover);
  border-radius: 5px;
  box-shadow: inset 0 -1px 0 var(--line);
}
.foot a {
  text-decoration: none;
}
.foot a:hover {
  color: var(--fg);
}
.lang {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
}
.lang:hover {
  color: var(--fg);
  background: var(--hover);
}
.lang select {
  /* 可定制 select 的内容默认贴着顶部排，用 flex 居中，才能和图标对齐 */
  display: inline-flex;
  align-items: center;
  font: inherit;
  line-height: 1; /* 要写在 font 简写之后，否则会被它重置 */
  color: inherit;
  background: none;
  border: 0;
  outline: none;
  cursor: pointer;
  appearance: none;
}
/* 渐进增强：可定制 select（appearance: base-select）。不支持的浏览器用系统下拉，手机上即系统选择器 */
@supports (appearance: base-select) {
  .lang select,
  .lang select::picker(select) {
    appearance: base-select;
  }
  .lang select {
    padding: 0;
  }
  .lang select::picker-icon {
    display: none;
  }
  .lang select::picker(select) {
    min-width: 132px;
    padding: 4px;
    margin-block: 8px;
    color: var(--fg);
    background: var(--bg);
    border: 0;
    border-radius: 12px;
    box-shadow: var(--shadow);
    backdrop-filter: var(--glass);
  }
  .lang option {
    padding: 7px 10px;
    font-size: 13px;
    border-radius: 8px;
  }
  .lang option:hover,
  .lang option:focus-visible {
    background: var(--hover);
  }
  .lang option:checked {
    font-weight: 600;
  }
  .lang option::checkmark {
    order: 1;
    margin-left: auto;
    color: var(--accent);
  }
}
</style>
