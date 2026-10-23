// 图片加载失败（网络抖动、图床短暂拒绝并发请求）时退避重试：1、2、4、8 秒后各试一次。
// 等待期间换成透明空图，显示占位底色而不是浏览器的破图边框；仍失败就加上 img-failed（占位上显示「图片不可用」）
const RETRIES = 4;
const BLANK = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

/** 作为 <img> 的 error 处理函数；onGiveUp 在重试用尽时调用（例如地图上的照片标点直接隐藏） */
export function retryImage(img: HTMLImageElement, onGiveUp?: () => void): void {
  if (img.src === BLANK) return;
  const tries = Number(img.dataset.tries ?? 0);
  const url = new URL(img.dataset.src ?? img.src);
  url.searchParams.delete("retry");
  img.dataset.src = url.href;
  img.src = BLANK;
  if (tries >= RETRIES) {
    img.classList.add("img-failed");
    onGiveUp?.();
    return;
  }
  img.dataset.tries = String(tries + 1);
  url.searchParams.set("retry", String(tries + 1));
  setTimeout(() => (img.src = url.href), 1000 * 2 ** tries);
}

/** 服务端渲染的图片在页面接管前就开始加载，那时失败的错误事件没人接住；接管后补一次重试 */
export function recoverImages(root: ParentNode = document): void {
  for (const img of root.querySelectorAll<HTMLImageElement>("img[src]")) {
    if (img.complete && img.naturalWidth === 0 && !img.dataset.tries) retryImage(img);
  }
}
