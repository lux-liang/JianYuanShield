/* 鉴源盾 Service Worker — 最简静态壳缓存 + 离线兜底
   策略：Cache-First（命中缓存直接返回），API 请求直接透传（network-only）。
   首屏静态资源离线可用；后端 API 必须联网。
*/
const CACHE_NAME = "jys-shell-v1";
const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./app.js",
  "./styles.css",
  "./manifest.json",
];

/* 安装：预缓存静态壳 */
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

/* 激活：清理旧版本缓存 */
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

/* 请求拦截：API 请求 network-only；其余 cache-first，miss 时 fetch 并回写 */
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  /* API 端点直接走网络，不缓存 */
  if (url.pathname.startsWith("/api/")) {
    return; /* 浏览器默认 fetch */
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        /* 只缓存同源成功响应 */
        if (
          response.ok &&
          response.type === "basic" &&
          url.origin === self.location.origin
        ) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() =>
        /* 网络彻底不通时返回离线兜底页（index.html） */
        caches.match("./index.html")
      );
    })
  );
});
