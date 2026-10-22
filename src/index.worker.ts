// 作品索引的 Web Worker：下载并解析 points.geojson（约 6 MB）与 bangumi.json，
// 在这里做作品模糊搜索和视口统计，主线程只收结果，不会因为解析大 JSON 而卡顿。
import { fold } from "./fold";
import type { I18n } from "./i18n";

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
}
export type Bounds = { west: number; south: number; east: number; north: number };
export type Request =
  | { id: number; type: "search"; query: string; limit: number }
  | { id: number; type: "inView"; bounds: Bounds; limit: number };

type Raw = [number, string | null, string | null, string | null, string | null, number, string, I18n["name"] | null];

const bangumi: Promise<Entry[]> = fetch("/data/bangumi.json")
  .then((r) => r.json() as Promise<Raw[]>)
  .then((rows) =>
    rows.map(([id, cn, title, en, cover, pointCount, keys, names]) => ({
      id, cn, title, en, cover, pointCount, i18n: names ? { name: names } : null, keys: keys.split("|"),
    })),
  );

const points = fetch("/data/points.geojson")
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

const strip = ({ keys: _keys, ...b }: Entry): BangumiLite => b;

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

async function search(query: string, limit: number) {
  const q = fold(query);
  if (!q) return [];
  return (await bangumi)
    .map((b) => ({ b, s: Math.max(...b.keys.map((k) => score(k, q))) }))
    .filter((x) => x.s > 0)
    .sort((x, y) => y.s - x.s || y.b.pointCount - x.b.pointCount)
    .slice(0, limit)
    .map((x) => strip(x.b));
}

async function inView({ west, south, east, north }: Bounds, limit: number) {
  const [idx, all] = await Promise.all([points, bangumi]);
  const counts = new Map<number, number>();
  const wraps = west > east; // 跨 180° 经线
  for (let i = 0; i < idx.lat.length; i++) {
    const lat = idx.lat[i];
    const lng = idx.lng[i];
    if (lat < south || lat > north) continue;
    if (wraps ? lng < west && lng > east : lng < west || lng > east) continue;
    counts.set(idx.bangumi[i], (counts.get(idx.bangumi[i]) ?? 0) + 1);
  }
  const byId = new Map(all.map((b) => [b.id, b]));
  return [...counts]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .flatMap(([id, n]) => {
      const b = byId.get(id);
      return b ? [{ ...strip(b), inView: n }] : [];
    });
}

self.onmessage = async (e: MessageEvent<Request>) => {
  const req = e.data;
  const result = req.type === "search" ? await search(req.query, req.limit) : await inView(req.bounds, req.limit);
  self.postMessage({ id: req.id, result });
};
