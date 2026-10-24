<script setup lang="ts">
import { JIcon, provideIconDefaults } from "@jannchie/icons-vue";
import { fetch } from "void/client";
import { kitText, type KeyHandler, type SheetSnap, type StyleContext } from "@mapette/core";
import { MapExplorer, MapFooter, MapPopover, useThemePref } from "@mapette/vue";
import type { PaddingOptions } from "maplibre-gl";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { formatDate, formatEpisode, formatTime, imageUrl } from "../format";
import { type Locale, LOCALE_NAMES, LOCALES, localePath, provideLocale, spotNames, stripLocale, workNames } from "../i18n";
import { ICONS } from "../icons";
import { recoverImages, retryImage } from "../image-retry";
import LogoMark from "./LogoMark.vue";
import PilgrimLayers from "./PilgrimLayers.vue";
import { createStyle, KEEP_SOURCES } from "../map-style";
import { bangumiInView, searchBangumi } from "../bangumi-index";
import { fetchDetail, seedDetails } from "../detail";
import { buildView, type Card, type Group, groupOf, missingDetails, needsAdultGate, type View, viewPath, type ViewPoint, visibleGroup } from "../series";
import { initAdult, setShowAdult, showAdult } from "../adult";
import type { CreditName, Credits } from "@schema";
import type { RecentPoint } from "../server/bangumi";
import "../theme.css";

