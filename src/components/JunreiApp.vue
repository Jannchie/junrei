<script setup lang="ts">
import { JIcon, provideIconDefaults } from "@jannchie/icons-vue";
import { fetch } from "void/client";
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { formatEpisode, formatTime, imageUrl } from "../format";
import { initLocale, LOCALE_NAMES, LOCALES, locale, pickName, subName, t } from "../i18n";
import { ICONS } from "../icons";
import type { BangumiDetail } from "../server/bangumi";
import "../theme.css";

/** 首页与作品页 /b/:id 共用的整个应用；服务端渲染出面板内容（利于 SEO），地图只在浏览器里挂载 */
const props = defineProps<{
  initialDetail?: BangumiDetail | null;
  /** 概览里展示的热门作品 */
  popular?: { id: number; cn: string | null; title: string | null; en: string | null; cover: string | null; pointCount: number }[];
}>();

provideIconDefaults({ size: 16 });

// maplibre 体积大且只在浏览器里用，单独分包，也不进服务端 bundle
const PilgrimMap = defineAsyncComponent(() => import("./PilgrimMap.vue"));
const mounted = ref(false);

type SearchResult = Awaited<ReturnType<typeof fetchSearch>>;
const fetchDetail = (id: number): Promise<BangumiDetail> => fetch("/v1/bangumi/:id", { params: { id: String(id) } });
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
        points: detail.value.points.map((p) => ({ id: p.id, name: pickName({ cn: p.cn, original: p.name }), lng: p.lng, lat: p.lat })),
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

