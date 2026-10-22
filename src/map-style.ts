// junrei 的地图皮肤「和纸与墨」：亮色是和纸，暗色是墨。
// 矢量瓦片来自 OpenFreeMap（OpenMapTiles schema），只保留巡礼用得上的要素：
// 水、绿地、道路细线、铁路（JR 式黑白相间）、车站、地名。
import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";

const PALETTE_KEYS = [
  "land", "wood", "grass", "park", "water", "building", "buildingLine", "road", "roadCasing", "major",
  "majorCasing", "rail", "boundary", "label", "labelMuted", "waterLabel", "focusRing",
] as const;

export type Palette = Record<(typeof PALETTE_KEYS)[number] | "accent", string>;

/** 配色只在 src/theme.css 里定义一份，这里按当前亮暗模式读出来 */
export function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement);
  const read = (name: string) => css.getPropertyValue(name).trim();
  const palette = { accent: read("--accent") } as Palette;
  for (const key of PALETTE_KEYS) palette[key] = read(`--map-${key.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)}`);
  return palette;
}

/** 中日文字由浏览器本地字体绘制：用明朝体，拉丁字母走 glyph 服务的 Noto Sans */
export const CJK_FONT_FAMILY = "'Hiragino Mincho ProN', 'Yu Mincho', 'YuMincho', 'Noto Serif JP', 'Noto Serif CJK JP', serif";

const SOURCE = "openmaptiles";
const FONT = ["Noto Sans Regular"];
const FONT_BOLD = ["Noto Sans Bold"];
const CLUSTER_RADIUS: ExpressionSpecification = ["step", ["get", "point_count"], 11, 50, 14, 500, 18, 5000, 24];
/** 当地名称：日本境内即日文原名，与作品里的地名一致 */
const NAME: ExpressionSpecification = ["get", "name"];

/** 线宽随缩放指数增长 */
const width = (pairs: [number, number][]): ExpressionSpecification =>
  ["interpolate", ["exponential", 1.6], ["zoom"], ...pairs.flat()] as ExpressionSpecification;

