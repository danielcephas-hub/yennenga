// Avant / après : pour chaque province, élèves par enseignant à l'horizon sans moyens nouveaux (rond creux)
// et après le plan (rond plein), triées de la plus chargée à la moins chargée, avec la ligne de norme.
import { useEffect, useRef, useState } from 'react'
import type { LigneRepartition } from './api'
import { joli, nb } from './format'

type Props = { lignes: LigneRepartition[]; norme: number; max?: number; horizon?: string }

export default function AvantApres({ lignes, norme, max = 45, horizon }: Props) {
  // le dessin prend la largeur réelle de son cadre : 1 unité = 1 pixel, les textes gardent leur taille
  const boite = useRef<HTMLElement>(null)
  const [L, setL] = useState(820)
  useEffect(() => {
    if (!boite.current) return
    const o = new ResizeObserver(([e]) => setL(Math.max(260, Math.round(e.contentRect.width))))
    o.observe(boite.current)
    return () => o.disconnect()
  }, [])
  const d = lignes
    .map((l) => ({ p: l.province, avant: l.maitres > 0 ? l.eleves_horizon / l.maitres : null, apres: l.ratio_maitre_apres, ajout: l.enseignants_attribues + (l.solde_redeploiement ?? 0) }))
    .filter((x): x is { p: string; avant: number; apres: number; ajout: number } => x.avant != null && x.apres != null)
    .sort((a, b) => b.avant - a.avant)
    .slice(0, max)
  if (!d.length) return null
  // téléphone : le nom passe au-dessus de sa ligne, l'axe se réduit à trois repères lisibles
  const etroit = L < 480
  const pas = etroit ? 36 : 22, haut = 30, gauche = etroit ? 10 : 130, droite = etroit ? 44 : 70
  const H = haut + d.length * pas + 8
  const vmin = Math.min(30, ...d.map((x) => x.apres)), vmax = Math.max(...d.map((x) => x.avant)) * 1.03
  const X = (v: number) => gauche + ((v - vmin) / (vmax - vmin)) * (L - gauche - droite)
  const graduations = etroit
    ? [Math.ceil(vmin / 10) * 10, norme, Math.floor(vmax / 10) * 10].filter((v, i, t) => v >= vmin && v <= vmax && t.indexOf(v) === i && (v === norme || Math.abs(v - norme) >= 15))
    : [30, 40, 50, 60, 70, 80, 90, 100, 110, 120].filter((v) => v >= vmin && v <= vmax)
  return (
    <figure className="avant-apres" ref={boite}>
      <svg viewBox={`0 0 ${L} ${H}`} role="img"
        aria-label={`Élèves par enseignant avant et après le plan, ${d.length} provinces. La plus chargée passe de ${nb(d[0].avant)} à ${nb(d[0].apres)}.`}>
        {graduations.map((v) => (
          <g key={v}>
            <line x1={X(v)} x2={X(v)} y1={haut - 6} y2={H - 4} className={v === norme ? 'norme' : 'grille'} />
            <text x={X(v)} y={haut - 10} textAnchor="middle" className={v === norme ? 'axe norme-txt' : 'axe'}>{v === norme ? `norme ${v}` : v}</text>
          </g>
        ))}
        {d.map((x, i) => {
          const y = haut + i * pas + pas / 2
          const bouge = Math.abs(x.avant - x.apres) >= 0.5
          return (
            <g key={x.p}>
              {etroit ? <text x={gauche} y={y - 9} className="nom">{joli(x.p)}</text>
                : <text x={gauche - 10} y={y + 4.5} textAnchor="end" className="nom">{joli(x.p)}</text>}
              {bouge && <line x1={X(x.avant)} x2={X(x.apres)} y1={y} y2={y} className="tige" />}
              <circle cx={X(x.avant)} cy={y} r={5} className="avant" />
              <circle cx={X(x.apres)} cy={y} r={5.5} className={x.apres > norme ? 'apres au-dessus' : 'apres'} />
              {x.ajout > 0 && <text x={L - 4} y={y + 4.5} textAnchor="end" className="ajout">+{nb(x.ajout)}</text>}
            </g>
          )
        })}
        <text x={L - 4} y={haut - 10} textAnchor="end" className="axe">enseignants</text>
      </svg>
      <figcaption>
        <span><i className="pt avant" />sans moyens nouveaux</span>
        <span><i className="pt apres" />après le plan, à la norme</span>
        <span><i className="pt apres au-dessus" />après le plan, encore au-dessus de la norme</span>
        <span>Élèves par enseignant{horizon ? ` à la rentrée ${horizon.slice(0, 4)}` : ''} ; à droite, enseignants ajoutés (recrues et redéploiements).</span>
      </figcaption>
    </figure>
  )
}
