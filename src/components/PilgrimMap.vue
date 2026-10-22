<script setup lang="ts">
import { JIcon } from "@jannchie/icons-vue";
import type { Point } from "geojson";
import maplibregl, { type GeoJSONSource, type LngLatLike, type PaddingOptions } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "../i18n";
import { ICONS } from "../icons";
import { fetchDetail } from "../detail";
import { imageUrl } from "../format";
import { CJK_FONT_FAMILY, createStyle, HEAT_FADE, readPalette } from "../map-style";
import { isDark } from "../theme";

export interface SelectedPoint {
  id: string;
  name: string | null;
  lng: number;
  lat: number;
}

const props = defineProps<{
  /** 选中作品的地标，高亮并显示名称 */
  selected: { bangumiId: number; color: string | null; points: SelectedPoint[] } | null;
  focusPointId: string | null;
  /** 被浮层面板挡住的边距，地图的可视中心会避开它 */
  padding: PaddingOptions;
}>();

const emit = defineEmits<{
  pick: [bangumiId: number, pointId: string];
  /** 视口范围变化（拖动、缩放结束后） */
  view: [bounds: { west: number; south: number; east: number; north: number }];
}>();

const { locale, t } = useI18n();
const el = ref<HTMLDivElement>();
let map: maplibregl.Map | null = null;

// 给页面的键盘快捷键用
defineExpose({
  zoomIn: () => map?.zoomIn(),
  zoomOut: () => map?.zoomOut(),
  locate: () => geolocate?.trigger(),
});
let geolocate: maplibregl.GeolocateControl | null = null;
const ready = ref(false);

// 换主题或语言只换颜色和地名字段：样式按 diff 更新。两个 geojson 源沿用当前的定义（序列化后与 createStyle 的写法不同，
// 否则 diff 会把它们当成新源，重新加载、重新聚合 5 万个点）
function restyle() {
  map?.setStyle(createStyle(readPalette(), locale.value), {
    transformStyle: (prev, next) => ({
      ...next,
      sources: { ...next.sources, points: prev!.sources.points, selected: prev!.sources.selected },
    }),
  });
}

/** 选中作品变化：换高亮源的数据，切换淡化状态 */
function syncSelected() {
  if (!ready.value || !map) return;
  const sel = props.selected;
  (map.getSource("selected") as GeoJSONSource).setData({
    type: "FeatureCollection",
    features: (sel?.points ?? []).map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lng, p.lat] },
      properties: { b: sel!.bangumiId, p: p.id, name: p.name ?? "" },
    })),
  });
  map.setGlobalStateProperty("selected", sel != null);
  const color = sel?.color ?? readPalette().accent;
  map.setGlobalStateProperty("selectedColor", color);
  el.value?.style.setProperty("--focus-color", color); // 选中地标的截图描边用作品色
}

/** 焦点变化：只改 feature-state，不重建数据 */
function syncFocus(next: string | null, prev: string | null) {
  if (!ready.value || !map) return;
  if (prev) map.setFeatureState({ source: "selected", id: prev }, { focus: false });
  if (next) map.setFeatureState({ source: "selected", id: next }, { focus: true });
  map.setGlobalStateProperty("focus", next ?? "");
  for (const [key, marker] of photoMarkers) marker.getElement().classList.toggle("focus", key.endsWith(`:${next}`));
}

// 相机由「作品:焦点」决定，同一个 key 只移动一次；地图就绪前的选择会在就绪后补上
let cameraKey = "";
let pickedOnMap = "";
// 链接里带了视野（#map=…）时，首次选中不移动相机，尊重链接里的视野
let keepLinkedView = typeof location !== "undefined" && location.hash.includes("map=");
function syncCamera() {
  const sel = props.selected;
  if (!ready.value || !map || !sel?.points.length) return;
  const key = `${sel.bangumiId}:${props.focusPointId ?? ""}`;
  if (key === cameraKey) return;
  cameraKey = key;
  if (keepLinkedView) {
    keepLinkedView = false;
    return;
  }
  // 在地图上直接点的地标：它就在眼前，镜头不动
  if (key === pickedOnMap) return;
  const focus = sel.points.find((p) => p.id === props.focusPointId);
  // setPadding 会打断进行中的动画，所以只在相机空闲时或发起新动作前调用（见下方 padding 的 watch）
  map.setPadding(props.padding);
  // 都用 easeTo（fitBounds 设 linear）：flyTo 途中会先拉远再推近，像跳了一下
  if (focus) {
    map.easeTo({ center: [focus.lng, focus.lat], zoom: Math.max(map.getZoom(), 15), duration: 800 });
  } else {
    map.fitBounds(coreBounds(sel.points), { padding: 80, maxZoom: 15, linear: true, duration: 800 });
  }
}

