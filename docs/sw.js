// Service worker mínimo: hace instalable la página como app. No guarda nada en caché
// (los informes tienen que ser siempre los últimos publicados).
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) { e.respondWith(fetch(e.request)); });
