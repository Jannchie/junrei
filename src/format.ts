/** 纯数字集数显示为 EP 3，其他（如「特典」）原样显示 */
export function formatEpisode(ep: string): string {
  return /^\d+$/.test(ep) ? `EP ${ep}` : ep;
}

/** 秒 → 12:34 */
export function formatTime(s: number): string {
  if (!Number.isFinite(s)) return "";
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/** Unix 秒 → 2026-10-24（UTC，各语言一致） */
export function formatDate(t: number): string {
  return new Date(t * 1000).toISOString().slice(0, 10);
}

/** Anitabi 的图片按 plan 参数缩放：h160 缩略图、h360 大图；原图请勿大量使用。其他来源原样返回 */
export function imageUrl(url: string, plan: "h160" | "h360" = "h160"): string {
  return url.startsWith("https://image.anitabi.cn/") ? `${url}?plan=${plan}` : url;
}
