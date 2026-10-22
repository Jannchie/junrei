// junrei 的地图皮肤，参照 Apple 地图：素净的底、明亮的水与青绿、水深渐变与淡山影、白色道路、暖黄高速、细灰铁路。
// 矢量瓦片来自 OpenFreeMap（OpenMapTiles schema），只保留巡礼用得上的要素：
// 水、绿地、市街地、道路、铁路与车站、地名。配色在 src/theme.css。
// 刻意不画任何政治要素：没有国界、省界、国名，也没有存在命名争议的海域名称；
// 地名按界面语言显示（与 Apple 地图一致），避免在争议地区显示实际管辖方的文字。
import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";
import type { Locale } from "./i18n";

const PALETTE_KEYS = [
  "land", "urban", "wood", "grass", "park", "sand", "water", "building", "buildingLine", "road", "roadCasing",
  "major", "majorCasing", "motorway", "motorwayCasing", "rail", "label", "labelMuted", "waterLabel",
  "focusRing", "space", "horizon", "depthShelf", "depthMid", "depthDeep", "hillshadeShadow", "hillshadeHighlight", "heat1", "heat2", "heat3", "heat4", "heat5",
] as const;

export type Palette = Record<(typeof PALETTE_KEYS)[number] | "accent", string>;

/**
 * 配色只在 src/theme.css 里定义一份，这里按当前亮暗模式读出来。
 * 变量里是 light-dark(…)，要挂到一个元素的 color 上才会求值成具体的 rgb()。
 */
export function readPalette(): Palette {
  const probe = document.createElement("span");
  probe.style.display = "none";
  document.body.appendChild(probe);
  const read = (name: string) => {
    probe.style.color = `var(${name})`;
    return getComputedStyle(probe).color;
  };
  const palette = { accent: read("--accent") } as Palette;
  for (const key of PALETTE_KEYS) palette[key] = read(`--map-${key.replace(/[A-Z]|\d/g, (m) => `-${m.toLowerCase()}`)}`);
  probe.remove();
  return palette;
}

/** 中日文字由浏览器本地字体绘制（与 Apple 地图一致用无衬线体），拉丁字母走 glyph 服务的 Noto Sans */
export const CJK_FONT_FAMILY = "'Hiragino Sans', 'PingFang SC', 'Yu Gothic', 'YuGothic', 'Noto Sans JP', 'Noto Sans CJK JP', sans-serif";

const SOURCE = "openmaptiles";
/** AWS 开放地形瓦片（Terrarium 编码），含陆地高程与海底水深；只取到 z10，再放大就复用低层级瓦片 */
const DEM = "terrain";
const FONT = ["Noto Sans Regular"];
const FONT_BOLD = ["Noto Sans Bold"];
const FONT_ITALIC = ["Noto Sans Italic"];
/** 热力图淡出、单个地标淡入的缩放区间 */
export const HEAT_FADE: [number, number] = [9, 11];

/** rgb() 颜色 + 透明度 → rgba()，热力图的色带要在同一个颜色上渐变透明度 */
function alpha(color: string, a: number) {
  const [r, g, b] = color.match(/[\d.]+/g)!.map(Number);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}
const NAME_FIELDS: Record<Locale, string[]> = {
  "zh-Hans": ["name:zh-Hans", "name:zh"],
  "zh-Hant": ["name:zh-Hant", "name:zh"],
  ja: ["name:ja"],
  en: ["name:en", "name:latin"],
};

/** 线宽随缩放指数增长 */
const width = (pairs: [number, number][]): ExpressionSpecification =>
  ["interpolate", ["exponential", 1.6], ["zoom"], ...pairs.flat()] as ExpressionSpecification;

