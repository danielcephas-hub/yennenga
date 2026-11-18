// Visite guidée : à la première ouverture, l'outil se présente sur ses vrais écrans, et agit pour le visiteur
// (il ouvre une fiche, descend aux communes, lance un calcul). La page reste utilisable pendant la visite.
// Aucune bibliothèque externe : un calque qui met en valeur l'élément visé et une bulle d'explication.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { demander, type ActionVisite } from './visiteActions'
import type { Meta } from './api'
import { joli, nb, pct } from './format'

export type Etape = { vue: string; cible: string; titre: string; texte: string; action?: ActionVisite }

const EXEMPLE_DEFAUT = 'LOROUM'

// première étape : le chiffre de l'écran de résultat, lu dans les données publiées (jamais écrit à la main)
function introduction(meta: Meta): string {
  const pr = meta.plan_reference
  const md = pr?.cout_fcfa ? pr.cout_fcfa / 1e9 : null
  const sO = pr?.surnombre_avant != null && pr.surnombre_optimisee != null ? pr.surnombre_avant - pr.surnombre_optimisee : null
  const sP = pr?.surnombre_avant != null && pr.surnombre_proportionnelle != null ? pr.surnombre_avant - pr.surnombre_proportionnelle : null
  if (!pr || !md || sO == null || !sP) return 'La visite montre en deux minutes comment l\'outil mesure les besoins, calcule un plan et le compare aux règles simples.'
  return `Avec ${nb(pr.enseignants)} enseignants et ${nb(pr.salles)} salles, le plan sort ${nb(sO)} élèves des classes surchargées : ${nb(sO / md)} par milliard de FCFA, contre ${nb(sP / md)} en partageant selon le nombre d'élèves (+${pct(sO / sP - 1, 0)} pour le même argent). La visite montre d'où vient ce chiffre, en deux minutes.`
}

export const ETAPES: Etape[] = [
  { vue: 'accueil', cible: 'resultat', titre: 'Ce que l\'outil change', texte: '' },
  { vue: 'carte', cible: 'panneau-carte', titre: '1. Comprendre : la carte', texte: 'Choisissez un indicateur : élèves par enseignant, indice de besoin, écoles fermées… Les couleurs changent de teinte à la norme de 50 élèves par enseignant.' },
  { vue: 'carte', cible: 'fiche', action: { action: 'province', arg: EXEMPLE_DEFAUT }, titre: 'La fiche d\'une province', texte: '' },
  { vue: 'carte', cible: 'carte', action: { action: 'communes', arg: EXEMPLE_DEFAUT }, titre: 'Descendre à la commune', texte: '' },
  { vue: 'repartition', cible: 'moyens', titre: '2. Décider : vos moyens', texte: 'Indiquez les postes et les salles disponibles, ou seulement un budget : l\'outil choisit alors le meilleur partage entre recruter et construire. Vous pouvez aussi autoriser des redéploiements.' },
  { vue: 'repartition', cible: 'contraintes', titre: 'Vos exigences', texte: 'Imposez par exemple « au moins 300 enseignants au Sahel ». Une exigence impossible à tenir est expliquée, jamais contournée.' },
  { vue: 'repartition', cible: 'tuiles', action: { action: 'calculer' }, titre: 'Le calcul est fait en direct', texte: 'Le serveur vient de recalculer le plan : en quelques secondes, le meilleur plan possible, vérifié par le calcul. Il s\'exporte en Excel et s\'imprime en fiche de décision.' },
  { vue: 'repartition', cible: 'comparaison', titre: 'Comparé aux règles simples', texte: 'À moyens égaux, le plan est comparé à deux règles simples. Tout est affiché, y compris ce que Yennenga cède : elle soulage d\'abord les provinces les plus chargées.' },
  { vue: 'donnees', cible: 'ajout-donnees', titre: '3. Mettre à jour', texte: 'Chaque année, l\'annuaire se dépose dans le fichier type : l\'outil le contrôle ligne par ligne, puis l\'intègre. Un changement de découpage (province créée ou renommée) se déclare sans programmation.' },
]

type Props = { etape: number; setEtape: (n: number | null) => void; setVue: (v: string) => void; meta: Meta; terminer: () => void }

// textes qui dépendent des données : province de l'exemple, horizon, nombre de communes
function completer(e: Etape, i: number, meta: Meta): Etape {
  const ex = meta.plan_reference?.province_pire_avant ?? EXEMPLE_DEFAUT
  const h = meta.annee_horizon.slice(0, 4)
  const action = e.action && (e.action.action === 'province' || e.action.action === 'communes') ? { ...e.action, arg: ex } : e.action
  if (i === 0) return { ...e, texte: introduction(meta) }
  if (e.cible === 'fiche') return { ...e, action, texte: `Un clic sur une province ouvre sa fiche. Ici ${joli(ex)}, la plus chargée : chiffres clés, rang de priorité avec sa fourchette et la raison de ce rang, effectifs passés et prévision jusqu'en ${h} avec sa marge.` }
  if (e.cible === 'carte' && e.action) return { ...e, action, texte: `Les ${nb(meta.national.communes)} communes : enfants attendus en ${h}, accès à l'école, déplacés, et les sites où ouvrir une école. Disque plein : construire ; cercle : rouvrir d'abord les écoles fermées.` }
  return e
}

