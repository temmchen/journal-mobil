/* Journal Mobil – Service Worker
   Aufgabe: die App-Hülle (HTML, pdf.js, Icons) offline verfügbar halten und
   verschlüsselte Tresordateien zwischenspeichern. Alles bleibt verschlüsselt im
   Cache; entschlüsselt wird nur im Seitenkontext.

   Strategien
   - Hülle, Index und Manifeste (index.html, lib/*, manifest.webmanifest,
     vaults/index.json, */m.enc): network-first, Cache als Rückfall.
   - Tresordateien vaults/*/f/*.enc: cache-first – die Kennung (fid) ändert sich,
     sobald der Inhalt sich ändert, der Cache kann also nie veralten.
   - Fremde Origins werden nicht angefasst. */

const CACHE = "jm-v1";
const HUELLE = [
  "./", "./index.html", "./manifest.webmanifest",
  "./lib/pdf.min.mjs", "./lib/pdf.worker.min.mjs",
  "./icons/icon-180.png", "./icons/icon-192.png", "./icons/icon-512.png"
];

self.addEventListener("install", ev => {
  ev.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // Einzeln laden, damit eine fehlende Datei nicht die ganze Installation kippt.
    await Promise.all(HUELLE.map(async p => {
      try { await cache.add(new Request(p, { cache: "reload" })); } catch (e) { /* offline o. ä. */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", ev => {
  ev.waitUntil((async () => {
    const namen = await caches.keys();
    await Promise.all(namen.filter(n => n !== CACHE).map(n => caches.delete(n)));
    await self.clients.claim();
  })());
});

/* Hilfen zur Einordnung eines Pfads (relativ zum Scope) */
function relPfad(url) {
  const scope = self.registration.scope;                // z. B. https://…/journal-mobil/
  return url.href.startsWith(scope) ? url.href.slice(scope.length).split("?")[0] : null;
}
const istTresordatei = p => /^vaults\/[^/]+\/f\/[^/]+\.enc$/.test(p);
const istHuelle = p =>
  p === "" || p === "index.html" || p === "manifest.webmanifest" || p === "sw.js" ||
  p.startsWith("lib/") || p.startsWith("icons/") ||
  p === "vaults/index.json" || /^vaults\/[^/]+\/m\.enc$/.test(p);

self.addEventListener("fetch", ev => {
  const req = ev.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;       // fremde Origins nicht anfassen
  const p = relPfad(url);
  if (p === null) return;

  if (istTresordatei(p)) {
    ev.respondWith(cacheFirst(req));
  } else if (istHuelle(p) || req.mode === "navigate") {
    ev.respondWith(networkFirst(req));
  }
});

async function cacheFirst(req) {
  const cache = await caches.open(CACHE);
  const treffer = await cache.match(req, { ignoreSearch: true });
  if (treffer) return treffer;
  const antwort = await fetch(req);
  if (antwort && antwort.ok) cache.put(req, antwort.clone()).catch(() => {});
  return antwort;
}

async function networkFirst(req) {
  const cache = await caches.open(CACHE);
  try {
    const antwort = await fetch(req);
    if (antwort && antwort.ok) cache.put(req, antwort.clone()).catch(() => {});
    return antwort;
  } catch (e) {
    const treffer = await cache.match(req, { ignoreSearch: true })
      || (req.mode === "navigate" ? await cache.match("./index.html") : null);
    if (treffer) return treffer;
    throw e;
  }
}