export function createStyle(c: Palette, locale: Locale): StyleSpecification {
  const NAME: ExpressionSpecification = ["coalesce", ...NAME_FIELDS[locale].map((f): ExpressionSpecification => ["get", f]), ["get", "name"]];
  const roadClasses = (classes: string[]): ExpressionSpecification => [
    "all",
    ["match", ["get", "class"], classes, true, false],
    ["!=", ["get", "brunnel"], "tunnel"],
  ];
  const railClasses = roadClasses(["rail", "transit"]);
  const line = (id: string, minzoom: number, filter: ExpressionSpecification, color: string, w: [number, number][]): LayerSpecification => ({
    id,
    type: "line",
    source: SOURCE,
    "source-layer": "transportation",
    minzoom,
    filter,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": color, "line-width": width(w) },
  });

  const layers: LayerSpecification[] = [
    { id: "land", type: "background", paint: { "background-color": c.land } },

    // ---- 地表 ----
    {
      id: "landcover",
      type: "fill",
      source: SOURCE,
      "source-layer": "landcover",
      filter: ["match", ["get", "class"], ["wood", "grass", "farmland", "wetland", "sand"], true, false],
      paint: {
        "fill-color": ["match", ["get", "class"], "wood", c.wood, "sand", c.sand, c.grass],
        "fill-opacity": ["interpolate", ["linear"], ["zoom"], 5, 0.6, 12, 1],
      },
    },
    {
      id: "urban",
      type: "fill",
      source: SOURCE,
      "source-layer": "landuse",
      minzoom: 9,
      filter: ["match", ["get", "class"], ["residential", "commercial", "industrial", "retail"], true, false],
      paint: { "fill-color": c.urban },
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
    // 水深：近岸一段保持透明，避免低分辨率高程把海岸线附近的陆地染蓝；放大到城市级别后淡出
    {
      id: "bathymetry",
      type: "color-relief",
      source: DEM,
      maxzoom: 10,
      paint: {
        "color-relief-color": [
          "interpolate", ["linear"], ["elevation"],
          -8000, c.depthDeep,
          -3000, c.depthMid,
          -400, c.depthShelf,
          -60, "rgba(0, 0, 0, 0)",
        ],
        "color-relief-opacity": ["interpolate", ["linear"], ["zoom"], 7, 1, 9.5, 0],
      },
    },
    {
      id: "hillshade",
      type: "hillshade",
      source: DEM,
      maxzoom: 14,
      paint: {
        "hillshade-shadow-color": c.hillshadeShadow,
        "hillshade-highlight-color": c.hillshadeHighlight,
        "hillshade-accent-color": "rgba(0, 0, 0, 0)",
        "hillshade-exaggeration": 0.35,
      },
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


    // ---- 道路：白色加淡描边，高速暖黄 ----
    line("road-minor-casing", 13, roadClasses(["minor", "service"]), c.roadCasing, [[13, 1.5], [16, 6], [19, 22]]),
    line("road-major-casing", 9, roadClasses(["primary", "secondary", "tertiary"]), c.majorCasing, [[9, 1.2], [13, 3.5], [16, 9], [19, 28]]),
    line("road-motorway-casing", 7, roadClasses(["motorway", "trunk"]), c.motorwayCasing, [[7, 1.4], [10, 2.6], [13, 4.5], [16, 11], [19, 32]]),
    line("road-minor", 13, roadClasses(["minor", "service"]), c.road, [[13, 0.6], [16, 4], [19, 18]]),
    line("road-major", 8, roadClasses(["primary", "secondary", "tertiary"]), c.major, [[8, 0.5], [10, 1], [13, 2.4], [16, 7], [19, 24]]),
    line("road-motorway", 5, roadClasses(["motorway", "trunk"]), c.motorway, [[5, 0.6], [7, 1], [10, 1.8], [13, 3.2], [16, 9], [19, 28]]),

    // ---- 铁路：细灰线，车站带圆点 ----
    line("rail", 7, railClasses, c.rail, [[7, 0.4], [11, 0.9], [14, 1.6], [18, 3]]),

    // ---- 文字 ----
    {
      id: "water-name",
      type: "symbol",
      source: SOURCE,
      "source-layer": "water_name",
      filter: ["!", ["match", ["get", "class"], ["ocean", "sea"], true, false]],
      layout: {
        "text-field": NAME,
        "text-font": FONT_ITALIC,
        "text-size": 11,
        "text-letter-spacing": 0.15,
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
      paint: { "text-color": c.labelMuted, "text-halo-color": c.land, "text-halo-width": 1.2 },
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
        "circle-color": c.road,
        "circle-stroke-color": c.labelMuted,
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
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 1.4 },
    },
    {
      id: "place-minor",
      type: "symbol",
      source: SOURCE,
      "source-layer": "place",
      minzoom: 11,
      filter: ["match", ["get", "class"], ["village", "suburb", "quarter"], true, false],
      layout: { "text-field": NAME, "text-font": FONT, "text-size": 11, "text-max-width": 6 },
      paint: { "text-color": c.labelMuted, "text-halo-color": c.land, "text-halo-width": 1.2 },
    },
    {
      id: "place-town",
      type: "symbol",
      source: SOURCE,
      "source-layer": "place",
      minzoom: 8,
      filter: ["==", ["get", "class"], "town"],
      layout: { "text-field": NAME, "text-font": FONT, "text-size": ["interpolate", ["linear"], ["zoom"], 8, 11, 14, 14] },
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 1.2 },
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
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 1.4 },
    },
  ];

  return {
    version: 8,
    // 切换外观、语言时新样式一次到位，不做颜色渐变
    transition: { duration: 0, delay: 0 },
    projection: { type: "globe" },
    // 缩到最小是地球：球外是「太空」底色，边缘一圈大气光
    sky: {
      "sky-color": c.space,
      "horizon-color": c.horizon,
      "sky-horizon-blend": 0.6,
      "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 5, 1, 7, 0],
    },
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    // selected：是否选中了作品（其余地标淡化）；selectedColor：选中作品的主题色，由组件设置。
    // 默认值必须与主题无关，换主题时样式才能按 diff 更新，而不是整体重载
    state: { selected: { default: false }, selectedColor: { default: "#000000" }, focus: { default: "" } },
    sources: {
      [SOURCE]: { type: "vector", url: "https://tiles.openfreemap.org/planet" },
      [DEM]: {
        type: "raster-dem",
        tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
        encoding: "terrarium",
        tileSize: 256,
        maxzoom: 10,
      },
      // 全部地标：maplibre 在 worker 里抓取、解析并聚合，主线程不碰这 5 万个点
      points: { type: "geojson", data: "/data/points.geojson" },
      // 选中作品的地标，焦点用 feature-state 标记
      selected: { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "p" },
    },
    // 热力图插在第一个文字图层之前，地名浮在光晕上面
    layers: [
      ...layers.filter((l) => l.type !== "symbol"),
      heatLayer(c),
      ...layers.filter((l) => l.type === "symbol"),
      ...overlayLayers(c),
    ],
  };
}