/** 首页、系列页 /s/:id 与作品页 /b/:id 共用的整个应用；服务端渲染出面板内容（利于 SEO），地图只在浏览器里挂载 */
const props = defineProps<{
  /** 页面语言，由 URL 决定（简体中文无前缀，其余为 /zh-hant、/ja、/en） */
  lang: Locale;
  /** 系列页、作品页：所在系列与筛选的作品（null 为全部） */
  initialGroup?: Group | null;
  initialFilter?: number | null;
  /** 地标页 /b/:id?p=：展开的地标（服务端渲染时就展开，供搜索引擎读取） */
  initialPoint?: string | null;
  /** 概览里展示的热门系列 */
  popular?: Card[];
  /** 最近更新页 /recent：第一页地标 */
  initialRecent?: RecentPoint[];
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

// 外观偏好由 mapette 管（页脚的按钮与 T 快捷键共用一份）；存储键与 void.config.ts 的首屏脚本一致
const { cycle: cycleTheme } = useThemePref("junrei:theme");

// 图片失败重试见 src/image-retry.ts；模板里的 @error 直接用它
const onImageError = (e: Event) => retryImage(e.target as HTMLImageElement);

// 地图骨架（地图、侧栏 / 抽屉、留白、通用快捷键）来自 @mapette/vue 的 MapExplorer；maplibre 在挂载时才按需加载，不进服务端 bundle。
// 样式函数不随语言变：语言通过 locale 传给 MapExplorer，由它换地名字段
const mapStyle = (ctx: StyleContext) => createStyle(ctx);
const mounted = ref(false);

/** 苹果设备用 Apple 地图，其余用 Google 地图（服务端渲染时先按 Google 出链接，挂载后再判断） */
const appleMaps = ref(false);
const mapsUrl = (p: { lat: number; lng: number; name: string | null; cn: string | null }) =>
  appleMaps.value
    ? `https://maps.apple.com/?ll=${p.lat},${p.lng}&q=${encodeURIComponent(pickName(spotNames(p)) || `${p.lat},${p.lng}`)}`
    : `https://www.google.com/maps/search/?api=1&query=${p.lat}%2C${p.lng}`;

interface SearchResult {
  bangumis: Awaited<ReturnType<typeof searchBangumi>>;
  points: Awaited<ReturnType<typeof fetchSearch>>["points"];
}
const fetchSearch = (q: string, adult: boolean) => fetch("/v1/search", { query: adult ? { q, adult: "1" as const } : { q } });

// 面板里的作品以系列为单位：group 是当前系列，filter 是筛选的作品（null 为全部），detail 是据此组装出的显示内容
const group = shallowRef<Group | null>(props.initialGroup ?? null);
if (props.initialGroup) seedDetails(props.initialGroup.details);
const filter = ref<number | null>(props.initialFilter ?? null);
// 成人向（src/adult.ts）：没打开显示开关时，系列里只留一般向作品；直接打开成人向作品要先确认一次（revealed 记下确认过的系列）
const revealed = ref<number | null>(null);
const adultFor = (g: Group) => showAdult.value || revealed.value === g.key;
const gated = computed(() => !!group.value && !adultFor(group.value) && needsAdultGate(group.value, filter.value));
const detail = computed<View | null>(() =>
  group.value ? buildView(visibleGroup(group.value, adultFor(group.value), filter.value), filter.value) : null,
);
const focusPointId = ref<string | null>(props.initialPoint ?? null);
/** 当前地标：面板里单独一页（地图上的弹出卡片也用它）；focusedIndex 是它在列表里的位置 */
const focusedPoint = computed(() => detail.value?.points.find((p) => p.id === focusPointId.value) ?? null);
const focusedIndex = computed(() => (focusPointId.value ? orderedPoints.value.findIndex((p) => p.id === focusPointId.value) : -1));
const query = ref("");
const results = shallowRef<SearchResult | null>(null);
const searching = ref(false);

const selected = computed(() =>
  detail.value && !gated.value
    ? {
        bangumiId: detail.value.id,
        points: detail.value.points.map((p) => ({ id: p.id, b: p.bangumiId, name: pickName(spotNames(p)), lng: p.lng, lat: p.lat })),
      }
    : // 最近更新：地图上高亮列表里的地标
      !detail.value && recent.value?.length
      ? { bangumiId: 0, color: null, points: recent.value.map((p) => ({ id: p.id, b: p.bangumiId, name: pickName(spotNames(p)), lng: p.lng, lat: p.lat })) }
      : null,
);

// 地标列表分批渲染：首屏（含服务端渲染）只出前一批，滚到底再追加；上千个地标的作品也不卡
const PAGE = 60;
const visibleCount = ref(PAGE);
// 放大到局部时，列表只列出视野内的地标（选中的那个总算在内），视野外的折叠在最后，点开才列出
const outOpen = ref(false);
const split = computed(() => {
  const points = detail.value?.points ?? [];
  const b = viewBounds.value;
  const inside: typeof points = [];
  const outside: typeof points = [];
  for (const p of points) (!b || p.id === focusPointId.value || inBounds(p, b) ? inside : outside).push(p);
  return { inside, outside };
});
const orderedPoints = computed(() => [...split.value.inside, ...split.value.outside]);
const listedCount = computed(() => (outOpen.value ? orderedPoints.value.length : split.value.inside.length));
const visiblePoints = computed(() => orderedPoints.value.slice(0, Math.min(visibleCount.value, listedCount.value)));
// 地标页：展开的地标要在首批渲染出来的列表里
const initialIndex = props.initialPoint && detail.value ? detail.value.points.findIndex((p) => p.id === props.initialPoint) : -1;
if (initialIndex >= PAGE) visibleCount.value = initialIndex + PAGE;
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

// ---- 最近更新：全站按更新时间倒序的地标，按日期分组；从这里打开的作品，返回时回到这里 ----
const RECENT_PAGE = 100; // 同 src/server/bangumi.ts
const recent = shallowRef<RecentPoint[] | null>(props.initialRecent ?? null);
const recentDone = ref((props.initialRecent?.length ?? 0) < RECENT_PAGE);
let recentSeq = 0;
async function loadRecent(reset: boolean) {
  const id = ++recentSeq;
  const offset = String(reset ? 0 : (recent.value?.length ?? 0));
  const { points } = await fetch("/v1/recent", { query: showAdult.value ? { offset, adult: "1" as const } : { offset } });
  if (id !== recentSeq || !recent.value) return;
  recent.value = reset ? points : [...recent.value, ...points];
  recentDone.value = points.length < RECENT_PAGE;
}
function openRecent() {
  clearSelection();
  query.value = "";
  if (recent.value) return;
  recent.value = [];
  recentDone.value = false;
  void loadRecent(true);
}
function closeRecent() {
  recent.value = null;
  recentSeq++;
}
const recentDays = computed(() => {
  const days: { date: string; points: RecentPoint[] }[] = [];
  for (const p of recent.value ?? []) {
    const date = formatDate(p.updated);
    if (days.at(-1)?.date !== date) days.push({ date, points: [] });
    days.at(-1)!.points.push(p);
  }
  return days;
});
const recentSentinel = ref<HTMLElement>();
let recentObserver: IntersectionObserver | undefined;
watch(recentSentinel, (el) => {
  recentObserver?.disconnect();
  if (!el) return;
  recentObserver = new IntersectionObserver(([e]) => {
    if (e.isIntersecting) void loadRecent(false);
  }, { rootMargin: "400px" });
  recentObserver.observe(el);
});

// ---- 主要人员与角色（Bangumi）：人名按当前语言取，没有就用原名；角色先列 CAST_SHOWN 个，可以展开 ----
const ROLE_LABEL = {
  original: "roleOriginal", director: "roleDirector", composition: "roleComposition", studio: "roleStudio",
  originalDesign: "roleOriginalDesign", characterDesign: "roleCharacterDesign", music: "roleMusic",
} as const satisfies Record<Credits["staff"][number]["r"], string>;
const CAST_SHOWN = 6;
const castOpen = ref(false);
const creditName = (e: CreditName) =>
  (locale.value === "zh-Hans" ? e.cn : locale.value === "zh-Hant" ? (e.tw ?? e.cn) : locale.value === "en" ? e.en : null) ?? e.n ?? "";
const sep = computed(() => (locale.value === "en" ? ", " : "、"));

// 作品标题区滚出可视范围时，列表顶部浮出作品名
const titleRow = ref<HTMLElement>();
const headHidden = ref(false);
function onDetailScroll(e: Event) {
  const row = titleRow.value;
  headHidden.value = !!row && row.getBoundingClientRect().bottom < (e.target as HTMLElement).getBoundingClientRect().top;
}

/** 打开某部作品所在的系列：filterId 为 null 显示全部，否则筛选到那一部；可同时聚焦一个地标 */
async function open(anyId: number, filterId: number | null, pointId: string | null = null) {
  let g = group.value?.works.some((w) => w.id === anyId) ? group.value : groupOf(await fetchDetail(anyId));
  const need = (filterId != null ? [filterId] : missingDetails(visibleGroup(g, adultFor(g), null))).filter((id) => !g.details.some((d) => d.id === id));
  if (need.length) g = { ...g, details: [...g.details, ...(await Promise.all(need.map(fetchDetail)))] };
  if (g !== group.value || filterId !== filter.value) {
    group.value = g;
    filter.value = filterId;
    visibleCount.value = PAGE;
    outOpen.value = false;
    castOpen.value = false;
    headHidden.value = false;
  }
  await focus(pointId);
}

/** 选中一个地标（地图、搜索结果、列表、快捷键）：在当前显示范围里就直接聚焦，否则打开它所在的整个系列 */
async function select(bangumiId: number, pointId: string | null = null) {
  const shown = group.value?.works.some((w) => w.id === bangumiId) && (filter.value == null || filter.value === bangumiId);
  if (shown && detail.value) return focus(pointId);
  return open(bangumiId, null, pointId);
}

async function focus(pointId: string | null) {
  if (!detail.value) return;
  focusPointId.value = pointId; // 先设好：选中的地标总排在视野内的那一组里
  const index = pointId ? orderedPoints.value.findIndex((p) => p.id === pointId) : -1;
  if (index >= visibleCount.value) visibleCount.value = index + PAGE;
  sheet.value = "half"; // 选中后回到半屏，地图上要看得到它
  await nextTick(); // 新作品的列表要等渲染后才能滚动到选中项
  // 切换地标时列表直接跳到选中项，不做滚动动画：连按 J / K 时动画跟不上，也拖慢视线
  if (pointId) document.getElementById(`p-${pointId}`)?.scrollIntoView({ block: "nearest", behavior: "instant" });
}

function clearSelection() {
  group.value = null;
  filter.value = null;
  focusPointId.value = null;
  headHidden.value = false;
}

// ---- 撤销 / 重做：面板显示的内容（作品、筛选、地标、最近更新）每变一次记一步。
// Ctrl+Z 撤销、Ctrl+Y 或 Ctrl+Shift+Z 重做；返回（Esc、返回按钮）之后另有一个「撤销」提示，误按了能马上回去 ----
type Snapshot = { key: number | null; filter: number | null; point: string | null; recent: boolean };
const HISTORY = 50;
const snapshot = (): Snapshot => ({ key: group.value?.key ?? null, filter: filter.value, point: focusPointId.value, recent: !!recent.value });
const sameView = (a: Snapshot, b: Snapshot) => a.key === b.key && a.filter === b.filter && a.point === b.point && a.recent === b.recent;
const undoStack: Snapshot[] = [];
const redoStack: Snapshot[] = [];
let current = snapshot();
let restoring = false; // 恢复中途的状态（先打开最近更新、再加载作品…）不记成新的一步
watch(snapshot, (next) => {
  if (sameView(next, current)) return;
  if (!restoring) {
    undoStack.push(current);
    if (undoStack.length > HISTORY) undoStack.shift();
    redoStack.length = 0;
  }
  current = next;
});
async function restore(s: Snapshot) {
  restoring = true;
  try {
    query.value = "";
    if (s.recent && !recent.value) openRecent();
    else if (!s.recent && recent.value) closeRecent();
    if (s.key != null) await open(s.key, s.filter, s.point);
    else if (group.value) clearSelection();
    await nextTick();
  } finally {
    restoring = false;
    current = snapshot();
  }
}
function undo() {
  const prev = undoStack.pop();
  if (!prev) return false;
  redoStack.push(snapshot());
  undoHint.value = false;
  void restore(prev);
}
function redo() {
  const next = redoStack.pop();
  if (!next) return false;
  undoStack.push(snapshot());
  void restore(next);
}
// 返回之后的提示条：几秒后自动消失
const undoHint = ref(false);
let undoTimer: ReturnType<typeof setTimeout> | undefined;
function wentBack() {
  undoHint.value = true;
  clearTimeout(undoTimer);
  undoTimer = setTimeout(() => (undoHint.value = false), 6000);
}
/** 返回按钮与 Esc：退一层，并提示可以撤销 */
function goBack() {
  if (focusPointId.value) focusPointId.value = null;
  else if (detail.value) clearSelection();
  else if (recent.value) closeRecent();
  else return false;
  wentBack();
}

// ---- 手机端底部抽屉：peek 只露出搜索框，half 半屏，full 接近全屏 ----
// 像地图 App 一样，平时停在半屏：只有输入搜索时展开到全屏，输入结束、选中结果、碰地图都回到半屏
// 拖动、甩动与吸附由 mapette 的 MapSheet 处理，这里只决定什么时候切到哪一档
const sheet = ref<SheetSnap>("half");
/** 碰到地图：抽屉让开，回到半屏 */
function onMapPointer() {
  if (sheet.value === "full") sheet.value = "half";
  if (document.activeElement === searchInput.value) searchInput.value!.blur();
}

// 搜索：输入停顿 250ms 后请求，同时写进地址栏（debouncedQuery）
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;
const debouncedQuery = ref("");
watch(query, (q) => {
  clearTimeout(timer);
  if (!q.trim()) {
    results.value = null;
    debouncedQuery.value = "";
    return;
  }
  timer = setTimeout(async () => {
    debouncedQuery.value = q.trim();
    const id = ++seq;
    searching.value = true;
    try {
      // 作品在浏览器里模糊匹配（全语种、即时）；地标五万多条，交给服务端的全文索引
      const [local, { bangumis: remote, points }] = await Promise.all([searchBangumi(q, showAdult.value), fetchSearch(q.trim(), showAdult.value)]);
      // 本地索引只有带地标的作品（模糊匹配更好）；服务端还能搜到没有地标的作品，接在后面
      const seen = new Set(local.map((b) => b.id));
      const bangumis = [...local, ...remote.filter((b) => !seen.has(b.id))].slice(0, 30);
      if (id === seq) results.value = { bangumis, points };
    } finally {
      if (id === seq) searching.value = false;
    }
  }, 250);
});

async function pickResult(bangumiId: number, pointId: string | null = null) {
  query.value = ""; // 清空搜索词时 watch 会一并清掉结果
  await select(bangumiId, pointId);
}
/** 搜索结果、首页的系列卡片：打开整个系列 */
async function pickCard(id: number) {
  query.value = "";
  await open(id, null);
}
const workName = (id: number) => {
  const w = detail.value?.series.find((s) => s.id === id);
  return w ? pickName(workNames(w)) : "";
};
/** 报告地标问题：预填好作品、地标、坐标与来源的 GitHub issue */
function reportUrl(p: ViewPoint) {
  const work = detail.value?.series.find((w) => w.id === p.bangumiId);
  const title = `[地标] ${pickName(spotNames(p))}（${work ? pickName(workNames(work)) : p.bangumiId}）`;
  const body = [
    "<!-- 请说明问题：位置不对 / 不是这部作品的场景 / 地点已经消失或变化 / 其他 -->",
    "",
    "",
    "---",
    `- 地标：https://junrei.jannchie.com${localePath(locale.value, `/b/${p.bangumiId}`)}?p=${p.id}`,
    `- id：\`${p.bangumiId}:${p.id}\``,
    `- 坐标：${p.lat}, ${p.lng}`,
    ...(p.sourceUrl ? [`- 来源：${p.sourceUrl}`] : []),
  ].join("\n");
  return `https://github.com/Jannchie/junrei/issues/new?${new URLSearchParams({ title, body, labels: "spot-report" })}`;
}
const cardPath = (c: Card) => localePath(locale.value, c.series ? `/s/${c.id}` : `/b/${c.id}`);

// 状态写进 URL，链接即可分享、收藏：路径是作品（/b/:id 由服务端渲染，可被收录），?p 是地标，
// ?q 是搜索词（也是 OpenSearch 的入口），#map 是地图视野（由 maplibre 维护，这里原样保留）
watch([detail, focusPointId, debouncedQuery, () => !!recent.value], () => {
  const d = detail.value;
  const path = d ? viewPath(d) : recent.value ? "/recent" : "/";
  const url = new URL(localePath(locale.value, path), location.origin);
  if (focusPointId.value) url.searchParams.set("p", focusPointId.value);
  if (debouncedQuery.value) url.searchParams.set("q", debouncedQuery.value);
  url.hash = location.hash;
  history.replaceState(null, "", url);
  const spot = detail.value?.points.find((p) => p.id === focusPointId.value);
  document.title = detail.value
    ? `${spot ? `${pickName(spotNames(spot))} · ` : ""}${pickName(workNames(detail.value))} · ${t("brand")}`
    : recent.value ? `${t("recent")} · ${t("brand")}` : t("brand");
});

// 面板浮在地图上：MapExplorer 量出它挡住的区域交给地图；这里也记一份，撤销提示要避开抽屉
const explorer = ref<InstanceType<typeof MapExplorer>>();
const panel = computed(() => explorer.value?.panel ?? null);
const mapPadding = ref<PaddingOptions>({ top: 0, right: 0, bottom: 0, left: 0 });
// 来源浮层：支持 CSS 锚点定位时由样式摆放；否则打开时按按钮位置算一次
type Bounds = { west: number; south: number; east: number; north: number };
const viewBounds = shallowRef<Bounds | null>(null);
const inBounds = (p: { lat: number; lng: number }, b: Bounds) =>
  p.lat >= b.south && p.lat <= b.north && (b.west <= b.east ? p.lng >= b.west && p.lng <= b.east : p.lng >= b.west || p.lng <= b.east);
const inView = shallowRef<Awaited<ReturnType<typeof bangumiInView>> | null>(null);
let viewSeq = 0;
let lastBounds: Bounds | null = null;
async function onView(bounds: Bounds) {
  lastBounds = bounds;
  viewBounds.value = bounds;
  const id = ++viewSeq;
  const list = await bangumiInView(bounds, showAdult.value);
  if (id === viewSeq) inView.value = list;
}
/** 成人向开关变化：视口列表重算；系列「全部」补加载刚显示出来的作品 */
watch(showAdult, () => {
  if (lastBounds) void onView(lastBounds);
  if (group.value) void open(group.value.key, filter.value, focusPointId.value);
  if (recent.value) void loadRecent(true);
});
/** 确认后显示这一个系列里的成人向作品（不改变全局开关） */
function revealAdult() {
  if (!group.value) return;
  revealed.value = group.value.key;
  void open(group.value.key, filter.value, focusPointId.value);
}
const overviewList = computed(() => inView.value ?? props.popular?.map((b) => ({ ...b, inView: b.pointCount })) ?? []);


// ---- 手机键盘：布局不随键盘缩放（见 void.config.ts 的 viewport），抽屉留出被键盘挡住的高度，列表能滚到键盘上方 ----
const keyboard = ref(0);
function onVisualViewport() {
  const vv = visualViewport!;
  keyboard.value = Math.max(0, Math.round(innerHeight - vv.height - vv.offsetTop));
  // iOS 聚焦输入框时会把整页往上推；页面本身不滚动，推上去的部分直接拉回
  if (keyboard.value && scrollY) scrollTo(0, 0);
}
/** 用键盘（/ 快捷键、Tab）聚焦搜索框时展开抽屉 */
function expandForTyping() {
  if (sheet.value !== "full") sheet.value = "full";
}
/**
 * 手机上点搜索框：抬起手指时自己完成「展开 → 聚焦」，不交给浏览器。
 * 浏览器会在抬起后按原来的坐标合成点击、聚焦并把输入框滚进视野；抽屉一展开，原坐标上已经是别的东西
 * （点到作品卡片就打开了作品），滚动也是按展开前的位置算的，结果看到的是抽屉下半截。
 * 所以取消合成点击，先不带动画把抽屉直接展开到全屏，再聚焦，并且不让浏览器滚动
 */
function onSearchTouch(e: TouchEvent) {
  if ((e.target as Element).closest("button") || !e.cancelable) return; // 返回按钮照常；滑动中的不管
  e.preventDefault();
  const el = panel.value;
  if (!el) return;
  el.style.transition = "none";
  el.style.height = "calc(100dvh - 48px - env(safe-area-inset-top))"; // 同 .mapette-sheet-full：同步撑开，聚焦时布局已经是展开后的
  sheet.value = "full";
  searchInput.value!.focus({ preventScroll: true });
  void nextTick(() => {
    el.style.height = ""; // sheet-full 的样式已经生效，高度相同，去掉临时值不会跳
    el.style.transition = "";
  });
}
/** 输入结束（键盘收起）就回到半屏。手指还按着时先不动：点的可能是搜索结果，抽屉一变，点击会落空 */
let pressing = false;
function onSearchBlur() {
  const collapse = () => {
    if (document.activeElement !== searchInput.value && sheet.value === "full") sheet.value = "half";
  };
  if (!pressing) return collapse();
  addEventListener("pointerup", () => setTimeout(collapse), { once: true });
}

// ---- 键盘快捷键（按 ? 查看）----
const searchInput = ref<HTMLInputElement>();
// 作品的 ⋯ 菜单：打开时贴在按钮下方、右边对齐（不依赖 CSS 锚点定位）
const linksBtn = ref<HTMLElement>();
const linksPop = ref<HTMLElement>();
function onLinksToggle(e: Event) {
  if ((e as ToggleEvent).newState !== "open") return;
  const r = linksBtn.value!.getBoundingClientRect();
  Object.assign(linksPop.value!.style, { top: `${r.bottom + 4}px`, left: "auto", right: `${innerWidth - r.right}px` });
}

// 页脚（mapette 的 MapFooter）：快捷键说明的开关也在它那里
const footer = ref<InstanceType<typeof MapFooter>>();

function focusSearch() {
  searchInput.value?.focus();
  searchInput.value?.select();
}
/** Esc 逐层退出：清空搜索 → 离开输入框 → 取消选中地标 → 返回概览 */
function escape(e: KeyboardEvent) {
  if (footer.value?.shortcutsOpen()) return false; // popover 自己会关
  if (query.value) query.value = "";
  else if (e.target === searchInput.value) searchInput.value!.blur();
  else return goBack();
}
/** 在作品的地标之间移动；没有选中地标时从第一个开始 */
function stepPoint(delta: number) {
  const points = detail.value?.points;
  if (!points?.length) return false;
  const i = points.findIndex((p) => p.id === focusPointId.value);
  const next = i < 0 ? 0 : Math.min(points.length - 1, Math.max(0, i + delta));
  void select(points[next].bangumiId, points[next].id);
}
/** 搜索结果：↑↓ 在输入框与结果之间移动焦点，回车即点击 */
function stepRow(e: KeyboardEvent, delta: number) {
  const list = [...(panel.value?.querySelectorAll<HTMLElement>(".row") ?? [])];
  if (!list.length) return false;
  const i = list.indexOf(e.target as HTMLElement);
  if (i + delta < 0) searchInput.value?.focus();
  else list[Math.min(list.length - 1, i + delta)].focus();
}
const arrow = (delta: number) => (e: KeyboardEvent) => {
  if ((e.target as HTMLElement).closest?.(".maplibregl-map")) return false; // 地图有焦点时方向键平移地图
  return query.value.trim() ? stepRow(e, delta) : stepPoint(delta);
};

// 缩放（+ −）与定位（L）由 MapExplorer 内置；这里是巡礼自己的快捷键，同名的覆盖内置的（Esc 逐层退出）
const shortcuts: Record<string, KeyHandler> = {
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
      window.open(mapsUrl(p), "_blank", "noopener");
    },
    t: () => cycleTheme(),
    "?": () => footer.value?.toggleShortcuts(),
    // 输入框里交还浏览器，撤销的是输入的文字
    "mod+z": (e) => ((e.target as HTMLElement).closest?.("input, textarea") ? false : e.shiftKey ? redo() : undo()),
    "mod+y": (e) => ((e.target as HTMLElement).closest?.("input, textarea") ? false : redo()),
};

