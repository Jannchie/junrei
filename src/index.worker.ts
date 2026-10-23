// 作品索引的 Web Worker：下载并解析 points.geojson（约 6 MB）与 bangumi.json，
// 在这里做作品模糊搜索和视口统计，主线程只收结果，不会因为解析大 JSON 而卡顿。
import { fold } from "./fold";
import type { I18n } from "./i18n";
import type { Card } from "./series";

export interface BangumiLite {
  id: number;
  cn: string | null;
  title: string | null;
  en: string | null;
  cover: string | null;
  pointCount: number;
  i18n: I18n | null;
}
interface Entry extends BangumiLite {
  keys: string[];
  series: number | null;
  nsfw: boolean;
}
export type Bounds = { west: number; south: number; east: number; north: number };
export type Request =
  | { id: number; type: "search"; query: string; limit: number; adult: boolean }
  | { id: number; type: "inView"; bounds: Bounds; limit: number; adult: boolean };

type Raw = [number, string | null, string | null, string | null, string | null, number, string, I18n["name"] | null, number | null, 0 | 1];
type RawSeries = [string | null, string | null, string | null, I18n["name"] | null, number, number, string | null];

// 作品（有地标的）与系列汇总，格式见 sync/export.py
const index = fetch("/data/bangumi.json")
  .then((r) => r.json() as Promise<{ works: Raw[]; series: Record<string, RawSeries> }>)
  .then(({ works, series }) => ({
    works: works.map(([id, cn, title, en, cover, pointCount, keys, names, s, nsfw]): Entry => ({
      id, cn, title, en, cover, pointCount, i18n: names ? { name: names } : null, keys: keys.split("|"), series: s, nsfw: !!nsfw,
    })),
    series: new Map(Object.entries(series).map(([id, s]) => [Number(id), s])),
  }))
  .then((x) => ({ ...x, byId: new Map(x.works.map((b) => [b.id, b])) }));
type Index = Awaited<typeof index>;

/** 作品 → 卡片：在系列里的显示系列名与系列地标总数，否则显示自己 */
function card(b: Entry, { series }: Index): Card {
  const s = b.series != null ? series.get(b.series) : undefined;
  if (!s) return { id: b.id, series: false, cn: b.cn, title: b.title, en: b.en, i18n: b.i18n, cover: b.cover, pointCount: b.pointCount, works: 1 };
  const [cn, title, en, names, pointCount, works, cover] = s;
  return { id: b.series!, series: works > 1, cn, title, en, i18n: names ? { name: names } : null, cover, pointCount, works };
}

// 地标坐标只在第一次算「视野里的作品」时才取：那时地图多半已经把同一个文件放进浏览器缓存，不会再下载一遍
let points: Promise<{ lng: Float32Array; lat: Float32Array; bangumi: Int32Array }> | undefined;
const loadPoints = () => (points ??= fetch("/data/points.geojson")
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
  }));


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

// 成人向作品默认不出现在搜索和视口列表里（见 src/adult.ts）
async function search(query: string, limit: number, adult: boolean) {
  const q = fold(query);
  if (!q) return [];
  const ix = await index;
  const hits = ix.works
    .filter((b) => adult || !b.nsfw)
    .map((b) => ({ b, s: Math.max(...b.keys.map((k) => score(k, q))) }))
    .filter((x) => x.s > 0)
    .sort((x, y) => y.s - x.s || y.b.pointCount - x.b.pointCount);
  // 同一系列只留得分最高的那部，显示成系列
  const seen = new Set<number>();
  const out: Card[] = [];
  for (const { b } of hits) {
    const c = card(b, ix);
    if (seen.has(c.id)) continue;
    seen.add(c.id);
    out.push(c);
    if (out.length >= limit) break;
  }
  return out;
}

async function inView({ west, south, east, north }: Bounds, limit: number, adult: boolean) {
  const [idx, ix] = await Promise.all([loadPoints(), index]);
  const counts = new Map<number, number>();
  const wraps = west > east; // 跨 180° 经线
  for (let i = 0; i < idx.lat.length; i++) {
    const lat = idx.lat[i];
    const lng = idx.lng[i];
    if (lat < south || lat > north) continue;
    if (wraps ? lng < west && lng > east : lng < west || lng > east) continue;
    counts.set(idx.bangumi[i], (counts.get(idx.bangumi[i]) ?? 0) + 1);
  }
  // 按系列合并：系列在视口里的地标数是各部之和
  const merged = new Map<number, Card & { inView: number }>();
  for (const [id, n] of counts) {
    const b = ix.byId.get(id);
    if (!b || (b.nsfw && !adult)) continue;
    const c = card(b, ix);
    const m = merged.get(c.id);
    if (m) m.inView += n;
    else merged.set(c.id, { ...c, inView: n });
  }
  return [...merged.values()].sort((a, b) => b.inView - a.inView).slice(0, limit);
}

self.onmessage = async (e: MessageEvent<Request>) => {
  const req = e.data;
  const result = req.type === "search" ? await search(req.query, req.limit, req.adult) : await inView(req.bounds, req.limit, req.adult);
  self.postMessage({ id: req.id, result });
};
