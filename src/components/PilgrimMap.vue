<script setup lang="ts">
import { JIcon } from "@jannchie/icons-vue";
import type { Point } from "geojson";
import maplibregl, { type GeoJSONSource, type LngLatLike, type PaddingOptions } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { locale, t } from "../i18n";
import { ICONS } from "../icons";
import { CJK_FONT_FAMILY, createStyle, readPalette } from "../map-style";

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

const emit = defineEmits<{ pick: [bangumiId: number, pointId: string] }>();

const el = ref<HTMLDivElement>();
let map: maplibregl.Map | null = null;
let geolocate: maplibregl.GeolocateControl | null = null;
const ready = ref(false);
const dark = matchMedia("(prefers-color-scheme: dark)");

// 换主题或语言只换颜色和国名：样式按 diff 更新。两个 geojson 源沿用当前的定义（序列化后与 createStyle 的写法不同，
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
  map.setGlobalStateProperty("selectedColor", sel?.color ?? readPalette().accent);
}

/** 焦点变化：只改 feature-state，不重建数据 */
function syncFocus(next: string | null, prev: string | null) {
  if (!ready.value || !map) return;
  if (prev) map.setFeatureState({ source: "selected", id: prev }, { focus: false });
  if (next) map.setFeatureState({ source: "selected", id: next }, { focus: true });
}

// 相机由「作品:焦点」决定，同一个 key 只移动一次；地图就绪前的选择会在就绪后补上
let cameraKey = "";
function syncCamera() {
  const sel = props.selected;
  if (!ready.value || !map || !sel?.points.length) return;
  const key = `${sel.bangumiId}:${props.focusPointId ?? ""}`;
  if (key === cameraKey) return;
  cameraKey = key;
  const focus = sel.points.find((p) => p.id === props.focusPointId);
  // setPadding 会打断进行中的动画，所以只在相机空闲时或发起新动作前调用（见下方 padding 的 watch）
  map.setPadding(props.padding);
  if (focus) {
    map.flyTo({ center: [focus.lng, focus.lat], zoom: Math.max(map.getZoom(), 15) });
  } else {
    const bounds = new maplibregl.LngLatBounds();
    for (const p of sel.points) bounds.extend([p.lng, p.lat]);
    map.fitBounds(bounds, { padding: 80, maxZoom: 15 });
  }
}

onMounted(() => {
  const m = (map = new maplibregl.Map({
    container: el.value!,
    style: createStyle(readPalette(), locale.value),
    center: [137.5, 36.2],
    zoom: 4.6,
    padding: props.padding,
    localIdeographFontFamily: CJK_FONT_FAMILY,
    attributionControl: false, // 署名放在面板底部
  }));
  if (import.meta.env.DEV) {
    Object.assign(window, { __map: m }); // 调试用
    m.on("error", (e) => console.error("[map]", e.error));
  }
  dark.addEventListener("change", restyle);

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

  m.on("click", "clusters", async (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const zoom = await (m.getSource("points") as GeoJSONSource).getClusterExpansionZoom(f.properties.cluster_id as number);
    // 展开级别常常只比当前大 1，大聚合要点很多次，至少放大两级
    m.easeTo({ center: (f.geometry as Point).coordinates as LngLatLike, zoom: Math.max(zoom, m.getZoom() + 2) });
  });
  for (const layer of ["point", "selected-point"]) {
    m.on("click", layer, (e) => {
      const p = e.features?.[0]?.properties;
      if (p) emit("pick", Number(p.b), String(p.p));
    });
  }
  for (const layer of ["point", "selected-point", "clusters"]) {
    m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
    m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
  }
});

onBeforeUnmount(() => {
  dark.removeEventListener("change", restyle);
  map?.remove();
});

watch(locale, restyle);
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
}
.map :deep(.maplibregl-ctrl-geolocate) {
  display: none;
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
  backdrop-filter: saturate(180%) blur(20px);
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
