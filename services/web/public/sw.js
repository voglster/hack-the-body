/* Hack the Body service worker.
 *
 * Tiny on purpose: cache the bundled app shell so the page loads instantly on
 * repeat visits, but never cache API responses (those must always be fresh).
 * On every deploy the cache name (CACHE) gets a new version via Vite's
 * content-hashed bundle file names, which naturally invalidates the old shell
 * the first time a new index.html requests new assets.
 */

const CACHE = "htb-shell-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg", "/config.js"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls — they must always go to the network.
  if (
    url.pathname.startsWith("/auth") ||
    url.pathname.startsWith("/metrics") ||
    url.pathname.startsWith("/meals") ||
    url.pathname.startsWith("/foods") ||
    url.pathname.startsWith("/admin") ||
    url.pathname.startsWith("/workouts")
  ) {
    return; // default network behavior
  }

  // Network-first for navigation (so a fresh deploy is visible right away)
  // with cache fallback (so the app loads while offline).
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/index.html"))
    );
    return;
  }

  // Cache-first for everything else (the bundled JS/CSS, icon, fonts).
  event.respondWith(
    caches.match(event.request).then((hit) => hit || fetch(event.request))
  );
});