export function createStyle(c: Palette): StyleSpecification {
  const roadClasses = (classes: string[]): ExpressionSpecification => [
    "all",
    ["match", ["get", "class"], classes, true, false],
    ["!=", ["get", "brunnel"], "tunnel"],
  ];

  const layers: LayerSpecification[] = [
    { id: "land", type: "background", paint: { "background-color": c.land } },

    // ---- 地表 ----
    {
      id: "landcover",
      type: "fill",
      source: SOURCE,
      "source-layer": "landcover",
      filter: ["match", ["get", "class"], ["wood", "grass", "farmland", "wetland"], true, false],
      paint: {
        "fill-color": ["match", ["get", "class"], "wood", c.wood, c.grass],
        "fill-opacity": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 12, 1],
      },
    },
    {
      id: "park",
      type: "fill",
      source: SOURCE,
      "source-layer": "park",
      minzoom: 9,
      paint: { "fill-color": c.park },
    },
    {
      id: "water",
      type: "fill",
      source: SOURCE,
      "source-layer": "water",
      filter: ["!=", ["get", "brunnel"], "tunnel"],
      paint: { "fill-color": c.water },
    },
    {
      id: "waterway",
      type: "line",
      source: SOURCE,
      "source-layer": "waterway",
      minzoom: 8,
      filter: ["match", ["get", "class"], ["river", "canal"], true, false],
      paint: { "line-color": c.water, "line-width": width([[8, 0.6], [14, 3], [18, 10]]) },
    },
    {
      id: "building",
      type: "fill",
      source: SOURCE,
      "source-layer": "building",
      minzoom: 14,
      paint: {
        "fill-color": c.building,
        "fill-outline-color": c.buildingLine,
        "fill-opacity": ["interpolate", ["linear"], ["zoom"], 14, 0, 15, 1],
      },
    },

    // ---- 边界 ----
    {
      id: "boundary-state",
      type: "line",
      source: SOURCE,
      "source-layer": "boundary",
      minzoom: 5,
      filter: ["all", ["==", ["get", "admin_level"], 4], ["!=", ["get", "maritime"], 1]],
      paint: { "line-color": c.boundary, "line-width": 0.6, "line-dasharray": [2, 2], "line-opacity": 0.6 },
    },
    {
      id: "boundary-country",
      type: "line",
      source: SOURCE,
      "source-layer": "boundary",
      filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
      paint: { "line-color": c.boundary, "line-width": width([[3, 0.6], [10, 1.4]]) },
    },

    // ---- 道路：克制的细线 ----
    {
      id: "road-minor-casing",
      type: "line",
      source: SOURCE,
      "source-layer": "transportation",
      minzoom: 13,
      filter: roadClasses(["minor", "service", "tertiary"]),
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": c.roadCasing, "line-width": width([[13, 1.5], [16, 6], [19, 22]]) },
    },
    {
      id: "road-major-casing",
      type: "line",
      source: SOURCE,
      "source-layer": "transportation",
      minzoom: 9,
      filter: roadClasses(["primary", "secondary", "trunk", "motorway"]),
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": c.majorCasing, "line-width": width([[9, 1.2], [13, 3.5], [16, 9], [19, 28]]) },
    },
    {
      id: "road-minor",
      type: "line",
      source: SOURCE,
      "source-layer": "transportation",
      minzoom: 13,
      filter: roadClasses(["minor", "service", "tertiary"]),
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": c.road, "line-width": width([[13, 0.6], [16, 4], [19, 18]]) },
    },
    {
      id: "road-major",
      type: "line",
      source: SOURCE,
      "source-layer": "transportation",
      minzoom: 6,
      filter: roadClasses(["primary", "secondary", "trunk", "motorway"]),
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": c.major,
        "line-width": width([[6, 0.4], [9, 0.8], [13, 2.4], [16, 7], [19, 24]]),
        "line-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.5, 9, 1],
      },
    },

    // ---- 铁路：巡礼的主角，JR 式黑白相间 ----
    {
      id: "rail",
      type: "line",
      source: SOURCE,
      "source-layer": "transportation",
      minzoom: 7,
      filter: ["all", ["match", ["get", "class"], ["rail", "transit"], true, false], ["!=", ["get", "brunnel"], "tunnel"]],
      paint: {
        "line-color": c.rail,
        "line-width": width([[7, 0.5], [11, 1.2], [14, 2.6], [18, 5]]),
      },
    },
    {
      id: "rail-dash",
      type: "line",
      source: SOURCE,
      "source-layer": "transportation",
      minzoom: 12,
      filter: ["all", ["match", ["get", "class"], ["rail", "transit"], true, false], ["!=", ["get", "brunnel"], "tunnel"]],
      paint: {
        "line-color": c.land,
        "line-width": width([[12, 0.4], [14, 1.4], [18, 3]]),
        "line-dasharray": [3, 3],
      },
    },

    // ---- 文字 ----
    {
      id: "water-name",
      type: "symbol",
      source: SOURCE,
      "source-layer": "water_name",
      layout: {
        "text-field": NAME,
        "text-font": FONT,
        "text-size": ["match", ["get", "class"], "ocean", 15, "sea", 13, 11],
        "text-letter-spacing": 0.3,
        "text-max-width": 6,
      },
      paint: { "text-color": c.waterLabel },
    },
    {
      id: "road-name",
      type: "symbol",
      source: SOURCE,
      "source-layer": "transportation_name",
      minzoom: 15,
      filter: ["match", ["get", "class"], ["primary", "secondary", "tertiary", "minor"], true, false],
      layout: { "text-field": NAME, "text-font": FONT, "text-size": 10, "symbol-placement": "line" },
      paint: { "text-color": c.labelMuted, "text-halo-color": c.land, "text-halo-width": 1.5 },
    },
    {
      id: "station-dot",
      type: "circle",
      source: SOURCE,
      "source-layer": "poi",
      minzoom: 12,
      filter: ["all", ["==", ["get", "class"], "railway"], ["match", ["get", "subclass"], ["station", "halt"], true, false]],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 16, 5],
        "circle-color": c.land,
        "circle-stroke-color": c.rail,
        "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 12, 1.2, 16, 2],
      },
    },
    {
      id: "station-name",
      type: "symbol",
      source: SOURCE,
      "source-layer": "poi",
      minzoom: 13,
      filter: ["all", ["==", ["get", "class"], "railway"], ["match", ["get", "subclass"], ["station", "halt"], true, false]],
      layout: {
        "text-field": NAME,
        "text-font": FONT_BOLD,
        "text-size": 11,
        "text-offset": [0, 0.9],
        "text-anchor": "top",
        "text-optional": true,
      },
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 1.6 },
    },
    {
      id: "place-minor",
      type: "symbol",
      source: SOURCE,
      "source-layer": "place",
      minzoom: 11,
      filter: ["match", ["get", "class"], ["village", "suburb", "quarter"], true, false],
      layout: { "text-field": NAME, "text-font": FONT, "text-size": 11, "text-max-width": 6 },
      paint: { "text-color": c.labelMuted, "text-halo-color": c.land, "text-halo-width": 1.5 },
    },
    {
      id: "place-town",
      type: "symbol",
      source: SOURCE,
      "source-layer": "place",
      minzoom: 8,
      filter: ["==", ["get", "class"], "town"],
      layout: { "text-field": NAME, "text-font": FONT, "text-size": ["interpolate", ["linear"], ["zoom"], 8, 11, 14, 14] },
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 1.5 },
    },
    {
      id: "place-city",
      type: "symbol",
      source: SOURCE,
      "source-layer": "place",
      minzoom: 4,
      maxzoom: 15,
      filter: ["==", ["get", "class"], "city"],
      layout: {
        "text-field": NAME,
        "text-font": FONT_BOLD,
        "text-size": ["interpolate", ["linear"], ["zoom"], 4, ["case", ["<=", ["get", "rank"], 2], 13, 11], 10, 18],
        "text-letter-spacing": 0.08,
        "symbol-sort-key": ["get", "rank"],
      },
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 1.8 },
    },
    {
      id: "place-country",
      type: "symbol",
      source: SOURCE,
      "source-layer": "place",
      maxzoom: 7,
      filter: ["==", ["get", "class"], "country"],
      layout: {
        "text-field": ["coalesce", ["get", "name:zh"], ["get", "name"]],
        "text-font": FONT_BOLD,
        "text-size": ["interpolate", ["linear"], ["zoom"], 2, 12, 6, 18],
        "text-letter-spacing": 0.4,
        "text-transform": "uppercase",
      },
      paint: { "text-color": c.labelMuted, "text-halo-color": c.land, "text-halo-width": 1.5 },
    },
  ];

  return {
    version: 8,
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    // selected：是否选中了作品（其余地标淡化）；selectedColor：选中作品的主题色，由组件设置。
    // 默认值必须与主题无关，换主题时样式才能按 diff 更新，而不是整体重载
    state: { selected: { default: false }, selectedColor: { default: "#000000" } },
    sources: {
      [SOURCE]: { type: "vector", url: "https://tiles.openfreemap.org/planet" },
      // 全部地标：maplibre 在 worker 里抓取、解析并聚合，主线程不碰这 5 万个点
      points: { type: "geojson", data: "/data/points.geojson", cluster: true, clusterRadius: 44, clusterMaxZoom: 13 },
      // 选中作品的地标，焦点用 feature-state 标记
      selected: { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "p" },
    },
    layers: [...layers, ...overlayLayers(c)],
  };
}

