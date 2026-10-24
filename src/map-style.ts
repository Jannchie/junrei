// junrei 的地图：底图来自 @mapette/core（参照 Apple 地图的皮肤最早就是在这里做的，后来抽成了 mapette），
// 这里只有巡礼自己的数据源与叠加层：全部地标的热力图与圆点、选中作品的高亮与名称、当前地标。
// 配色由 mapette 的 CSS 变量决定（src/theme.css 只做别名）。
import { alpha, createBasemap, FONT, FONT_BOLD, HEAT_FADE, type Palette, type StyleContext } from "@mapette/core";
import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";

/** 按线路配色的铁路（sync/rail.py 从 OSM 线路关系生成的 PMTiles，放在 R2）；底图的灰色铁路垫在下面，覆盖不到的地区照常显示 */
export const RAIL_TILES = "pmtiles://https://cdn.jannchie.com/junrei/rail/rail-v4.pmtiles";

/** 换主题、换语言时原样保留的数据源：5 万个点的 points 不要重新加载、重新聚合 */
export const KEEP_SOURCES = ["points", "selected"];

export function createStyle({ palette: c, locale }: StyleContext): StyleSpecification {
  return createBasemap({
    palette: c,
    locale,
    rail: RAIL_TILES,
    // selected：是否选中了作品（其余地标淡化）；selectedColor：选中作品的主题色，由组件设置。
    // 默认值必须与主题无关，换主题时样式才能按 diff 更新，而不是整体重载
    state: { selected: { default: false }, selectedColor: { default: "#000000" }, focus: { default: "" }, adult: { default: false } },
    sources: {
      // 全部地标：maplibre 在 worker 里抓取、解析并聚合，主线程不碰这 5 万个点
      points: { type: "geojson", data: "/data/points.geojson" },
      // 选中作品的地标，焦点用 feature-state 标记
      selected: { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "p" },
    },
    // 热力图插在文字图层之前，地名浮在光晕上面
    belowLabels: [heatLayer(c)],
    overlays: overlayLayers(c),
  });
}

const SELECTED: ExpressionSpecification = ["global-state", "selected"];
const FOCUS: ExpressionSpecification = ["boolean", ["feature-state", "focus"], false];
/** 过滤器里不能用 feature-state，选中地标的专属图层用全局状态 focus（地标 id）筛选 */
const IS_FOCUS: ExpressionSpecification = ["==", ["get", "p"], ["global-state", "focus"]];
/** 成人向作品的地标带 n 属性（sync/export.py），全局状态 adult 打开前不画、也点不到 */
const SHOWN: ExpressionSpecification = ["any", ["global-state", "adult"], ["!", ["has", "n"]]];

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
    filter: ["all", ["!", SELECTED], SHOWN],
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
      filter: ["all", unselected, SHOWN],
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
      filter: ["!", IS_FOCUS], // 选中的地标由 focus-label 单独画，这里不再重复
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
    // ---- 当前选中的地标：单独画在最上层，稍大一圈，名字加粗且不会被避让掉 ----
    {
      id: "focus-point",
      type: "circle",
      source: "selected",
      filter: IS_FOCUS,
      paint: {
        "circle-color": ["global-state", "selectedColor"],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 7, 16, 10, 18, 12],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 3,
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