/** 地标数据的来源（地图底图的几项由 MapFooter 自带） */
const SOURCES = [
  { label: "Anitabi", href: "https://www.anitabi.cn/" },
  { label: "CC BY-NC-SA 4.0", href: "https://creativecommons.org/licenses/by-nc-sa/4.0/" },
  { label: "Bangumi", href: "https://bgm.tv/" },
];

const SHORTCUTS = computed(() => [
  { keys: ["/", "Ctrl K"], label: t("kbSearch") },
  { keys: ["Esc"], label: t("back") },
  { keys: ["Ctrl Z"], label: t("undo") },
  { keys: ["Ctrl Y", "Ctrl ⇧ Z"], label: t("redo") },
  { keys: ["J", "K", "↓", "↑"], label: t("kbPoints") },
  { keys: ["O"], label: t("openInMaps") },
  { keys: ["+", "−"], label: `${t("zoomIn")} / ${t("zoomOut")}` },
  { keys: ["L"], label: t("locate") },
  { keys: ["N"], label: kitText(locale.value).resetNorth },
  { keys: ["T"], label: t("kbTheme") },
  { keys: ["?"], label: t("shortcuts") },
]);

onMounted(() => {
  addEventListener("pointerdown", (e) => {
    pressing = true;
    if ((e.target as Element).closest?.(".mapette-map")) onMapPointer();
  }, { capture: true });
  for (const type of ["pointerup", "pointercancel"]) addEventListener(type, () => (pressing = false), { capture: true });
  appleMaps.value = /iPhone|iPad|Macintosh/.test(navigator.userAgent);
  recoverImages();

  visualViewport?.addEventListener("resize", onVisualViewport);
  visualViewport?.addEventListener("scroll", onVisualViewport);
  mounted.value = true;
  initAdult();
  // ?p= 定位地标（作品页）；旧链接 /?b=…&p=…
  const params = new URLSearchParams(location.search);
  const b = Number(params.get("b"));
  if (b) void select(b, params.get("p"));
  else if (detail.value && params.get("p")) void focus(params.get("p"));
  const q = params.get("q");
  if (q) {
    query.value = q;
    sheet.value = "full";
  }
  if (import.meta.env.PROD && "serviceWorker" in navigator) void navigator.serviceWorker.register("/sw.js");
});
onBeforeUnmount(() => {
  moreObserver?.disconnect();
  recentObserver?.disconnect();
  visualViewport?.removeEventListener("resize", onVisualViewport);
  visualViewport?.removeEventListener("scroll", onVisualViewport);
});
</script>