const SELECTED: ExpressionSpecification = ["global-state", "selected"];
const FOCUS: ExpressionSpecification = ["boolean", ["feature-state", "focus"], false];
/** 过滤器里不能用 feature-state，选中地标的专属图层用全局状态 focus（地标 id）筛选 */
const IS_FOCUS: ExpressionSpecification = ["==", ["get", "p"], ["global-state", "focus"]];

/**
 * 缩小时的热度晕染：极低密度处透明，按密度由淡紫、品红、珊瑚橙渐变到暖金，最密集处最亮。
 * 放大到 HEAT_FADE 区间淡出，由可点击的单个地标接替。选中作品后隐藏。
 */
function heatLayer(c: Palette): LayerSpecification {
  const [fadeFrom, fadeTo] = HEAT_FADE;
  return {
    id: "heat",
    type: "heatmap",
    source: "points",
    maxzoom: fadeTo + 0.5,
    filter: ["!", SELECTED],
    paint: {
      "heatmap-weight": 1,
      // 半径偏小，相邻城市不会连成一片
      "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.02, 4, 0.04, 6, 0.08, 8, 0.18, fadeTo, 0.5],
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 3, 4, 6, 6, 9, 8, 14, fadeTo, 24],
      // 节点按指数间隔分布，相当于对密度取对数：东京上万个点、小城几十个点也能分出层次，而不是只剩「有/没有」
      "heatmap-color": [
        "interpolate", ["linear"], ["heatmap-density"],
        0, alpha(c.heat1, 0),
        0.015, alpha(c.heat1, 0),
        0.04, alpha(c.heat1, 0.18),
        0.1, alpha(c.heat2, 0.3),
        0.22, alpha(c.heat3, 0.42),
        0.45, alpha(c.heat4, 0.55),
        1, alpha(c.heat5, 0.68),
      ],
      "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], fadeFrom, 1, fadeTo, 0],
    },
  };
}

