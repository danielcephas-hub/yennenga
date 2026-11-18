import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'

// la bibliothèque de carte n'est chargée qu'à l'ouverture d'une vue qui en a besoin
const VueCarte = lazy(() => import('./VueCarte'))
const VueRepartition = lazy(() => import('./VueRepartition'))
import { donnees, type Meta } from './api'
import { definirNoms } from './format'
import VueAccueil from './VueAccueil'
import VueDonnees from './VueDonnees'
import VueMethode from './VueMethode'
import Visite from './Visite'
import Intro from './Intro'
import Assistant from './Assistant'

const VUES = [
  { cle: 'accueil', libelle: 'Accueil' },
  { cle: 'carte', libelle: 'Carte' },
  { cle: 'repartition', libelle: 'Répartition' },
  { cle: 'donnees', libelle: 'Données' },
  { cle: 'methode', libelle: 'Méthode' },
]
const CLE_VISITE = 'yennenga-visite-vue'

function lireVue(): string {
  const h = window.location.hash.replace('#', '').split(/[/?]/)[0]
  return VUES.some((v) => v.cle === h) ? h : 'accueil'
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [vue, setVueEtat] = useState(lireVue)
  const [etape, setEtape] = useState<number | null>(null)
  const [essai, setEssai] = useState(0)
  const [enLigne, setEnLigne] = useState(() => navigator.onLine)
  const entete = useRef<HTMLElement>(null)
  const principal = useRef<HTMLElement>(null)
  const premiere = useRef(true)

  const setVue = useCallback((v: string) => {
    setVueEtat(v)
    if (window.location.hash !== `#${v}`) window.history.pushState(null, '', `#${v}`)
  }, [])

  useEffect(() => {
    setErreur(null)
    donnees<Meta>('meta').then((m) => { definirNoms(m.noms); setMeta(m) }).catch((e) => setErreur(String(e.message)))
  }, [essai])
  useEffect(() => {
    const surHash = () => setVueEtat(lireVue())
    const reseau = () => setEnLigne(navigator.onLine)
    window.addEventListener('hashchange', surHash)
    window.addEventListener('popstate', surHash)
    window.addEventListener('online', reseau)
    window.addEventListener('offline', reseau)
    return () => {
      window.removeEventListener('hashchange', surHash); window.removeEventListener('popstate', surHash)
      window.removeEventListener('online', reseau); window.removeEventListener('offline', reseau)
    }
  }, [])
  // hauteur réelle de l'en-tête : les barres collantes (plan, réglages) se placent juste dessous
  useEffect(() => {
    const el = entete.current
    if (!el) return
    const o = new ResizeObserver(() => document.documentElement.style.setProperty('--h-entete', `${el.offsetHeight}px`))
    o.observe(el)
    return () => o.disconnect()
  }, [meta])
  // changement de vue : le lecteur d'écran et le clavier repartent du titre de la nouvelle vue
  useEffect(() => {
    if (premiere.current) { premiere.current = false; return }
    principal.current?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  }, [vue])

  // première ouverture : la vidéo de présentation, puis la visite guidée (mémorisé dans ce navigateur seulement) ;
  // hors ligne, la visite directement (la vidéo n'est pas gardée sur l'appareil)
  const [intro, setIntro] = useState(false)
  useEffect(() => {
    if (!meta) return
    const q = window.location.search
    let dejaVue = false
    try { dejaVue = window.localStorage.getItem(CLE_VISITE) === '1' } catch { /* stockage indisponible */ }
    // « ?intro » : la rejouer ; « ?sans-visite » : captures d'écran et démonstrations sans rien d'automatique
    if (q.includes('sans-visite') || lireVue() !== 'accueil' || (dejaVue && !q.includes('intro'))) return
    if (navigator.onLine) setIntro(true)
    else setEtape(0)
  }, [meta])
  const finIntro = useCallback(() => { setIntro(false); setVue('accueil'); setEtape(0) }, [setVue])

  const finVisite = (n: number | null) => {
    setEtape(n)
    if (n === null) { try { window.localStorage.setItem(CLE_VISITE, '1') } catch { /* stockage indisponible */ } }
  }

  if (erreur) return (
    <div className="chargement" role="alert">
      <p><b>Les données de l'outil n'ont pas pu être chargées.</b> {navigator.onLine ? 'Le serveur ne répond pas pour le moment.' : 'Vous êtes hors ligne et ces données ne sont pas encore gardées sur cet appareil.'}</p>
      <p><button className="principal" onClick={() => setEssai(essai + 1)}>Réessayer</button> <a href="/hors-ligne">Ouvrir le tableau de bord hors ligne</a></p>
      <p className="petit">Détail technique : {erreur}</p>
    </div>
  )
  if (!meta) return <div className="chargement" aria-busy="true">Chargement de Yennenga…</div>

  return (
    <div className="app">
      <a className="lien-evitement" href="#contenu" onClick={(e) => { e.preventDefault(); principal.current?.focus() }}>Aller au contenu</a>
      <header className="entete" ref={entete}>
        <a className="marque" href="#accueil" aria-label="Yennenga, accueil">
          <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#1f5c4a" /><path d="M8 22V12l8-4 8 4v10" fill="none" stroke="#f2c14e" strokeWidth="2.5" /><rect x="13" y="16" width="6" height="6" fill="#f2c14e" /></svg>
          <div><b>Yennenga</b><span>Enseignants et salles de classe · primaire</span></div>
        </a>
        <nav aria-label="Vues">
          {VUES.map((v) => (
            <a key={v.cle} href={`#${v.cle}`} className={vue === v.cle ? 'actif' : ''} aria-current={vue === v.cle ? 'page' : undefined}>{v.libelle}</a>
          ))}
          <button className="lien visite-lancer" onClick={() => setEtape(0)}><span className="long">Visite guidée</span><span className="court">Visite</span></button>
        </nav>
      </header>
      {!enLigne && <div className="bandeau-hors-ligne" role="status">Hors ligne : vous consultez les données gardées sur cet appareil ({meta.annee_reference}). Le calcul d'un nouveau plan et l'assistant demandent le réseau.</div>}
      <main id="contenu" ref={principal} tabIndex={-1}>
        {vue === 'accueil' && <VueAccueil meta={meta} aller={setVue} visite={() => setEtape(0)} />}
        <Suspense fallback={<div className="chargement">Chargement de la carte…</div>}>
          {vue === 'carte' && <VueCarte meta={meta} />}
          {vue === 'repartition' && <VueRepartition meta={meta} />}
        </Suspense>
        {vue === 'donnees' && <VueDonnees anneeReference={meta.annee_reference} />}
        {vue === 'methode' && <VueMethode meta={meta} />}
      </main>
      <footer className="pied">
        Données {meta.annee_reference}, prévisions jusqu'à la rentrée {meta.annee_horizon.slice(0, 4)}. Sources : annuaires statistiques DGESS, INSD, CONASUR, OCHA, WorldPop, OpenStreetMap. <a href="#methode">Méthode et sources détaillées</a>
      </footer>
      {intro && <Intro fin={finIntro} />}
      {etape !== null && <Visite etape={etape} setEtape={finVisite} setVue={setVue} meta={meta} terminer={() => { finVisite(null); setVue('accueil') }} />}
      <Assistant aller={setVue} vue={vue} />
    </div>
  )
}
