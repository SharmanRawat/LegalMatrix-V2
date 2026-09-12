// Self-destructing service worker.
// Registered by ServiceWorkerRegister during production builds. Service workers
// that precache the '/' HTML break after every rebuild (the cached shell
// references old chunk hashes that 500), which surfaced to users as Chrome's
// "This page couldn't load" black screen. Disable interception entirely:
// unregister, wipe all caches, and hand control back to the network.
self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => self.registration.unregister()),
  )
})