/** 作品的主要区域：去掉经纬度两端各 10% 的离群地标（外地零星的点不该把镜头拉远） */
function coreBounds(points: SelectedPoint[]) {
  const pick = (values: number[]) => {
    const v = [...values].sort((a, b) => a - b);
    const cut = v.length >= 10 ? Math.floor(v.length * 0.1) : 0;
    return [v[cut], v[v.length - 1 - cut]] as const;
  };
  const [w, e] = pick(points.map((p) => p.lng));
  const [s, n] = pick(points.map((p) => p.lat));
  return new maplibregl.LngLatBounds([w, s], [e, n]);
}

// ---- 放大到街区级别时，视野里的地标直接显示截图 ----
const PHOTO_ZOOM = 17;
const PHOTO_MAX = 30;
const PHOTO_GAP = 120; // 屏幕上两张截图中心的最小距离（px），太近的跳过
type PointImages = Map<string, string>; // 地标 id → 截图地址
// 与作品面板共用同一份详情请求（src/detail.ts）
const pointImages = (bangumiId: number): Promise<PointImages> =>
  fetchDetail(bangumiId).then(
    (d) => new Map(d.points.flatMap((x) => (x.image ? [[x.id, x.image] as [string, string]] : []))),
    () => new Map(),
  );

const photoMarkers = new Map<string, maplibregl.Marker>();
let photoSeq = 0;
async function syncPhotos() {
  const m = map;
  if (!m) return;
  const seq = ++photoSeq;
  if (m.getZoom() < PHOTO_ZOOM) {
    for (const marker of photoMarkers.values()) marker.remove();
    photoMarkers.clear();
    return;
  }
  // 按屏幕位置挑出互不重叠的地标
  const picked: { b: number; p: string; lngLat: [number, number]; x: number; y: number }[] = [];
  for (const f of m.queryRenderedFeatures({ layers: ["selected-point", "point"] })) {
    const { b, p } = f.properties as { b: number; p: string };
    const lngLat = (f.geometry as Point).coordinates as [number, number];
    const { x, y } = m.project(lngLat);
    if (picked.some((q) => q.p === p || Math.hypot(q.x - x, q.y - y) < PHOTO_GAP)) continue;
    picked.push({ b: Number(b), p: String(p), lngLat, x, y });
    if (picked.length >= PHOTO_MAX) break;
  }
  const images = new Map(await Promise.all([...new Set(picked.map((q) => q.b))].map(async (b) => [b, await pointImages(b)] as const)));
  if (seq !== photoSeq) return;
  const keep = new Set<string>();
  for (const q of picked) {
    const src = images.get(q.b)?.get(q.p);
    if (!src) continue;
    const key = `${q.b}:${q.p}`;
    keep.add(key);
    if (photoMarkers.has(key)) continue;
    const el = document.createElement("button");
    el.className = props.focusPointId === q.p ? "photo-pin focus" : "photo-pin";
    el.title = "";
    el.innerHTML = `<img alt="" referrerpolicy="no-referrer" src="${imageUrl(src)}">`;
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      pickedOnMap = `${q.b}:${q.p}`;
      emit("pick", q.b, q.p);
    });
    photoMarkers.set(key, new maplibregl.Marker({ element: el, anchor: "bottom", offset: [0, -8] }).setLngLat(q.lngLat).addTo(m));
  }
  for (const [key, marker] of photoMarkers) {
    if (!keep.has(key)) {
      marker.remove();
      photoMarkers.delete(key);
    }
  }
}

