// Yennenga : garde l'application et ses données dans le navigateur, pour les connexions lentes ou coupées.
// - dès la première visite, l'installation précharge la page, tous les fichiers de l'application (y compris la carte)
//   et les données de consultation : l'outil s'ouvre ensuite sans réseau ;
// - fichiers de l'application (/assets/, noms uniques) : servis depuis le cache dès qu'ils y sont ;
// - données publiées (/api/donnees/, /api/etat) : réseau d'abord ; copie gardée si le réseau tarde (4 s) ou manque ;
// - page d'accueil : réseau d'abord (une nouvelle version se voit aussitôt), copie gardée si le réseau manque.
// Les calculs (POST) passent toujours par le réseau.
const VERSION = 'yennenga-' + (new URL(self.location.href).searchParams.get('v') || '0')
const DONNEES = ['meta', 'provinces', 'provinces_annees', 'communes', 'sites', 'geo_provinces_annuaires', 'geo_communes', 'geo_regions_2025']

// la page, puis les fichiers qu'elle charge, puis ceux que ces fichiers chargent à la demande (vues, carte)
async function precharger() {
  const cache = await caches.open(VERSION)
  const page = await fetch('/', { cache: 'no-cache' })
  if (!page.ok) return
  const html = await page.clone().text()
  await cache.put('/', page)
  const vus = new Set()
  const attente = [...html.matchAll(/\/assets\/[\w.-]+\.(?:js|css)/g)].map((m) => m[0])
  while (attente.length) {
    const u = attente.pop()
    if (vus.has(u)) continue
    vus.add(u)
    try {
      const rep = await fetch(u)
      if (!rep.ok) continue
      if (u.endsWith('.js')) {
        const texte = await rep.clone().text()
        for (const m of texte.matchAll(/assets\/[\w.-]+\.(?:js|css)/g)) attente.push('/' + m[0])
      }
      await cache.put(u, rep)
    } catch { /* un fichier manquant n'empêche pas les autres */ }
  }
  await Promise.all([...DONNEES.map((n) => `/api/donnees/${n}.json`), '/api/etat'].map((u) =>
    fetch(u).then((rep) => (rep.ok ? cache.put(u, rep) : null)).catch(() => null)))
}

self.addEventListener('install', (e) => {
  self.skipWaiting()
  e.waitUntil(precharger().catch(() => undefined))
})
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((cles) => Promise.all(cles.filter((c) => c !== VERSION).map((c) => caches.delete(c))))
    .then(() => self.clients.claim()))
})

const garder = (cle, rep) => { if (rep.ok) { const copie = rep.clone(); caches.open(VERSION).then((c) => c.put(cle, copie)) } return rep }

// données : le réseau d'abord (toujours les chiffres à jour après une mise à jour annuelle) ;
// la copie gardée seulement si le réseau ne répond pas dans le délai (connexion lente) ou manque
const reseauOuCopie = (r, delai) => new Promise((repondre) => {
  let fait = false
  const finir = (rep) => { if (!fait && rep) { fait = true; repondre(rep) } }
  const minuterie = setTimeout(() => caches.match(r, { ignoreSearch: true }).then(finir), delai)
  fetch(r)
    .then((rep) => { clearTimeout(minuterie); finir(garder(r, rep)) })
    .catch(() => { clearTimeout(minuterie); caches.match(r, { ignoreSearch: true }).then((m) => finir(m || Response.error())) })
})

self.addEventListener('fetch', (e) => {
  const r = e.request
  if (r.method !== 'GET') return
  const u = new URL(r.url)
  if (u.origin !== self.location.origin) return

  if (u.pathname.startsWith('/assets/')) {
    e.respondWith(caches.match(r).then((m) => m || fetch(r).then((rep) => garder(r, rep))))
  } else if (u.pathname.startsWith('/api/donnees/') || u.pathname === '/api/etat') {
    e.respondWith(reseauOuCopie(r, 4000))
  } else if (r.mode === 'navigate') {
    e.respondWith(fetch(r).then((rep) => garder('/', rep)).catch(() => caches.match('/').then((m) => m || Response.error())))
  }
})
