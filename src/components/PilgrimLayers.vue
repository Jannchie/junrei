<script setup lang="ts">
// 放在 MapExplorer 的 #map 插槽里：巡礼自己的地图逻辑——选中作品的高亮与淡化、当前地标、镜头、
// 成人向地标的显示开关、点击地标、视野变化，以及放大后显示截图的标记。
// 底图、比例尺、按钮、面板、留白与通用快捷键都由 @mapette/vue 的 MapExplorer 提供。
import { readPalette } from "@mapette/core";
import { ClusterPopover, PhotoPins, useMap } from "@mapette/vue";
import ClusterWorks from "./ClusterWorks.vue";
import type { GeoJSONSource, LngLatBounds, Map as MaplibreMap, MapGeoJSONFeature } from "maplibre-gl";
import { computed, ref, watch } from "vue";
import { showAdult } from "../adult";
import { fetchDetail } from "../detail";
import { imageUrl } from "../format";

export interface SelectedPoint {
  id: string;
  /** 所属作品（系列「全部」时各地标来自不同作品） */
  b: number;
  name: string | null;
  lng: number;
  lat: number;
}

const props = defineProps<{
  /** 选中作品的地标，高亮并显示名称 */
  selected: { bangumiId: number; points: SelectedPoint[] } | null;
  focusPointId: string | null;
}>();

const emit = defineEmits<{
  pick: [bangumiId: number, pointId: string];
  /** 视口范围变化（拖动、缩放结束后） */
  view: [bounds: { west: number; south: number; east: number; north: number }];
}>();

const { controller } = useMap();
const map = () => controller.value?.map;

/** 选中作品变化：换高亮源的数据，切换淡化状态 */
function syncSelected() {
  const m = map();
  if (!m?.getSource("selected")) return;
  const sel = props.selected;
  (m.getSource("selected") as GeoJSONSource).setData({
    type: "FeatureCollection",
    features: (sel?.points ?? []).map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lng, p.lat] },
      properties: { b: p.b, p: p.id, name: p.name ?? "" },
    })),
  });
  m.setGlobalStateProperty("selected", sel != null);
  m.setGlobalStateProperty("adult", showAdult.value);
  // 选中作品的地标用主题色（不再按作品分颜色，界面颜色保持稳定）
  m.setGlobalStateProperty("selectedColor", readPalette(m.getContainer()).accent);
}

/** 焦点变化：只改 feature-state，不重建数据 */
function syncFocus(next: string | null, prev: string | null) {
  const m = map();
  if (!m?.getSource("selected")) return;
  if (prev) m.setFeatureState({ source: "selected", id: prev }, { focus: false });
  if (next) m.setFeatureState({ source: "selected", id: next }, { focus: true });
  m.setGlobalStateProperty("focus", next ?? "");
}

// 相机由「作品:焦点」决定，同一个 key 只移动一次；地图就绪前的选择会在就绪后补上
let cameraKey = "";
let pickedOnMap = "";
// 链接里带了视野（#map=…）时，首次选中不移动相机，尊重链接里的视野
let keepLinkedView = typeof location !== "undefined" && location.hash.includes("map=");
function syncCamera() {
  const m = map();
  const sel = props.selected;
  if (!m || !sel?.points.length) return;
  const key = `${sel.bangumiId}:${props.focusPointId ?? ""}`;
  if (key === cameraKey) return;
  // 从地标退回同一部作品（Esc、返回）：镜头留在原处，不跳回整部作品的范围
  const backToWork = !props.focusPointId && cameraKey.startsWith(`${sel.bangumiId}:`);
  cameraKey = key;
  if (backToWork) return;
  if (keepLinkedView) {
    keepLinkedView = false;
    return;
  }
  // 在地图上直接点的地标：它就在眼前，镜头不动
  if (key === pickedOnMap) return;
  const focus = sel.points.find((p) => p.id === props.focusPointId);
  // 选中地标、换作品都从不改缩放（自动缩放对用户是负担）。
  // 地标：看不到才平移过去。作品：已经能看到它的地标就不动，一个都看不到才平移到它主要区域的中心
  if (focus) {
    controller.value?.reveal([focus.lng, focus.lat]);
  } else if (!sel.points.some((p) => inView(m, p))) {
    const c = coreBounds(sel.points).getCenter();
    controller.value?.reveal([c.lng, c.lat]);
  }
}