/**
 * 地标与选中高亮。缩小时是柔和的热度晕染（不显示数字），放大到 HEAT_FADE 区间渐变为可点击的单个地标。
 * 选中作品后，其余作品的热度与地标直接隐藏（用过滤条件，隐藏后也点不到），只留当前作品的地标。
 */
function overlayLayers(c: Palette): LayerSpecification[] {
  const unselected: ExpressionSpecification = ["!", SELECTED];
  const [fadeFrom, fadeTo] = HEAT_FADE;
  return [
    {
      id: "point",
      type: "circle",
      source: "points",
      minzoom: fadeFrom - 0.5,
      filter: unselected,
      paint: {
        "circle-color": c.accent,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], fadeFrom, 3, 12, 5, 16, 8, 18, 10],
        "circle-opacity": ["interpolate", ["linear"], ["zoom"], fadeFrom, 0, fadeTo, 1],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], fadeFrom, 1, 16, 2.5],
        "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], fadeFrom, 0, fadeTo, 1],
      },
    },
    {
      id: "selected-point",
      type: "circle",
      source: "selected",
      paint: {
        "circle-color": ["global-state", "selectedColor"],
        // zoom 只能出现在最外层的 interpolate 里，焦点与否放进每一档
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, ["case", FOCUS, 8.5, 4], 16, ["case", FOCUS, 11, 8.5], 18, ["case", FOCUS, 13, 10]],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["case", FOCUS, 3, 2],
      },
    },
    {
      id: "selected-label",
      type: "symbol",
      source: "selected",
      minzoom: 14,
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT,
        "text-size": ["interpolate", ["linear"], ["zoom"], 14, 11, 17, 13],
        "text-offset": [0, 1.2],
        "text-anchor": "top",
        "text-max-width": 8,
        "text-padding": 4,
        "text-optional": true,
      },
      // 有选中地标时，其他地标的名字淡一些，把注意力留给选中的那个
      paint: {
        "text-color": c.label,
        "text-halo-color": c.land,
        "text-halo-width": 1.6,
        "text-opacity": ["case", ["==", ["global-state", "focus"], ""], 1, 0.55],
      },
    },
    // ---- 当前选中的地标：单独画在最上层，大一圈、带光晕，名字加粗且不会被避让掉 ----
    {
      id: "focus-halo",
      type: "circle",
      source: "selected",
      filter: IS_FOCUS,
      paint: {
        "circle-color": ["global-state", "selectedColor"],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 18, 16, 26],
        "circle-opacity": 0.32,
        "circle-blur": 0.25,
      },
    },
    {
      id: "focus-point",
      type: "circle",
      source: "selected",
      filter: IS_FOCUS,
      paint: {
        "circle-color": ["global-state", "selectedColor"],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 9, 16, 13, 18, 15],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 4,
      },
    },
    {
      id: "focus-label",
      type: "symbol",
      source: "selected",
      filter: IS_FOCUS,
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT_BOLD,
        "text-size": 14,
        "text-offset": [0, 1.5],
        "text-anchor": "top",
        "text-max-width": 10,
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: { "text-color": c.label, "text-halo-color": c.land, "text-halo-width": 2 },
    },
  ];
}
