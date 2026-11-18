// Infobulle d'explication : une petite icône « i » alignée sur le texte. L'explication flotte au-dessus de la page
// (elle ne décale rien), au survol, au clavier (focus) ou au toucher ; Échap ou un clic ailleurs la ferme.
// Placée par rapport à l'écran : jamais coupée par un panneau qui défile ou un tableau.
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type Place = { left: number; top: number; fleche: number; dessous: boolean }
const LARGEUR = 320, MARGE = 8

export default function Aide({ children, titre = 'Explication' }: { children: ReactNode; titre?: string }) {
  const [ouvert, setOuvert] = useState(false)
  const [epingle, setEpingle] = useState(false) // ouverte par un clic ou un toucher : reste ouverte jusqu'à un clic ailleurs
  const [place, setPlace] = useState<Place | null>(null)
  const bouton = useRef<HTMLButtonElement>(null)
  const bulle = useRef<HTMLDivElement>(null)
  const minuterie = useRef(0)
  const id = useId()

  const fermer = useCallback(() => { setOuvert(false); setEpingle(false); setPlace(null) }, [])
  const ouvrir = () => { window.clearTimeout(minuterie.current); setOuvert(true) }
  const fermerBientot = () => { if (!epingle) minuterie.current = window.setTimeout(() => setOuvert(false), 120) }

  // position : au-dessus du bouton s'il y a la place, sinon dessous ; recadrée dans la largeur de l'écran
  useLayoutEffect(() => {
    if (!ouvert || !bouton.current || !bulle.current) return
    const b = bouton.current.getBoundingClientRect()
    const h = bulle.current.offsetHeight
    const l = Math.min(LARGEUR, window.innerWidth - 2 * MARGE)
    const centre = b.left + b.width / 2
    const left = Math.max(MARGE, Math.min(centre - l / 2, window.innerWidth - l - MARGE))
    const dessous = b.top - h - 10 < MARGE
    setPlace({ left, top: dessous ? b.bottom + 10 : b.top - h - 10, fleche: centre - left, dessous })
  }, [ouvert, children])

  useEffect(() => {
    if (!ouvert) return
    const touche = (e: KeyboardEvent) => { if (e.key === 'Escape') { fermer(); bouton.current?.focus() } }
    const clic = (e: MouseEvent) => {
      const t = e.target as Node
      if (!bouton.current?.contains(t) && !bulle.current?.contains(t)) fermer()
    }
    window.addEventListener('keydown', touche)
    document.addEventListener('mousedown', clic)
    window.addEventListener('scroll', fermer, true)
    window.addEventListener('resize', fermer)
    return () => {
      window.removeEventListener('keydown', touche); document.removeEventListener('mousedown', clic)
      window.removeEventListener('scroll', fermer, true); window.removeEventListener('resize', fermer)
    }
  }, [ouvert, fermer])

  return (
    <>
      <button ref={bouton} type="button" className={`info${ouvert ? ' ouvert' : ''}`} aria-label={titre}
        aria-expanded={ouvert} aria-describedby={ouvert ? id : undefined}
        onMouseEnter={ouvrir} onMouseLeave={fermerBientot} onFocus={ouvrir} onBlur={() => { if (!epingle) setOuvert(false) }}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (epingle) fermer(); else { setEpingle(true); ouvrir() } }}>
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <circle cx="8" cy="4.6" r="1" fill="currentColor" />
          <path d="M8 7.2v4.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
      {ouvert && createPortal(
        <div ref={bulle} id={id} role="tooltip" className={`infobulle${place?.dessous ? ' dessous' : ''}`}
          style={{ left: place?.left ?? -9999, top: place?.top ?? -9999, maxWidth: Math.min(LARGEUR, window.innerWidth - 2 * MARGE), visibility: place ? 'visible' : 'hidden' }}
          onMouseEnter={ouvrir} onMouseLeave={fermerBientot}>
          {children}
          <span className="infobulle-fleche" style={{ left: place?.fleche ?? 0 }} aria-hidden="true" />
        </div>,
        document.body,
      )}
    </>
  )
}