/** 地标是否在可见区域里（面板挡住的部分不算） */
function inView(m: MaplibreMap, p: SelectedPoint) {
  const pad = controller.value!.getPadding();
  const c = m.getContainer();
  const { x, y } = m.project([p.lng, p.lat]);
  return x >= pad.left! && x <= c.clientWidth - pad.right! && y >= pad.top! && y <= c.clientHeight - pad.bottom!;
}

/** 作品的主要区域：去掉经纬度两端各 10% 的离群地标（外地零星的点不该把镜头拉远） */
function coreBounds(points: SelectedPoint[]): LngLatBounds {
  const pick = (values: number[]) => {
    const v = [...values].sort((a, b) => a - b);
    const cut = v.length >= 10 ? Math.floor(v.length * 0.1) : 0;
    return [v[cut], v[v.length - 1 - cut]] as const;
  };
  const [w, e] = pick(points.map((p) => p.lng));
  const [s, n] = pick(points.map((p) => p.lat));
  return new controller.value!.lib.LngLatBounds([w, s], [e, n]);
}

watch(controller, (ctrl) => {
  if (!ctrl) return;
  const m = ctrl.map;
  if (import.meta.env.DEV) {
    Object.assign(window, { __map: m }); // 调试用
    m.on("error", (e) => console.error("[map]", e.error));
  }
  // 首次加载，以及换主题时 diff 失败退回整体重载，都会触发 style.load；全局状态和高亮要重新应用
  ctrl.onStyleLoad(() => {
    syncSelected();
    syncFocus(props.focusPointId, null);
    syncCamera();
  });

  const reportView = () => {
    const b = m.getBounds();
    emit("view", { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() });
  };
  m.on("moveend", reportView);
  if (m.loaded()) reportView();
  else m.once("load", reportView);

  for (const layer of ["point", "selected-point"]) {
    m.on("click", layer, (e) => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      pickedOnMap = `${p.b}:${p.p}`;
      emit("pick", Number(p.b), String(p.p));
    });
    m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
    m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
  }
}, { immediate: true });

const pins = ref<{ refresh(): void }>();
watch(showAdult, (on) => {
  map()?.setGlobalStateProperty("adult", on);
  pins.value?.refresh();
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

// ---- 放大到街区级别时，视野里的地标直接显示截图（与作品面板共用同一份详情请求，src/detail.ts）----
const pinKey = (f: MapGeoJSONFeature) => `${f.properties.b}:${f.properties.p}`;
async function images(features: MapGeoJSONFeature[]) {
  const ids = [...new Set(features.map((f) => Number(f.properties.b)))];
  const byWork = new Map(await Promise.all(ids.map(async (b) => {
    const d = await fetchDetail(b).catch(() => null);
    return [b, new Map((d?.points ?? []).flatMap((x) => (x.image ? [[x.id, x.image] as [string, string]] : [])))] as const;
  })));
  return features.map((f) => {
    const src = byWork.get(Number(f.properties.b))?.get(String(f.properties.p));
    return src ? imageUrl(src) : null;
  });
}
const focusKey = computed(() => {
  const p = props.selected?.points.find((x) => x.id === props.focusPointId);
  return p ? `${p.b}:${p.id}` : null;
});
function onPin(f: MapGeoJSONFeature) {
  pickedOnMap = pinKey(f);
  emit("pick", Number(f.properties.b), String(f.properties.p));
}
</script>

<template>
  <!-- 点气泡：不放大，弹出卡片按作品列出里面的地标 -->
  <ClusterPopover source="points">
    <template #default="{ features, count, close }">
      <ClusterWorks :features="features" :count="count" @pick="(b) => { close(); emit('pick', b, ''); /* 只选作品，不选地标 */ }" />
    </template>
  </ClusterPopover>
  <PhotoPins
    ref="pins"
    :layers="['selected-point', 'point']"
    :feature-key="pinKey"
    :images="images"
    :focus="focusKey"
    :min-zoom="17"
    :max="30"
    :gap="120"
    @pick="onPin"
  />
</template>
