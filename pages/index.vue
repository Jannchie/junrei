<script setup lang="ts">
import { JIcon, provideIconDefaults } from "@jannchie/icons-vue";
import { fetch } from "void/client";
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import stats from "../data/stats.json";
import { formatDate, formatEpisode, formatTime, imageUrl } from "../src/format";
import { ICONS } from "../src/icons";
import "../src/theme.css";

provideIconDefaults({ size: 16 });

// maplibre 体积大且只在浏览器里用，单独分包，也不进服务端 bundle
const PilgrimMap = defineAsyncComponent(() => import("../src/components/PilgrimMap.vue"));

type Detail = Awaited<ReturnType<typeof fetchDetail>>;
type SearchResult = Awaited<ReturnType<typeof fetchSearch>>;
const fetchDetail = (id: number) => fetch("/v1/bangumi/:id", { params: { id: String(id) } });
const fetchSearch = (q: string) => fetch("/v1/search", { query: { q } });

const detail = shallowRef<Detail | null>(null);
const focusPointId = ref<string | null>(null);
const query = ref("");
const results = shallowRef<SearchResult | null>(null);
const searching = ref(false);

const selected = computed(() =>
  detail.value
    ? {
        bangumiId: detail.value.id,
        color: detail.value.color,
        points: detail.value.points.map((p) => ({ id: p.id, name: p.cn ?? p.name, lng: p.lng, lat: p.lat })),
      }
    : null,
);

async function select(bangumiId: number, pointId: string | null = null) {
  if (detail.value?.id !== bangumiId) {
    detail.value = await fetchDetail(bangumiId);
  }
  focusPointId.value = pointId;
  await nextTick(); // 新作品的列表要等渲染后才能滚动到选中项
  if (pointId) document.getElementById(`p-${pointId}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function clearSelection() {
  detail.value = null;
  focusPointId.value = null;
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

// 选中状态写进 URL，方便分享
watch([detail, focusPointId], () => {
  const url = new URL(location.href);
  url.search = "";
  if (detail.value) url.searchParams.set("b", String(detail.value.id));
  if (focusPointId.value) url.searchParams.set("p", focusPointId.value);
  history.replaceState(null, "", url);
});

// 面板浮在地图上：量出它挡住的区域，交给地图做 padding，并给地图控件留出位置
const app = ref<HTMLElement>();
const panel = ref<HTMLElement>();
const mapPadding = ref({ top: 0, right: 0, bottom: 0, left: 0 });
const panelObserver = new ResizeObserver(() => {
  const a = app.value!.getBoundingClientRect();
  const r = panel.value!.getBoundingClientRect();
  const beside = r.width < a.width * 0.6; // 桌面端在左侧，手机端在底部
  mapPadding.value = beside
    ? { top: 0, right: 0, bottom: 0, left: r.right - a.left }
    : { top: 0, right: 0, bottom: a.bottom - r.top, left: 0 };
});

onMounted(() => {
  panelObserver.observe(panel.value!);
  panelObserver.observe(app.value!);
  const params = new URLSearchParams(location.search);
  const b = Number(params.get("b"));
  if (b) void select(b, params.get("p"));
});
onBeforeUnmount(() => panelObserver.disconnect());
</script>

<template>
  <div ref="app" class="app" :style="{ '--panel-inset-bottom': `${mapPadding.bottom}px` }">
    <PilgrimMap
      :selected="selected"
      :focus-point-id="focusPointId"
      :padding="mapPadding"
      @pick="(b, p) => select(b, p)"
    />

    <aside ref="panel" class="panel">
      <label class="search">
        <JIcon :icon="ICONS.search" class="muted" />
        <input v-model="query" type="search" aria-label="搜索" autocomplete="off" />
        <button v-if="query" class="icon-btn" title="清除" aria-label="清除" @click="query = ''">
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
              <strong>{{ b.cn ?? b.title }}</strong>
              <small v-if="b.cn && b.title">{{ b.title }}</small>
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
              <strong>{{ p.cn ?? p.name }}</strong>
              <small>{{ p.bangumiName }}</small>
            </span>
          </button>
        </template>
      </section>

      <!-- 作品详情 -->
      <section v-else-if="detail" class="scroll">
        <div class="detail-head" :style="{ '--bangumi-color': detail.color ?? 'var(--accent)' }">
          <button class="icon-btn back" title="返回" aria-label="返回" @click="clearSelection">
            <JIcon :icon="ICONS.back" :size="18" />
          </button>
          <div class="title-row">
            <img v-if="detail.cover" :src="imageUrl(detail.cover)" class="cover" referrerpolicy="no-referrer" alt="" />
            <div class="title-main">
              <h2>{{ detail.cn ?? detail.title }}</h2>
              <p v-if="detail.cn && detail.title" class="sub">{{ detail.title }}</p>
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
            v-for="p in detail.points"
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
              <strong>{{ p.cn ?? p.name }}</strong>
              <small v-if="p.cn && p.name">{{ p.name }}</small>
              <span v-if="p.ep || p.s" class="meta">
                <span v-if="p.ep" class="stat"><JIcon :icon="ICONS.episode" :size="14" />{{ formatEpisode(p.ep) }}</span>
                <span v-if="p.s" class="stat"><JIcon :icon="ICONS.time" :size="14" />{{ formatTime(p.s) }}</span>
              </span>
              <p v-if="p.id === focusPointId && p.mark" class="mark">{{ p.mark }}</p>
            </div>
          </li>
        </ol>
      </section>

      <!-- 概览 -->
      <section v-else class="scroll overview">
        <h1><JIcon :icon="ICONS.logo" :size="22" weight="bold" />junrei</h1>
        <div class="stats">
          <span class="stat" title="作品"><JIcon :icon="ICONS.bangumi" />{{ stats.bangumi.toLocaleString() }}</span>
          <span class="stat" title="地标"><JIcon :icon="ICONS.point" />{{ stats.points.toLocaleString() }}</span>
          <span class="stat" title="数据更新"><JIcon :icon="ICONS.updated" />{{ formatDate(stats.modified) }}</span>
        </div>
      </section>

      <footer class="foot">
        <a href="https://www.anitabi.cn/" target="_blank" rel="noopener">Anitabi</a>
        <span>·</span>
        <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>
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
  background: var(--bg);
  color: var(--fg);
  font-family: system-ui, -apple-system, "PingFang SC", "Hiragino Sans", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
}
a {
  color: inherit;
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
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 8px 30px rgb(0 0 0 / 0.12);
  overflow: hidden;
}
@media (max-width: 640px) {
  .panel {
    top: auto;
    left: 0;
    right: 0;
    bottom: 0;
    width: auto;
    height: 46vh;
    border-radius: 14px 14px 0 0;
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
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  font-size: 15px;
  font-weight: 600;
}
.stats .stat :deep(svg) {
  color: var(--muted);
}
.foot {
  display: flex;
  gap: 6px;
  padding: 8px 16px;
  font-size: 11px;
  color: var(--muted);
  border-top: 1px solid var(--line);
}
.foot a {
  text-decoration: none;
}
.foot a:hover {
  text-decoration: underline;
}
</style>