<template>
  <div class="app" :style="{ '--panel-inset-bottom': `${mapPadding.bottom}px`, '--keyboard': `${keyboard}px` }">
    <MapExplorer
      ref="explorer"
      v-model:snap="sheet"
      :map-style="mapStyle"
      :locale="locale"
      :keep-sources="KEEP_SOURCES"
      :center="[137.5, 36.2]"
      :zoom="4.6"
      :labels="{ locate: t('locate'), zoomIn: t('zoomIn'), zoomOut: t('zoomOut') }"
      :shortcuts="shortcuts"
      @padding="mapPadding = $event"
    >
      <template #map>
        <PilgrimLayers :selected="selected" :focus-point-id="focusPointId" @pick="(b, p) => select(b, p || null)" @view="onView" />
        <!-- 当前地标的弹出卡片：截图、地标名与集数；关掉就是退回作品（同 Esc） -->
        <MapPopover :lng-lat="focusedPoint ? [focusedPoint.lng, focusedPoint.lat] : null" :close-label="t('back')" @close="goBack()">
          <div v-if="focusedPoint" class="point-pop">
            <img v-if="focusedPoint.image" :src="imageUrl(focusedPoint.image)" alt="" referrerpolicy="no-referrer" @error="onImageError" />
            <div class="point-pop-text">
              <strong v-auto-lang>{{ pickName(spotNames(focusedPoint)) }}</strong>
              <span v-if="focusedPoint.ep" class="muted stat">{{ formatEpisode(focusedPoint.ep) }}</span>
            </div>
          </div>
        </MapPopover>
      </template>
      <template #header>
      <label class="search" @touchend="onSearchTouch">
        <button
          v-if="(detail || recent) && !query.trim()"
          type="button"
          class="icon-btn lead"
          :title="`${t('back')} (Esc)`"
          :aria-label="t('back')"
          @click.prevent="goBack()"
        >
          <JIcon :icon="ICONS.back" :size="18" />
        </button>
        <JIcon v-else :icon="ICONS.search" class="muted" />
        <input ref="searchInput" v-model="query" type="search" :placeholder="t('search')" :aria-label="t('search')" autocomplete="off" @focus="expandForTyping" @blur="onSearchBlur" />
        <button v-if="query" class="icon-btn" :title="t('clear')" :aria-label="t('clear')" @click="query = ''">
          <JIcon :icon="ICONS.clear" />
        </button>
      </label>
      </template>

      <!-- 搜索结果 -->
      <section v-if="query.trim()" class="scroll">
        <div v-if="searching && !results" class="empty"><JIcon :icon="ICONS.loading" :size="28" /></div>
        <template v-else-if="results">
          <div v-if="!results.bangumis.length && !results.points.length" class="empty">
            <JIcon :icon="ICONS.noResult" :size="28" />
          </div>
          <button v-for="b in results.bangumis" :key="b.id" class="row" :class="{ dim: !b.pointCount }" @click="pickCard(b.id)">
            <img @error="onImageError" v-if="b.cover" :src="imageUrl(b.cover)" class="cover-sm" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="cover-sm placeholder"><JIcon :icon="ICONS.bangumi" /></span>
            <span class="row-main">
              <strong v-auto-lang>{{ pickName(workNames(b)) }}</strong>
              <small v-auto-lang v-if="subName(workNames(b))">{{ subName(workNames(b)) }}</small>
            </span>
            <span class="row-stats">
              <span v-if="b.series" class="stat" :title="t('series')"><JIcon :icon="ICONS.series" :size="14" /><span class="tx">{{ b.works }}</span></span>
              <span v-if="b.pointCount" class="stat"><JIcon :icon="ICONS.point" :size="14" /><span class="tx">{{ b.pointCount }}</span></span>
            </span>
          </button>
          <hr v-if="results.bangumis.length && results.points.length" />
          <button
            v-for="p in results.points"
            :key="`${p.bangumiId}:${p.id}`"
            class="row"
            @click="pickResult(p.bangumiId, p.id)"
          >
            <img @error="onImageError" v-if="p.image" :src="imageUrl(p.image)" class="thumb-sm" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="thumb-sm placeholder"><JIcon :icon="ICONS.point" /></span>
            <span class="row-main">
              <strong v-auto-lang>{{ pickName(spotNames(p)) }}</strong>
              <small v-auto-lang>{{ pickName({ cn: p.bangumiCn, original: p.bangumiTitle, en: p.bangumiEn, i18n: p.bangumiI18n }) }}</small>
            </span>
          </button>
        </template>
      </section>

      <!-- 作品详情 -->
      <!-- 作品：标题、系列与地标列表。选中地标时隐藏而不销毁（地标单独一页，见下方），返回时停在原来的滚动位置 -->
      <section v-else-if="detail" v-show="!focusedPoint || gated" :key="detail.id" class="scroll" @scroll.passive="onDetailScroll">
        <!-- 标题区滚出去后，作品名浮在列表顶部；点一下回到顶部 -->
        <div class="detail-bar" :class="{ shown: headHidden }" :aria-hidden="!headHidden">
          <button v-auto-lang type="button" class="bar-title" tabindex="-1" @click="($event.currentTarget as HTMLElement).closest('.scroll')!.scrollTo({ top: 0, behavior: 'smooth' })">
            {{ pickName(workNames(detail)) }}
          </button>
        </div>
        <!-- 成人向作品：确认之前不显示封面、标题与地标 -->
        <div v-if="gated" class="adult-gate">
          <JIcon :icon="ICONS.adult" :size="28" />
          <p>{{ t("adultNotice") }}</p>
          <div class="adult-actions">
            <button type="button" class="primary" @click="revealAdult">{{ t("adultContinue") }}</button>
            <button type="button" @click="clearSelection">{{ t("back") }}</button>
          </div>
        </div>
        <template v-else>
        <div class="detail-head">
          <div ref="titleRow" class="title-row">
            <img @error="onImageError" v-if="detail.cover" :src="imageUrl(detail.cover)" class="cover" referrerpolicy="no-referrer" alt="" />
            <div class="title-main">
              <h2 v-auto-lang>{{ pickName(workNames(detail)) }}</h2>
              <p v-auto-lang v-if="subName(workNames(detail))" class="sub">
                {{ subName(workNames(detail)) }}
              </p>
              <p class="meta">
                <span v-if="detail.cat" class="stat"><JIcon :icon="ICONS.bangumi" :size="14" /><span class="tx">{{ categoryOf(detail.cat) }}</span></span>
                <span v-if="detail.city" class="stat"><JIcon :icon="ICONS.city" :size="14" /><span v-auto-lang class="tx">{{ cityOf(detail) }}</span></span>
                <span class="stat"><JIcon :icon="ICONS.point" :size="14" /><span class="tx">{{ detail.pointCount }}</span></span>
              </p>
            </div>
            <!-- 作品的外部链接与 KML 导出：次要操作，收在标题右侧的 ⋯ 菜单里（原生 popover，点外部或 Esc 关闭） -->
            <button ref="linksBtn" type="button" class="icon-btn more-btn" popovertarget="work-links" :title="t('moreLinks')" :aria-label="t('moreLinks')">
              <JIcon :icon="ICONS.more" :size="18" />
            </button>
            <div id="work-links" ref="linksPop" popover class="links-pop" @toggle="onLinksToggle">
              <a :href="`https://bgm.tv/subject/${detail.linkId}`" target="_blank" rel="noopener"><JIcon :icon="ICONS.external" :size="14" />Bangumi</a>
              <a :href="`https://www.anitabi.cn/map?bangumiId=${detail.linkId}`" target="_blank" rel="noopener"><JIcon :icon="ICONS.external" :size="14" />Anitabi</a>
              <a :href="`/v1/bangumi/${detail.linkId}/kml?lang=${locale}`" :title="t('exportKml')" download><JIcon :icon="ICONS.download" :size="14" />{{ t("kmlShort") }}</a>
            </div>
          </div>
          <!-- 主要人员与角色（Bangumi）：服务端渲染，按人名、角色名搜索的人也能从搜索引擎找到 -->
          <dl v-if="detail.credits?.staff.length || detail.credits?.cast.length" class="credits">
            <template v-for="s in detail.credits.staff" :key="s.r">
              <dt>{{ t(ROLE_LABEL[s.r]) }}</dt>
              <dd v-auto-lang>{{ s.p.map(creditName).join(sep) }}</dd>
            </template>
            <template v-if="detail.credits.cast.length">
              <dt>{{ t("cast") }}</dt>
              <dd>
                <ul class="cast">
                  <li v-for="c in castOpen ? detail.credits.cast : detail.credits.cast.slice(0, CAST_SHOWN)" :key="c.n">
                    <span v-auto-lang>{{ creditName(c) }}</span><small v-if="c.cv?.length" v-auto-lang>CV {{ c.cv.map(creditName).join(sep) }}</small>
                  </li>
                  <li v-if="!castOpen && detail.credits.cast.length > CAST_SHOWN">
                    <button type="button" class="more-cast" @click="castOpen = true">{{ t("showAll") }} · {{ detail.credits.cast.length }}</button>
                  </li>
                </ul>
              </dd>
            </template>
          </dl>
        </div>
        <!-- 同系列作品（TV 各季、剧场版、OVA…）：横向一排，当前作品高亮，没有地标的淡一些 -->
        <nav v-if="detail.series.length > 1" class="series" :aria-label="t('series')">
          <a
            :href="localePath(locale, `/s/${detail.key}`)"
            :class="{ current: detail.filter == null }"
            :aria-current="detail.filter == null ? 'page' : undefined"
            @click.prevent="open(detail.key, null)"
          >
            <span class="series-covers" aria-hidden="true">
              <img v-for="s in detail.series.filter((w) => w.cover).slice(0, 3)" :key="s.id" @error="onImageError" :src="imageUrl(s.cover!)" loading="lazy" referrerpolicy="no-referrer" alt="" />
            </span>
            <span class="series-text">
            <span class="series-name">{{ t("allWorks") }}</span>
            <small class="stat">
              <span class="tx">{{ detail.series.length }}</span>
              <JIcon :icon="ICONS.point" :size="11" /><span class="tx">{{ detail.series.reduce((n, s) => n + s.pointCount, 0) }}</span>
            </small>
            </span>
          </a>
          <a
            v-for="s in detail.series"
            :key="s.id"
            :href="localePath(locale, `/b/${s.id}`)"
            :class="{ current: s.id === detail.filter, dim: !s.pointCount }"
            :aria-current="s.id === detail.filter ? 'page' : undefined"
            @click.prevent="open(detail.key, s.id)"
          >
            <img v-if="s.cover" @error="onImageError" :src="imageUrl(s.cover)" class="series-cover" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="series-cover" aria-hidden="true" />
            <span class="series-text">
            <span v-auto-lang class="series-name">{{ pickName(workNames(s)) }}</span>
            <small class="stat">
              <span class="tx">{{ s.airDate?.slice(0, 4) ?? categoryOf(s.cat) }}</span>
              <template v-if="s.pointCount"><JIcon :icon="ICONS.point" :size="11" /><span class="tx">{{ s.pointCount }}</span></template>
            </small>
            </span>
          </a>
        </nav>
        <p v-if="!detail.points.length" class="empty no-spots">{{ t("noSpots") }}</p>
        <ol class="points">
          <template v-for="(p, i) in visiblePoints" :key="p.id">
          <li v-if="outOpen && i === split.inside.length" class="fold" @click="outOpen = false">
            <span class="stat"><JIcon :icon="ICONS.point" :size="12" /><span class="tx">{{ t("outOfView") }} · {{ split.outside.length }}</span></span>
          </li>
          <li
            :id="`p-${p.id}`"
            :class="{ active: p.id === focusPointId }"
            @click="select(p.bangumiId, p.id)"
          >
            <figure v-if="p.image">
              <img @error="onImageError"
                :src="imageUrl(p.image, 'h160')"
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
              <!-- 地标名是到地标页的真实链接（搜索引擎据此找到每个地标）；点击仍交给整行处理 -->
              <a :href="`${localePath(locale, `/b/${p.bangumiId}`)}?p=${p.id}`" class="spot-link" @click.prevent><strong v-auto-lang>{{ pickName(spotNames(p)) }}</strong></a>
              <span v-if="detail.filter == null && detail.series.length > 1" v-auto-lang class="from">{{ workName(p.bangumiId) }}</span>
              <span v-if="p.ep || p.s || p.updated" class="meta">
                <span v-if="p.ep" class="stat"><JIcon :icon="ICONS.episode" :size="14" /><span class="tx">{{ formatEpisode(p.ep) }}</span></span>
                <span v-if="p.s" class="stat"><JIcon :icon="ICONS.time" :size="14" /><span class="tx">{{ formatTime(p.s) }}</span></span>
                <span v-if="p.updated" class="stat" :title="t('updatedOn')"><JIcon :icon="ICONS.updated" :size="14" /><span class="tx">{{ formatDate(p.updated) }}</span></span>
              </span>
            </div>
          </li>
          </template>
          <li v-if="!outOpen && split.outside.length && visibleCount >= split.inside.length" class="fold" @click="outOpen = true">
            <span class="stat"><JIcon :icon="ICONS.point" :size="12" /><span class="tx">{{ t("outOfView") }} · {{ split.outside.length }}</span></span>
          </li>
        </ol>
        <div v-if="visibleCount < listedCount" ref="moreSentinel" class="more" />
        </template>
      </section>

      <!-- 最近更新 -->
      <section v-else-if="recent" class="scroll recent">
        <h2 class="recent-title"><JIcon :icon="ICONS.updated" :size="18" /><span class="tx">{{ t("recent") }}</span></h2>
        <div v-if="!recent.length && !recentDone" class="empty"><JIcon :icon="ICONS.loading" :size="28" /></div>
        <template v-for="day in recentDays" :key="day.date">
          <h3 class="day"><time :datetime="day.date">{{ day.date }}</time></h3>
          <a
            v-for="p in day.points"
            :key="`${p.bangumiId}:${p.id}`"
            :href="`${localePath(locale, `/b/${p.bangumiId}`)}?p=${p.id}`"
            class="row"
            @click.prevent="select(p.bangumiId, p.id)"
          >
            <img @error="onImageError" v-if="p.image" :src="imageUrl(p.image)" class="thumb-sm" loading="lazy" referrerpolicy="no-referrer" alt="" />
            <span v-else class="thumb-sm placeholder"><JIcon :icon="ICONS.point" /></span>
            <span class="row-main">
              <strong v-auto-lang>{{ pickName(spotNames(p)) }}</strong>
              <small v-auto-lang>{{ pickName({ cn: p.bangumiCn, original: p.bangumiTitle, en: p.bangumiEn, i18n: p.bangumiI18n }) }}</small>
            </span>
            <span v-if="p.ep" class="row-stats"><span class="stat"><JIcon :icon="ICONS.episode" :size="14" /><span class="tx">{{ formatEpisode(p.ep) }}</span></span></span>
          </a>
        </template>
        <div v-if="!recentDone && recent.length" ref="recentSentinel" class="more" />
      </section>

      <!-- 概览 -->
      <section v-else class="scroll overview">
        <h1><LogoMark :size="24" /><span class="tx">{{ t("brand") }}</span></h1>
        <!-- 全站最近更新的地标：单独的一页 /recent -->
        <a class="recent-link" :href="localePath(locale, '/recent')" @click.prevent="openRecent">
          <JIcon :icon="ICONS.updated" :size="16" /><span class="tx">{{ t("recent") }}</span>
        </a>
        <!-- 起初是热门作品（服务端渲染的真实链接，爬虫能走到每个作品页）；地图一动就换成视野内的作品 -->
        <h2 class="section-label">{{ t(inView ? "inView" : "popular") }}</h2>
        <ul v-if="overviewList.length" class="popular">
          <li v-for="b in overviewList" :key="b.id">
            <a :href="cardPath(b)" @click.prevent="pickCard(b.id)">
              <img @error="onImageError" v-if="b.cover" :src="imageUrl(b.cover)" loading="lazy" referrerpolicy="no-referrer" alt="" />
              <span v-auto-lang class="popular-name" :title="pickName(workNames(b))">{{ pickName(workNames(b)) }}</span>
              <span class="stat"><JIcon :icon="ICONS.point" :size="12" /><span class="tx">{{ b.inView }}</span></span>
            </a>
          </li>
        </ul>
      </section>

      <!-- 地标：单独一页。返回列表用搜索框左边的 ←（与 Esc 相同，各层只有这一个返回）；J / K 切换前后的地标。
           顶部一行只是位置提示：所在作品与第几个地标。手机半屏时截图、名称与导航按钮都在第一屏 -->
      <section v-if="!query.trim() && detail && focusedPoint && !gated" :key="focusedPoint.id" class="scroll point-page">
        <div class="point-bar muted">
          <span v-auto-lang class="point-work">{{ pickName(workNames(detail)) }}</span>
          <span v-if="focusedIndex >= 0" class="stat point-index">{{ focusedIndex + 1 }} / {{ orderedPoints.length }}</span>
        </div>
        <figure v-if="focusedPoint.image" class="point-shot">
          <img @error="onImageError" :src="imageUrl(focusedPoint.image, 'h360')" referrerpolicy="no-referrer" alt="" />
          <figcaption v-if="focusedPoint.origin">
            <a :href="focusedPoint.originLink ?? undefined" target="_blank" rel="noopener">
              <JIcon :icon="ICONS.credit" :size="12" />{{ focusedPoint.origin }}
            </a>
          </figcaption>
        </figure>
        <div class="point-info">
          <div class="point-title">
            <div class="point-names">
              <h2 v-auto-lang>{{ pickName(spotNames(focusedPoint)) }}</h2>
              <!-- 当地原名，方便到现场对照 -->
              <small v-if="localName(focusedPoint)" v-auto-lang>{{ localName(focusedPoint) }}</small>
            </div>
            <a :href="mapsUrl(focusedPoint)" target="_blank" rel="noopener" class="open-maps" :title="t('openInMaps')" :aria-label="t('openInMaps')">
              <JIcon :icon="ICONS.navigate" :size="16" />
            </a>
          </div>
          <span v-if="detail.filter == null && detail.series.length > 1" v-auto-lang class="from">{{ workName(focusedPoint.bangumiId) }}</span>
          <span v-if="focusedPoint.ep || focusedPoint.s || focusedPoint.updated" class="meta">
            <span v-if="focusedPoint.ep" class="stat"><JIcon :icon="ICONS.episode" :size="14" /><span class="tx">{{ formatEpisode(focusedPoint.ep) }}</span></span>
            <span v-if="focusedPoint.s" class="stat"><JIcon :icon="ICONS.time" :size="14" /><span class="tx">{{ formatTime(focusedPoint.s) }}</span></span>
            <span v-if="focusedPoint.updated" class="stat" :title="t('updatedOn')"><JIcon :icon="ICONS.updated" :size="14" /><span class="tx">{{ formatDate(focusedPoint.updated) }}</span></span>
          </span>
          <p v-if="markOf(focusedPoint).text" v-auto-lang class="mark">{{ markOf(focusedPoint).text }}</p>
          <!-- 数据出处：每个地标都能跳到原文；地标有误时开一个预填好的 GitHub issue -->
          <span class="source-row">
            <a v-if="focusedPoint.sourceUrl" :href="focusedPoint.sourceUrl" target="_blank" rel="noopener" class="source stat">
              <JIcon :icon="ICONS.external" :size="12" /><span class="tx">{{ t("sourceLabel") }}：{{ focusedPoint.source ?? new URL(focusedPoint.sourceUrl).hostname }}</span>
            </a>
            <a :href="reportUrl(focusedPoint)" target="_blank" rel="noopener" class="source stat">
              <JIcon :icon="ICONS.report" :size="12" /><span class="tx">{{ t("report") }}</span>
            </a>
          </span>
        </div>
      </section>

      <template #footer>
      <MapFooter
        ref="footer"
        :locale="locale"
        theme-key="junrei:theme"
        repo="https://github.com/Jannchie/junrei"
        :sources="SOURCES"
        :shortcuts="SHORTCUTS"
        @locale="switchLocale"
      >
        <template #credits>
          <label class="mapette-credits-row">
            <input type="checkbox" :checked="showAdult" @change="setShowAdult(($event.target as HTMLInputElement).checked)" />
            <span>{{ t("adultShow") }}</span>
          </label>
        </template>
      </MapFooter>
      </template>
    </MapExplorer>

    <!-- 返回之后的撤销提示 -->
    <Transition name="toast">
      <div v-if="undoHint" class="toast" role="status">
        <span>{{ t("wentBack") }}</span>
        <button type="button" @click="undo()"><JIcon :icon="ICONS.undo" :size="14" /><span class="tx">{{ t("undo") }}</span></button>
      </div>
    </Transition>
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
/* 面板骨架是 mapette 的 MapSheet：各个 section 自己滚动（.scroll），抽屉主体只负责撑满；分隔线由 .scroll / .foot 自己画 */
.mapette-sheet-body {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.mapette-sheet-header,
.mapette-sheet-footer {
  border: 0;
}
@media (max-width: 640px) {
  /* 键盘弹出时，内容区底部让出键盘的高度（抽屉本身不动） */
  .mapette-sheet-full {
    padding-bottom: max(env(safe-area-inset-bottom), var(--keyboard, 0px));
  }
}
/* 地图上的截图标记比 mapette 默认的宽一些（动画截图多是 16:9） */
.mapette-photo-pin {
  width: 128px;
}
/* 图片：加载中、等待重试时是占位底色；重试用尽后显示「图片不可用」图标，和加载中区分开 */
.mapette-sheet img {
  background-color: var(--hover);
}
img.img-failed {
  /* 隐藏破图图标与替代文字 */
  color: transparent;
  font-size: 0;
  background: var(--hover) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2386868b' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='4' width='18' height='16' rx='2'/%3E%3Cpath d='M3 16l5-5 4 4 3-3 6 6'/%3E%3Cpath d='M3 3l18 18'/%3E%3C/svg%3E") center / min(28px, 40%) no-repeat;
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
@media (max-width: 640px) {
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
  font-size: 16px; /* iOS 会在聚焦小于 16px 的输入框时自动放大页面 */
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
/* 没有地标的作品：封面淡一些，一眼能和有地标的区分 */
.row.dim .cover-sm {
  opacity: 0.5;
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
  border-bottom: 1px solid var(--line);
}
.title-row {
  display: flex;
  gap: 12px;
}
.title-main {
  flex: 1;
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
/* 主要人员：职位在左、人名在右的两列；角色是可换行的一串 */
.credits {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px 12px;
  margin: 12px 0 0;
  font-size: 12px;
}
.credits dt {
  color: var(--muted);
  white-space: nowrap;
}
.credits dd {
  margin: 0;
}
.cast {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.cast small {
  margin-left: 4px;
  color: var(--muted);
}
.more-cast {
  padding: 0;
  font: inherit;
  color: var(--accent);
  background: none;
  border: 0;
  cursor: pointer;
}
.more-btn {
  flex: none;
  align-self: flex-start;
  margin: -4px -6px 0 0;
}
.links-pop {
  position: fixed;
  inset: auto;
  margin: 0;
  min-width: 168px;
  padding: 4px;
  color: var(--fg);
  background: var(--bg);
  border: 0;
  border-radius: 12px;
  box-shadow: var(--shadow);
  backdrop-filter: var(--glass);
}
.links-pop:popover-open {
  display: flex;
  flex-direction: column;
}
.links-pop a {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  font-size: 13px;
  color: inherit;
  text-decoration: none;
  border-radius: 8px;
}
.links-pop a:hover {
  background: var(--hover);
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
.points li:not(:has(figure)) {
  grid-template-columns: minmax(0, 1fr);
}
.points li figcaption {
  display: none;
}
.points li.active {
  background: color-mix(in oklab, var(--accent) 8%, transparent);
}
.points li.active .point-body > .spot-link {
  color: var(--accent);
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
.recent-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 16px 8px; /* 与概览的标题（.overview h1）对齐 */
  font-size: 18px;
}
/* 日期分组的标题吸顶，滚动时始终知道看到的是哪一天 */
.recent .day {
  position: sticky;
  top: 0;
  z-index: 1;
  margin: 0;
  padding: 10px 16px 6px;
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  background: var(--bg-solid);
}
.recent a.row {
  text-decoration: none;
}
.recent-link {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 18px;
  padding: 10px 12px;
  color: inherit;
  text-decoration: none;
  background: var(--hover);
  border-radius: 10px;
}
.recent-link:hover {
  color: var(--accent);
}
/* 撤销提示：地图下方居中，手机上在抽屉上方 */
.toast {
  position: absolute;
  left: 50%;
  bottom: calc(var(--panel-inset-bottom, 0px) + 16px);
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 6px 6px 14px;
  font-size: 13px;
  color: var(--fg);
  background: var(--bg);
  border-radius: 10px;
  box-shadow: var(--shadow);
  backdrop-filter: var(--glass);
  transform: translateX(-50%);
}
.toast button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  font: inherit;
  font-weight: 600;
  color: var(--accent);
  background: none;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}
.toast button:hover {
  background: var(--hover);
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}
.spot-link {
  color: inherit;
  text-decoration: none;
}
.points li.fold {
  display: block;
  padding: 8px 16px;
  color: var(--muted);
  font-size: 12px;
  background: var(--hover);
}
.series {
  display: flex;
  gap: 6px;
  padding: 10px 16px;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  scrollbar-width: none;
}
/* 系列里的作品：小封面 + 名称 + 年份 / 地点数。选中的那张用作品主题色淡淡铺底、细描边，不整块填色 */
.series a {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 172px;
  padding: 5px 10px 5px 5px;
  font-size: 12px;
  text-decoration: none;
  border-radius: 10px;
  box-shadow: inset 0 0 0 1px var(--line);
  transition: background-color 0.15s, box-shadow 0.15s;
}
.series a:hover {
  background: var(--hover);
}
.series a.current {
  background: color-mix(in oklab, var(--accent) 10%, transparent);
  box-shadow: inset 0 0 0 1.5px color-mix(in oklab, var(--accent) 70%, transparent);
}
.series a.current .series-name {
  color: color-mix(in oklab, var(--accent) 75%, var(--fg));
}
.series a.dim:not(.current) {
  opacity: 0.55;
}
.series-cover,
.series-covers img {
  flex: none;
  width: 30px;
  height: 42px;
  object-fit: cover;
  border-radius: 5px;
  background: var(--line);
}
.series-covers {
  display: flex;
  flex: none;
}
.series-covers img {
  box-shadow: 0 0 0 1.5px var(--bg);
}
.series-covers img + img {
  margin-left: -18px;
}
.series-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.series-name {
  overflow: hidden;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.series .stat {
  gap: 3px;
  font-size: 11px;
  color: var(--muted);
}
.from {
  overflow: hidden;
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  text-overflow: ellipsis;
}
.row-stats {
  display: flex;
  flex: none;
  gap: 8px;
}
.no-spots {
  padding: 32px 24px;
  font-size: 13px;
  text-align: center;
}
/* 地标页：顶部返回栏、截图、名称与导航按钮。手机半屏（约 46dvh）时这些都在第一屏 */
.point-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 16px 8px;
  font-size: 12px;
}
.point-work {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.point-index {
  flex: none;
  font-size: 12px;
}
.point-shot {
  margin: 0 12px;
}
.point-shot img {
  border-radius: 10px;
}
.point-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 16px 16px;
}
.point-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.point-names {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.point-names h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
}
.point-names small {
  font-size: 12px;
  color: var(--muted);
}
.point-info .meta {
  font-size: 12px;
}
@media (max-width: 640px) {
  /* 手机半屏（可用高度两百多像素）：截图占满宽度，顶部的位置提示先不显示（拉到全屏时出现），
     截图下面紧接名称、导航按钮与集数，都在第一屏 */
  :where(.mapette-sheet:not(.mapette-sheet-full)) .point-bar {
    display: none;
  }
  :where(.mapette-sheet:not(.mapette-sheet-full)) .point-shot {
    margin-top: 10px;
  }
  :where(.mapette-sheet:not(.mapette-sheet-full)) .point-info {
    padding-top: 8px;
  }
}
.open-maps {
  flex: none;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  color: #fff;
  background: var(--accent);
  border-radius: 50%;
}
.source-row {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
}
.source {
  align-self: flex-start;
  margin-top: 2px;
  font-size: 11px;
  color: var(--muted);
}
.source:hover {
  color: var(--fg);
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
  grid-template-columns: repeat(3, minmax(0, 1fr)); /* minmax(0, …)：不换行的长标题不会把列撑宽 */
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
  /* 一行显示，放不下省略，网格各格高度一致；完整名称在悬停提示里 */
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.popular .stat {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
  font-weight: 400;
}
.adult-gate {
  display: grid;
  justify-items: center;
  gap: 12px;
  padding: 48px 24px;
  color: var(--muted);
  text-align: center;
}
.adult-gate p {
  margin: 0;
  font-size: 13px;
}
.adult-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}
.adult-actions button {
  padding: 6px 14px;
  font: inherit;
  font-size: 13px;
  color: var(--fg);
  background: var(--hover);
  border: 0;
  border-radius: 999px;
  cursor: pointer;
}
.adult-actions .primary {
  color: #fff;
  background: var(--accent);
}
/* 地图上的地标卡片（MapPopover 的内容） */
.point-pop {
  width: 240px;
  overflow: hidden;
  border-radius: inherit;
}
.point-pop img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}
.point-pop-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px 10px;
  font-size: 13px;
  line-height: 1.4;
}
.point-pop-text strong {
  font-weight: 600;
}
</style>