async function select(bangumiId: number, pointId: string | null = null) {
  if (detail.value?.id !== bangumiId) {
    detail.value = await fetchDetail(bangumiId);
    visibleCount.value = PAGE;
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
      const r = await fetchSearch(q.trim());
      if (id === seq) results.value = r;
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

// 选中状态写进 URL（作品页 /b/:id 由服务端渲染，可被搜索引擎收录），标题同步
watch([detail, focusPointId], () => {
  const url = new URL(detail.value ? `/b/${detail.value.id}` : "/", location.origin);
  if (focusPointId.value) url.searchParams.set("p", focusPointId.value);
  history.replaceState(null, "", url);
  document.title = detail.value
    ? `${pickName({ cn: detail.value.cn, original: detail.value.title, en: detail.value.en })} · ${t("brand")}`
    : t("brand");
});

// 面板浮在地图上：量出它挡住的区域，交给地图做 padding，并给地图控件留出位置
const app = ref<HTMLElement>();
const panel = ref<HTMLElement>();
const mapPadding = ref({ top: 0, right: 0, bottom: 0, left: 0 });
let panelObserver: ResizeObserver | undefined;

onMounted(() => {
  mounted.value = true;
  initLocale();
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
  if (import.meta.env.PROD && "serviceWorker" in navigator) void navigator.serviceWorker.register("/sw.js");
});
onBeforeUnmount(() => {
  panelObserver?.disconnect();
  moreObserver?.disconnect();
});
</script>

<template>
  <div ref="app" class="app" :style="{ '--panel-inset-bottom': `${mapPadding.bottom}px` }">
    <PilgrimMap
      v-if="mounted"
      :selected="selected"
      :focus-point-id="focusPointId"
      :padding="mapPadding"
      @pick="(b, p) => select(b, p)"
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
        <JIcon :icon="ICONS.search" class="muted" />
        <input v-model="query" type="search" :aria-label="t('search')" autocomplete="off" @focus="sheet = 'full'" />
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
            <img v-if="b.cover" :src="imageUrl(b.cover)" class="cover-sm" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="cover-sm placeholder"><JIcon :icon="ICONS.bangumi" /></span>
            <span class="row-main">
              <strong>{{ pickName({ cn: b.cn, original: b.title, en: b.en }) }}</strong>
              <small v-if="subName({ cn: b.cn, original: b.title, en: b.en })">{{ subName({ cn: b.cn, original: b.title, en: b.en }) }}</small>
            </span>
            <span class="stat"><JIcon :icon="ICONS.point" :size="14" />{{ b.pointCount }}</span>
          </button>
          <hr v-if="results.bangumis.length && results.points.length" />
          <button
            v-for="p in results.points"
            :key="`${p.bangumiId}:${p.id}`"
            class="row"
            @click="pickResult(p.bangumiId, p.id)"
          >
            <img v-if="p.image" :src="imageUrl(p.image)" class="thumb-sm" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="thumb-sm placeholder"><JIcon :icon="ICONS.point" /></span>
            <span class="row-main">
              <strong>{{ pickName({ cn: p.cn, original: p.name }) }}</strong>
              <small>{{ pickName({ cn: p.bangumiCn, original: p.bangumiTitle, en: p.bangumiEn }) }}</small>
            </span>
          </button>
        </template>
      </section>

      <!-- 作品详情 -->
      <section v-else-if="detail" class="scroll">
        <div class="detail-head" :style="{ '--bangumi-color': detail.color ?? 'var(--accent)' }">
          <button class="icon-btn back" :title="t('back')" :aria-label="t('back')" @click="clearSelection">
            <JIcon :icon="ICONS.back" :size="18" />
          </button>
          <div class="title-row">
            <img v-if="detail.cover" :src="imageUrl(detail.cover)" class="cover" referrerpolicy="no-referrer" alt="" />
            <div class="title-main">
              <h2>{{ pickName({ cn: detail.cn, original: detail.title, en: detail.en }) }}</h2>
              <p v-if="subName({ cn: detail.cn, original: detail.title, en: detail.en })" class="sub">
                {{ subName({ cn: detail.cn, original: detail.title, en: detail.en }) }}
              </p>
              <p class="meta">
                <span v-if="detail.cat" class="stat"><JIcon :icon="ICONS.bangumi" :size="14" />{{ detail.cat }}</span>
                <span v-if="detail.city" class="stat"><JIcon :icon="ICONS.city" :size="14" />{{ detail.city }}</span>
                <span class="stat"><JIcon :icon="ICONS.point" :size="14" />{{ detail.pointCount }}</span>
              </p>
              <p class="links">
                <a :href="`https://bgm.tv/subject/${detail.id}`" target="_blank" rel="noopener">Bangumi</a>
                <a :href="`https://www.anitabi.cn/map?bangumiId=${detail.id}`" target="_blank" rel="noopener">Anitabi</a>
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
              <img
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
              <strong>{{ pickName({ cn: p.cn, original: p.name }) }}</strong>
              <small v-if="subName({ cn: p.cn, original: p.name })">{{ subName({ cn: p.cn, original: p.name }) }}</small>
              <span v-if="p.ep || p.s" class="meta">
                <span v-if="p.ep" class="stat"><JIcon :icon="ICONS.episode" :size="14" />{{ formatEpisode(p.ep) }}</span>
                <span v-if="p.s" class="stat"><JIcon :icon="ICONS.time" :size="14" />{{ formatTime(p.s) }}</span>
              </span>
              <p v-if="p.id === focusPointId && p.mark" class="mark">{{ p.mark }}</p>
            </div>
          </li>
        </ol>
        <div v-if="visibleCount < detail.points.length" ref="moreSentinel" class="more" />
      </section>

      <!-- 概览 -->
      <section v-else class="scroll overview">
        <h1><JIcon :icon="ICONS.logo" :size="22" weight="bold" />{{ t("brand") }}</h1>
        <!-- 热门作品：真实链接，服务端渲染，既是入口也让爬虫能走到每个作品页 -->
        <ul v-if="popular?.length" class="popular">
          <li v-for="b in popular" :key="b.id">
            <a :href="`/b/${b.id}`" @click.prevent="select(b.id)">
              <img v-if="b.cover" :src="imageUrl(b.cover)" loading="lazy" referrerpolicy="no-referrer" alt="" />
              <span class="popular-name">{{ pickName({ cn: b.cn, original: b.title, en: b.en }) }}</span>
              <span class="stat"><JIcon :icon="ICONS.point" :size="12" />{{ b.pointCount }}</span>
            </a>
          </li>
        </ul>
      </section>

      <footer class="foot">
        <!-- OSM 要求地图署名始终可见；其余来源收进信息浮层 -->
        <details class="credits-more">
          <summary :title="t('credits')" :aria-label="t('credits')"><JIcon :icon="ICONS.info" :size="14" /></summary>
          <div class="credits-pop">
            <a href="https://www.anitabi.cn/" target="_blank" rel="noopener">Anitabi</a>
            <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>
            <a href="https://bgm.tv/" target="_blank" rel="noopener">Bangumi</a>
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a>
            <a href="https://openmaptiles.org/" target="_blank" rel="noopener">© OpenMapTiles</a>
            <a href="https://openfreemap.org/" target="_blank" rel="noopener">OpenFreeMap</a>
            <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noopener">Terrain Tiles</a>
          </div>
        </details>
        <a class="osm" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a>
        <label class="lang" :title="t('language')">
          <JIcon :icon="ICONS.language" :size="14" />
          <select v-model="locale" :aria-label="t('language')">
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
  font-family: system-ui, -apple-system, "PingFang SC", "Hiragino Sans", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
}
a {
  color: inherit;
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
  backdrop-filter: saturate(180%) blur(24px);
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
.detail-head {
  padding: 8px 16px 14px;
  border-bottom: 3px solid var(--bangumi-color);
}
.back {
  margin: 0 0 6px -6px;
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
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}
.points li:hover {
  background: var(--hover);
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
  margin: 14px 0;
  font-size: 22px;
}
.popular {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px 10px;
  margin: 20px 0 16px;
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
  transition: transform 0.2s;
}
.popular a:hover img {
  transform: translateY(-2px);
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
.credits-more {
  position: relative;
}
.credits-more summary {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  list-style: none;
  cursor: pointer;
}
.credits-more summary::-webkit-details-marker {
  display: none;
}
.credits-more summary:hover,
.credits-more[open] summary {
  color: var(--fg);
  background: var(--hover);
}
.credits-pop {
  position: absolute;
  left: -4px;
  bottom: calc(100% + 8px);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 160px;
  padding: 10px 12px;
  font-size: 12px;
  background: var(--bg-solid);
  border-radius: 10px;
  box-shadow: var(--shadow);
}
.osm {
  flex: 1;
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
  font: inherit;
  color: inherit;
  background: none;
  border: 0;
  outline: none;
  cursor: pointer;
  appearance: none;
}
</style>
