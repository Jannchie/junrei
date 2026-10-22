// 浏览器端的作品索引：public/data/bangumi.json（作品元数据与搜索键）+ points.geojson（按视口统计作品）。
// 两份文件都只在需要时加载一次；points.geojson 页面已预加载，通常直接命中缓存。
import { fold } from "./fold";

export interface BangumiLite {
  id: number;
  cn: string | null;
  title: string | null;
  en: string | null;
  cover: string | null;
  pointCount: number;
  keys: string[];
}

type Raw = [number, string | null, string | null, string | null, string | null, number, string];

let bangumiPromise: Promise<BangumiLite[]> | null = null;
export function loadBangumi() {
  bangumiPromise ??= fetch("/data/bangumi.json")
    .then((r) => r.json() as Promise<Raw[]>)
    .then((rows) => rows.map(([id, cn, title, en, cover, pointCount, keys]) => ({ id, cn, title, en, cover, pointCount, keys: keys.split("|") })));
  return bangumiPromise;
}

/**
 * 模糊匹配打分：连续命中（子串）最好，开头命中加分；否则按顺序命中全部字符也算，空隙越大分越低。
 * 不命中返回 0。
 */
function score(key: string, q: string): number {
  const at = key.indexOf(q);
  if (at >= 0) return 1000 - at * 2 - (key.length - q.length) * 0.5 + (at === 0 ? 200 : 0);
  let gaps = 0;
  let last = -1;
  for (const c of q) {
    const j = key.indexOf(c, last + 1);
    if (j < 0) return 0;
    if (last >= 0) gaps += j - last - 1;
    last = j;
  }
  // 空隙过大时多半是巧合，不算命中
  return gaps > q.length * 3 ? 0 : 500 - gaps * 10 - (key.length - q.length) * 0.5;
}

/** 作品搜索：全语种（各语言名称、罗马音、城市都在搜索键里）+ 模糊 */
export async function searchBangumi(query: string, limit = 20) {
  const q = fold(query);
  if (!q) return [];
  const all = await loadBangumi();
  return all
    .map((b) => ({ b, s: Math.max(...b.keys.map((k) => score(k, q))) }))
    .filter((x) => x.s > 0)
    .sort((x, y) => y.s - x.s || y.b.pointCount - x.b.pointCount)
    .slice(0, limit)
    .map((x) => x.b);
}

// ---- 按视口统计作品 ----

interface PointIndex {
  lng: Float32Array;
  lat: Float32Array;
  bangumi: Int32Array;
}

let pointsPromise: Promise<PointIndex> | null = null;
function loadPoints() {
  pointsPromise ??= fetch("/data/points.geojson")
    .then((r) => r.json() as Promise<{ features: { geometry: { coordinates: [number, number] }; properties: { b: number } }[] }>)
    .then(({ features }) => {
      const n = features.length;
      const idx = { lng: new Float32Array(n), lat: new Float32Array(n), bangumi: new Int32Array(n) };
      features.forEach((f, i) => {
        idx.lng[i] = f.geometry.coordinates[0];
        idx.lat[i] = f.geometry.coordinates[1];
        idx.bangumi[i] = f.properties.b;
      });
      return idx;
    });
  return pointsPromise;
}

/** 视口内有地标的作品，按视口内地标数排序 */
export async function bangumiInView(bounds: { west: number; south: number; east: number; north: number }, limit = 24) {
  const [points, all] = await Promise.all([loadPoints(), loadBangumi()]);
  const counts = new Map<number, number>();
  const { west, south, east, north } = bounds;
  const wraps = west > east; // 跨 180° 经线
  for (let i = 0; i < points.lat.length; i++) {
    const lat = points.lat[i];
    const lng = points.lng[i];
    if (lat < south || lat > north) continue;
    if (wraps ? lng < west && lng > east : lng < west || lng > east) continue;
    counts.set(points.bangumi[i], (counts.get(points.bangumi[i]) ?? 0) + 1);
  }
  const byId = new Map(all.map((b) => [b.id, b]));
  return [...counts]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .flatMap(([id, inView]) => {
      const b = byId.get(id);
      return b ? [{ ...b, inView }] : [];
    });
}
