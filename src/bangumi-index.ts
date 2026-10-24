// 主线程这边的作品索引接口：实际工作都在 index.worker.ts 里做，这里只负责收发消息。
import type { BangumiLite, Bounds, Request } from "./index.worker";
import type { Card } from "./series";

export type { BangumiLite };

let worker: Worker | null = null;
let nextId = 0;
const pending = new Map<number, (result: unknown) => void>();

type WithoutId<T> = T extends unknown ? Omit<T, "id"> : never;

function call<T>(req: WithoutId<Request>): Promise<T> {
  worker ??= (() => {
    const w = new Worker(new URL("./index.worker.ts", import.meta.url), { type: "module" });
    w.onmessage = (e: MessageEvent<{ id: number; result: unknown }>) => {
      pending.get(e.data.id)?.(e.data.result);
      pending.delete(e.data.id);
    };
    return w;
  })();
  const id = ++nextId;
  return new Promise<T>((resolve) => {
    pending.set(id, resolve as (r: unknown) => void);
    worker!.postMessage({ ...req, id });
  });
}

/** 作品搜索：全语种（各语言名称、罗马音、城市都在搜索键里）+ 模糊 */
export const searchBangumi = (query: string, adult: boolean, limit = 20) => call<Card[]>({ type: "search", query, limit, adult });

/** 视口内有地标的系列（不在系列里的作品单独算），按视口内地标数排序 */
export const bangumiInView = (bounds: Bounds, adult: boolean, limit = 48) =>
  call<(Card & { inView: number })[]>({ type: "inView", bounds, limit, adult });

/** 每部作品的地标数（[作品 id, 数量]）→ 按系列合并的卡片，按数量排序（地图气泡菜单用，不发网络请求） */
export const groupBangumi = (counts: [number, number][], adult: boolean) =>
  call<(Card & { inView: number })[]>({ type: "group", counts, adult });
