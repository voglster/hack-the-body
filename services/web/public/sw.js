/* Hack the Body service worker.
 *
 * Tiny on purpose: cache the bundled app shell so the page loads instantly on
 * repeat visits, but never cache API responses (those must always be fresh).
 * On every deploy the cache name (CACHE) gets a new version via Vite's
 * content-hashed bundle file names, which naturally invalidates the old shell
 * the first time a new index.html requests new assets.
 */

const CACHE = "htb-shell-v2";
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
    url.pathname.startsWith("/workouts") ||
    url.pathname.startsWith("/coach") ||
    url.pathname.startsWith("/push")
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

// ---------- Web Push ----------

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data?.text?.() || "" }; }
  const title = data.title || "Hack the Body";
  const body = data.body || "";
  const url = data.url || "/";
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icon.svg",
      badge: "/icon.svg",
      data: { url },
      tag: "htb",  // collapse to one notification at a time
      renotify: true,
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((all) => {
      for (const c of all) {
        if (c.url.endsWith(target) && "focus" in c) return c.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
