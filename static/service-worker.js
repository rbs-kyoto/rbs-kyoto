const CACHE_NAME = "rbs-offline-v2";
const OFFLINE_URL = "/static/offline.html";

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.add(OFFLINE_URL))
            .then(() => self.skipWaiting()),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => Promise.all(
                cacheNames
                    .filter((cacheName) => cacheName.startsWith("rbs-offline-")
                        && cacheName !== CACHE_NAME)
                    .map((cacheName) => caches.delete(cacheName)),
            ))
            .then(() => self.clients.claim()),
    );
});

self.addEventListener("push", (event) => {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch {
            payload = { body: event.data.text() };
        }
    }

    event.waitUntil(
        self.registration.showNotification(payload.title || "rbs京都", {
            body: payload.body || "返却予定のお知らせがあります。",
            icon: "/static/main/img/pwa-icon-192.png",
            badge: "/static/main/img/pwa-icon-72.png",
            data: { url: payload.url || "/" },
        }),
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const target = new URL(event.notification.data?.url || "/", self.location.origin);
    if (target.origin !== self.location.origin) {
        return;
    }
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true })
            .then((clients) => {
                const client = clients.find((windowClient) => "focus" in windowClient);
                if (client) {
                    return client.navigate(target.href).then(() => client.focus());
                }
                return self.clients.openWindow(target.href);
            }),
    );
});

self.addEventListener("fetch", (event) => {
    if (event.request.mode !== "navigate"
        || new URL(event.request.url).origin !== self.location.origin) {
        return;
    }

    event.respondWith(
        fetch(event.request).catch(async () => {
            const offlinePage = await caches.match(OFFLINE_URL);
            if (offlinePage) {
                return offlinePage;
            }
            throw new Error("Offline fallback page is not available in cache.");
        }),
    );
});