const LARGEUR = 360

export default function Visite({ etape, setEtape, setVue, meta, terminer }: Props) {
  const e = completer(ETAPES[etape], etape, meta)
  const [boite, setBoite] = useState<DOMRect | null>(null)
  const bulle = useRef<HTMLDivElement>(null)
  const suivant = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    setVue(e.vue)
    if (e.action) demander(e.action)
  }, [etape]) // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    let essais = 0
    let minuteur = 0
    setBoite(null)
    const placer = () => {
      const el = document.querySelector(`[data-visite="${e.cible}"]`)
      if (el) {
        // un bloc replié (réglages « Vos exigences ») s'ouvre pour être montré
        if (el instanceof HTMLDetailsElement) el.open = true
        el.scrollIntoView({ block: 'center', behavior: 'smooth' })
        // la position finale est relue une fois le défilement terminé
        minuteur = window.setTimeout(() => setBoite(el.getBoundingClientRect()), 450)
      } else if (essais++ < 30) minuteur = window.setTimeout(placer, 100)
    }
    placer()
    const r = () => { const el = document.querySelector(`[data-visite="${e.cible}"]`); if (el) setBoite(el.getBoundingClientRect()) }
    window.addEventListener('resize', r)
    window.addEventListener('scroll', r, true)
    return () => { window.clearTimeout(minuteur); window.removeEventListener('resize', r); window.removeEventListener('scroll', r, true) }
  }, [e.cible, etape])

  // focus dans la bulle à chaque étape ; Échap quitte ; flèches ; Tab reste dans la bulle
  useEffect(() => { suivant.current?.focus({ preventScroll: true }) }, [etape])
  useEffect(() => {
    const touche = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') setEtape(null)
      else if (ev.key === 'ArrowRight' && etape < ETAPES.length - 1) setEtape(etape + 1)
      else if (ev.key === 'ArrowLeft' && etape > 0) setEtape(etape - 1)
      else if (ev.key === 'Tab' && bulle.current) {
        const f = Array.from(bulle.current.querySelectorAll<HTMLElement>('button'))
        const i = f.indexOf(document.activeElement as HTMLElement)
        if (i === -1 || (ev.shiftKey && i === 0) || (!ev.shiftKey && i === f.length - 1)) {
          ev.preventDefault()
          f[ev.shiftKey ? f.length - 1 : 0]?.focus()
        }
      }
    }
    window.addEventListener('keydown', touche)
    return () => window.removeEventListener('keydown', touche)
  }, [etape, setEtape])

  // bulle : sur téléphone, rangée en bas de l'écran ; sinon à côté de la cible, sans la recouvrir
  const W = window.innerWidth, H = window.innerHeight, marge = 8, h = bulle.current?.offsetHeight ?? 200
  let style: React.CSSProperties
  if (W < 640) style = { left: 8, right: 8, bottom: 8, width: 'auto' }
  else if (!boite) style = { top: 120, left: Math.max(12, (W - LARGEUR) / 2) }
  else {
    const gauche = Math.min(Math.max(12, boite.left), W - LARGEUR - 12)
    if (H - boite.bottom > h + 24) style = { top: boite.bottom + 14, left: gauche }
    else if (boite.top > h + 24) style = { top: boite.top - h - 14, left: gauche }
    else if (W - boite.right > LARGEUR + 24) style = { top: Math.min(Math.max(12, boite.top), H - h - 12), left: boite.right + 14 }
    else if (boite.left > LARGEUR + 24) style = { top: Math.min(Math.max(12, boite.top), H - h - 12), left: boite.left - LARGEUR - 14 }
    else style = { bottom: 12, left: gauche }
  }
  return (
    <div className="visite">
      {boite && (
        <div className="visite-trou" style={{ top: boite.top - marge, left: boite.left - marge, width: boite.width + 2 * marge, height: boite.height + 2 * marge }} />
      )}
      <div className="visite-bulle" ref={bulle} style={style} role="dialog" aria-modal="false" aria-labelledby="visite-titre" aria-describedby="visite-texte">
        <div className="visite-progres" aria-hidden="true">
          {ETAPES.map((_, i) => <span key={i} className={i <= etape ? 'fait' : ''} />)}
        </div>
        <h3 id="visite-titre">{e.titre} <small>({etape + 1} sur {ETAPES.length})</small></h3>
        <p id="visite-texte">{e.texte}</p>
        <div className="visite-boutons">
          <button className="lien" onClick={() => setEtape(null)}>Quitter la visite</button>
          <span>
            {etape > 0 && <button className="secondaire" onClick={() => setEtape(etape - 1)}>Précédent</button>}
            {etape < ETAPES.length - 1
              ? <button ref={suivant} className="principal" onClick={() => setEtape(etape + 1)}>Suivant</button>
              : <button ref={suivant} className="principal" onClick={terminer}>Terminer</button>}
          </span>
        </div>
      </div>
    </div>
  )
}
