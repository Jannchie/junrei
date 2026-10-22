// junrei 的 Service Worker：让应用可安装、弱网可用，并缓存去过的地方（巡礼现场常常信号不好）。
// 策略：页面先走网络、失败回退缓存；带哈希的静态资源只取缓存；数据与地图瓦片先给缓存再后台更新。
const VERSION = "v2";
const PAGES = `pages-${VERSION}`;
const STATIC = `static-${VERSION}`;
const DATA = `data-${VERSION}`;
// 第三方资源按类型分池、各自设条目上限，互不挤占（截图再多也不会把地图瓦片挤出去）
const POOLS = [
  // 矢量瓦片、样式、字体：每张几十 KB，看过的区域尽量留住
  { name: `tiles-${VERSION}`, limit: 2000, test: (u) => /(^|\.)openfreemap\.org$/.test(u.hostname) },
  // 地形瓦片：每张约 100 KB，只在小比例尺用到，留少一些
  { name: `terrain-${VERSION}`, limit: 500, test: (u) => u.hostname.includes("elevation-tiles-prod") },
  // 截图与封面缩略图
  { name: `images-${VERSION}`, limit: 1000, test: (u) => /(^|\.)anitabi\.cn$/.test(u.hostname) },
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(PAGES).then((c) => c.addAll(["/", "/manifest.webmanifest"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  const keep = [PAGES, STATIC, DATA, ...POOLS.map((p) => p.name)];
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !keep.includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (req.mode === "navigate") return event.respondWith(networkFirst(req, PAGES));
  if (url.origin === location.origin) {
    if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) return event.respondWith(cacheFirst(req, STATIC));
    if (url.pathname.startsWith("/data/")) return event.respondWith(staleWhileRevalidate(req, DATA));
    if (url.pathname.startsWith("/v1/")) return event.respondWith(networkFirst(req, DATA));
    return;
  }
  const pool = POOLS.find((p) => p.test(url));
  if (pool) return event.respondWith(staleWhileRevalidate(req, pool.name, pool.limit));
});

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = (await cache.match(req)) ?? (req.mode === "navigate" ? await cache.match("/") : undefined);
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

async function staleWhileRevalidate(req, cacheName, limit) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  const update = fetch(req)
    .then(async (res) => {
      // 跨域图片可能是 opaque 响应（status 0），也照样缓存
      if (res.ok || res.type === "opaque") {
        await cache.put(req, res.clone());
        if (limit) trim(cache, limit);
      }
      return res;
    })
    .catch(() => hit);
  return hit ?? update;
}

// 超出上限时删掉最早放进去的条目（Cache API 的 keys() 按插入顺序返回）
async function trim(cache, limit) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - limit; i++) await cache.delete(keys[i]);
}