const SELECTED: ExpressionSpecification = ["global-state", "selected"];
const FOCUS: ExpressionSpecification = ["boolean", ["feature-state", "focus"], false];

/** 地标、聚合与选中高亮。选中作品后其余地标退成淡淡的点，只留位置感 */
function overlayLayers(c: Palette): LayerSpecification[] {
  const dim = (normal: number, selected: number): ExpressionSpecification => ["case", SELECTED, selected, normal];
  return [
    {
      id: "cluster-halo",
      type: "circle",
      source: "points",
      filter: ["has", "point_count"],
      paint: { "circle-color": c.accent, "circle-opacity": dim(0.16, 0), "circle-radius": ["+", CLUSTER_RADIUS, 7] },
    },
    {
      id: "clusters",
      type: "circle",
      source: "points",
      filter: ["has", "point_count"],
      paint: {
        "circle-color": c.accent,
        "circle-radius": CLUSTER_RADIUS,
        "circle-opacity": dim(1, 0.12),
        "circle-stroke-color": c.land,
        "circle-stroke-width": 1.5,
        "circle-stroke-opacity": dim(1, 0),
      },
    },
    {
      id: "cluster-count",
      type: "symbol",
      source: "points",
      filter: ["has", "point_count"],
      layout: {
        "text-field": ["get", "point_count_abbreviated"],
        "text-font": FONT_BOLD,
        "text-size": 11,
        "text-allow-overlap": true,
      },
      paint: { "text-color": "#ffffff", "text-opacity": dim(1, 0) },
    },
    {
      id: "point",
      type: "circle",
      source: "points",
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": c.accent,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3.5, 16, 6],
        "circle-opacity": dim(1, 0.25),
        "circle-stroke-color": c.land,
        "circle-stroke-width": 1.5,
        "circle-stroke-opacity": dim(1, 0),
      },
    },
    {
      id: "selected-point",
      type: "circle",
      source: "selected",
      paint: {
        "circle-color": ["global-state", "selectedColor"],
        "circle-radius": ["case", FOCUS, 9, 6.5],
        "circle-stroke-color": ["case", FOCUS, c.focusRing, c.land],
        "circle-stroke-width": ["case", FOCUS, 3, 2],
      },
    },
    {
      id: "selected-label",
      type: "symbol",
      source: "selected",
      minzoom: 12,
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT_BOLD,
        "text-size": 12,
        "text-offset": [0, 1.1],
        "text-anchor": "top",
        "text-optional": true,
      },
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 1.8 },
    },
  ];
}