onMounted(() => {
  const m = (map = new maplibregl.Map({
    container: el.value!,
    style: createStyle(readPalette(), locale.value),
    center: [137.5, 36.2],
    zoom: 4.6,
    // 视野写进 URL 的 #map=缩放/纬度/经度，链接打开就是同一片区域
    hash: "map",
    padding: props.padding,
    localIdeographFontFamily: CJK_FONT_FAMILY,
    attributionControl: false, // 署名放在面板底部
    // 默认只在内存里留 5 个缩放级别的瓦片，来回缩放会重新加载；淡入时间也缩短，加载完更快显现
    maxTileCacheZoomLevels: 10,
    fadeDuration: 150,
  }));
  if (import.meta.env.DEV) {
    Object.assign(window, { __map: m }); // 调试用
    m.on("error", (e) => console.error("[map]", e.error));
  }

  // 定位用 maplibre 自带的控件画位置点，按钮换成自己的（见模板），原按钮用 CSS 隐藏
  geolocate = new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: true });
  m.addControl(geolocate, "bottom-right");

  // 首次加载，以及换主题时 diff 失败退回整体重载，都会触发 style.load；全局状态和高亮要重新应用
  m.on("style.load", () => {
    ready.value = true;
    syncSelected();
    syncFocus(props.focusPointId, null);
    syncCamera();
  });

  const reportView = () => {
    const b = m.getBounds();
    emit("view", { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() });
  };
  m.on("moveend", reportView);
  m.once("load", reportView);

  // 热力图阶段没有可点的地标：点击地图即以该处为中心放大两级
  m.on("click", (e) => {
    if (m.getZoom() >= HEAT_FADE[0]) return;
    if (m.queryRenderedFeatures(e.point, { layers: ["selected-point"] }).length) return;
    m.easeTo({ center: e.lngLat, zoom: m.getZoom() + 2 });
  });
  m.on("moveend", syncPhotos);
  m.once("idle", syncPhotos); // 直接从带视野的链接打开时没有 moveend
  for (const layer of ["point", "selected-point"]) {
    m.on("click", layer, (e) => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      pickedOnMap = `${p.b}:${p.p}`;
      emit("pick", Number(p.b), String(p.p));
    });
  }
  for (const layer of ["point", "selected-point"]) {
    m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
    m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
  }
});

onBeforeUnmount(() => {
  for (const marker of photoMarkers.values()) marker.remove();
  map?.remove();
});

watch([locale, isDark], restyle);
watch(() => props.padding, () => {
  if (!map) return;
  if (map.isMoving()) map.once("moveend", () => map?.setPadding(props.padding));
  else map.setPadding(props.padding);
});
watch(() => props.selected, () => {
  syncSelected();
  syncFocus(props.focusPointId, null);
  syncCamera();
});
watch(() => props.focusPointId, (next, prev) => {
  syncFocus(next, prev);
  syncCamera();
});
</script>

<template>
  <div ref="el" class="map" />
  <div class="controls">
    <button :title="t('locate')" :aria-label="t('locate')" @click="geolocate?.trigger()"><JIcon :icon="ICONS.locate" /></button>
    <div class="group">
      <button :title="t('zoomIn')" :aria-label="t('zoomIn')" @click="map?.zoomIn()"><JIcon :icon="ICONS.zoomIn" /></button>
      <button :title="t('zoomOut')" :aria-label="t('zoomOut')" @click="map?.zoomOut()"><JIcon :icon="ICONS.zoomOut" /></button>
    </div>
  </div>
</template>

<style scoped>
.map {
  position: absolute;
  inset: 0;
  /* 缩到最小时地球之外露出的是容器背景 */
  background: radial-gradient(circle at 60% 50%, var(--map-horizon), var(--map-space) 70%);
}
.map :deep(.maplibregl-ctrl-geolocate) {
  display: none;
}
.map :deep(.photo-pin) {
  /* 不要设 position：maplibre 靠 .maplibregl-marker 的 absolute 与 transform 定位标记 */
  display: block;
  width: 128px;
  height: 76px;
  padding: 3px;
  background: #ffffff;
  border: 0;
  border-radius: 10px;
  box-shadow: 0 1px 4px rgb(0 0 0 / 0.18);
  cursor: pointer;
}
/* 当前选中地标的截图：作品色描边，并压在其他截图上面 */
.map :deep(.maplibregl-marker:has(.photo-pin.focus)) {
  z-index: 1;
}
.map :deep(.photo-pin.focus),
.map :deep(.photo-pin.focus)::after {
  background: var(--focus-color, var(--accent));
}
.map :deep(.photo-pin)::after {
  /* 指向地标的小尖角 */
  content: "";
  position: absolute;
  left: 50%;
  bottom: -6px;
  width: 12px;
  height: 12px;
  background: #ffffff;
  transform: translateX(-50%) rotate(45deg);
  border-radius: 0 0 2px 0;
}
.map :deep(.photo-pin img) {
  position: relative;
  z-index: 1;
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 7px;
  background: #e5e7eb;
}
.controls {
  position: absolute;
  right: 12px;
  bottom: calc(var(--panel-inset-bottom, 0px) + 36px);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.group {
  display: flex;
  flex-direction: column;
}
.controls button {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  color: var(--fg);
  background: var(--bg);
  border: 0;
  border-radius: 10px;
  box-shadow: var(--shadow);
  backdrop-filter: var(--glass);
  cursor: pointer;
}
.group button:first-child {
  border-radius: 10px 10px 0 0;
  box-shadow: var(--shadow), inset 0 -0.5px 0 var(--line);
}
.group button:last-child {
  border-radius: 0 0 10px 10px;
}
.controls button:hover {
  background: var(--hover);
}
</style>
