// 作品详情：面板和地图截图气泡共用同一次请求
import { fetch } from "void/client";
import type { BangumiDetail } from "./server/bangumi";

const cache = new Map<number, Promise<BangumiDetail>>();

export function fetchDetail(id: number): Promise<BangumiDetail> {
  let p = cache.get(id);
  if (!p) {
    p = fetch("/v1/bangumi/:id", { params: { id: String(id) } }) as Promise<BangumiDetail>;
    p.catch(() => cache.delete(id)); // 失败的不缓存，下次重试
    cache.set(id, p);
  }
  return p;
}
