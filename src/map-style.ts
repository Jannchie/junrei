// junrei 的地图：底图来自 @mapette/core（参照 Apple 地图的皮肤最早就是在这里做的，后来抽成了 mapette），
// 这里只有巡礼自己的数据源与叠加层：全部地标的聚合气泡与圆点、选中作品的高亮与名称、当前地标。
// 配色由 mapette 的 CSS 变量决定（src/theme.css 只做别名）。
import { clusterLayers, clusterSource, createBasemap, FONT, FONT_BOLD, pointLayer, UNCLUSTERED, type Palette, type StyleContext } from "@mapette/core";
import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";

/** 按线路配色的铁路（sync/rail.py 从 OSM 线路关系生成的 PMTiles，放在 R2）；底图的灰色铁路垫在下面，覆盖不到的地区照常显示 */
export const RAIL_TILES = "pmtiles://https://cdn.jannchie.com/junrei/rail/rail-v4.pmtiles";

/**
 * 气泡密度：radius 是合并半径（屏幕像素），越大气泡越少；maxZoom 以上不再聚合，全部显示成单个地标。
 * 运行时也能改：setClusterOptions(map, "points", { radius })
 */
export const CLUSTER = { radius: 72, maxZoom: 11 };

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
      // 全部地标：maplibre 在 worker 里抓取、解析并按缩放聚合，主线程不碰这 5 万个点。
      // 成人向地标（带 n 属性）默认隐藏，气泡要另外数一份不含它们的数量（visible）
      points: clusterSource("/data/points.geojson", { ...CLUSTER, properties: { visible: ["+", ["case", ["has", "n"], 0, 1]] } }),
      // 选中作品的地标，焦点用 feature-state 标记
      selected: { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "p" },
    },
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
 * 地标与选中高亮。缩小时相邻地标合成带数量的气泡，放大逐级拆开，点击气泡放大展开（PilgrimLayers 里的 ClusterExpand）。
 * 选中作品后，其余作品的气泡与地标直接隐藏（用过滤条件，隐藏后也点不到），只留当前作品的地标。
 */
function overlayLayers(c: Palette): LayerSpecification[] {
  const unselected: ExpressionSpecification = ["!", SELECTED];
  return [
    // 没被聚合的单个地标（任何缩放级别都显示）
    pointLayer({ source: "points", palette: c, fade: false, filter: ["all", UNCLUSTERED, unselected, SHOWN] }),
    // 聚合气泡：数量只算显示中的地标；全是成人向地标的气泡在开关打开前不画
    ...clusterLayers({
      source: "points",
      palette: c,
      count: ["case", ["global-state", "adult"], ["get", "point_count"], ["get", "visible"]],
      filter: ["all", unselected, ["any", ["global-state", "adult"], [">", ["get", "visible"], 0]]],
    }),
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
