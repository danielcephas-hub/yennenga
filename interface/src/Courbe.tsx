// Petite courbe : élèves inscrits (observés), prévision et sa marge.
import { useEffect, useRef, useState } from 'react'
import { nb } from './format'

type Props = { serie: [number, number][]; prevision?: [number, number, number, number][]; hauteur?: number }

// pas « rond » (1, 2, 2,5 ou 5 × 10ⁿ) donnant environ trois graduations
function pasRond(max: number): number {
  const brut = max / 3
  const p = 10 ** Math.floor(Math.log10(brut))
  return [1, 2, 2.5, 5, 10].map((k) => k * p).find((v) => v >= brut) ?? brut
}

const millier = (v: number) => (v >= 1000 ? `${nb(v / 1000, v % 1000 ? 1 : 0)} k` : nb(v))

export default function Courbe({ serie, prevision = [], hauteur = 150 }: Props) {
  // le dessin prend la largeur réelle de son cadre (1 unité = 1 pixel) : les graduations restent à 12 px sur téléphone
  const boite = useRef<HTMLElement>(null)
  const [L, setL] = useState(320)
  useEffect(() => {
    if (!boite.current) return
    const o = new ResizeObserver(([e]) => setL(Math.max(240, Math.round(e.contentRect.width))))
    o.observe(boite.current)
    return () => o.disconnect()
  }, [])
  if (!serie.length) return null
  const H = hauteur, g = 44, d = 12, h = 12, b = 24
  const xs = [...serie.map((s) => s[0]), ...prevision.map((p) => p[0])]
  const ys = [...serie.map((s) => s[1]), ...prevision.flatMap((p) => [p[2], p[3]])]
  const x0 = Math.min(...xs), x1 = Math.max(...xs)
  const pas = pasRond(Math.max(...ys, 1))
  const y1 = Math.ceil((Math.max(...ys, 1) * 1.04) / pas) * pas
  const X = (x: number) => g + ((x - x0) / Math.max(1, x1 - x0)) * (L - g - d)
  const Y = (y: number) => h + (1 - y / y1) * (H - h - b)
  const ligne = (pts: [number, number][]) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join('')
  const dernier = serie[serie.length - 1]
  const prev: [number, number][] = prevision.length ? [[dernier[0], dernier[1]], ...prevision.map((p) => [p[0], p[1]] as [number, number])] : []
  const marge = prevision.length
    ? `M${X(dernier[0])},${Y(dernier[1])}` + prevision.map((p) => `L${X(p[0])},${Y(p[3])}`).join('') +
      [...prevision].reverse().map((p) => `L${X(p[0])},${Y(p[2])}`).join('') + 'Z'
    : ''
  const graduations = Array.from({ length: Math.round(y1 / pas) }, (_, i) => (i + 1) * pas)
  const zeros = serie.filter(([, y]) => y === 0)
  const annees = Array.from(new Set([x0, ...serie.filter(([x]) => x % 5 === 0).map(([x]) => x), dernier[0], x1]))
    .filter((a, i, t) => i === 0 || a - t[i - 1] >= (L < 300 ? 5 : 3) || a === x1)
  return (
    <figure className="courbe-fig" ref={boite}>
      <svg viewBox={`0 0 ${L} ${H}`} className="courbe" role="img"
        aria-label={`Élèves inscrits de ${x0} à ${dernier[0]}, puis prévision jusqu'en ${x1}`}>
        <line x1={g} x2={L - d} y1={Y(0)} y2={Y(0)} className="axe-base" />
        {graduations.map((v) => (
          <g key={v}>
            <line x1={g} x2={L - d} y1={Y(v)} y2={Y(v)} className="grille" />
            <text x={g - 4} y={Y(v) + 3} textAnchor="end" className="axe">{millier(v)}</text>
          </g>
        ))}
        {prevision.length > 0 && <line x1={X(dernier[0])} x2={X(dernier[0])} y1={h} y2={Y(0)} className="repere" />}
        {marge && <path d={marge} className="marge" />}
        <path d={ligne(serie)} className="observe" />
        {prev.length > 0 && <path d={ligne(prev)} className="prevu" />}
        {zeros.map(([x]) => (
          <g key={x}>
            <circle cx={X(x)} cy={Y(0)} r={3} className="point-zero" />
            <text x={X(x)} y={Y(0) - 6} textAnchor="middle" className="axe">aucune école ouverte</text>
          </g>
        ))}
        {annees.map((a) => <text key={a} x={X(a)} y={H - 6} textAnchor={a === x0 ? 'start' : a === x1 ? 'end' : 'middle'} className="axe">{a}</text>)}
      </svg>
      <figcaption className="legende-courbe">
        <span><i className="trait-observe" />inscrits</span>
        {prevision.length > 0 && <><span><i className="trait-prevu" />prévision</span><span><i className="aire-marge" />marge : 8 prévisions sur 10 y tombaient lors du test sur le passé</span></>}
      </figcaption>
    </figure>
  )
}
