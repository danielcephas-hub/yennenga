// Intro : à la première ouverture du lien, la démonstration vidéo en plein écran ; à la fin (ou « Passer »), la visite guidée.
// Les navigateurs interdisent le son avant un premier geste de la personne : on tente la lecture avec le son ;
// si elle est refusée, la vidéo attend derrière un grand bouton « Lancer la présentation », et ce clic la démarre avec le son.
import { useEffect, useRef, useState } from 'react'

export default function Intro({ fin }: { fin: () => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const lancer = useRef<HTMLButtonElement>(null)
  const passer = useRef<HTMLButtonElement>(null)
  const [attente, setAttente] = useState(false)
  const [progres, setProgres] = useState(0)

  useEffect(() => {
    const v = video.current
    if (v) {
      v.muted = false
      v.play().then(() => passer.current?.focus()).catch(() => { setAttente(true) })
    }
    const touche = (e: KeyboardEvent) => { if (e.key === 'Escape') fin() }
    window.addEventListener('keydown', touche)
    const debord = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', touche); document.body.style.overflow = debord }
  }, [fin])
  useEffect(() => { if (attente) lancer.current?.focus() }, [attente])

  const demarrer = () => {
    const v = video.current
    if (!v) return
    v.muted = false
    v.play().then(() => { setAttente(false); passer.current?.focus() }).catch(() => undefined)
  }

  return (
    <div className="intro-video" role="dialog" aria-modal="true" aria-label="Présentation de Yennenga en vidéo">
      <div className="intro-video-cadre">
        <video ref={video} src="/video/demonstration.mp4?v=4" poster="/video/demonstration.jpg" playsInline preload="auto"
          onEnded={fin} onTimeUpdate={(e) => setProgres(e.currentTarget.currentTime / (e.currentTarget.duration || 1))}
          onClick={(e) => { const v = e.currentTarget; if (v.paused) v.play().catch(() => undefined); else v.pause() }} />
        {attente && (
          <button ref={lancer} className="intro-video-lancer" onClick={demarrer}>
            <span className="demo-lecture" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="34" height="34"><path d="M8 5.5v13l11-6.5z" fill="currentColor" /></svg>
            </span>
            <span className="intro-video-lancer-texte">Lancer la présentation<small>2 min 38, avec le son · sous-titrée</small></span>
          </button>
        )}
        <div className="intro-video-progres" style={{ transform: `scaleX(${progres})` }} aria-hidden="true" />
      </div>
      <div className="intro-video-actions">
        <span className="intro-video-texte">Yennenga en vidéo · la visite guidée suit</span>
        <button ref={passer} className={attente ? 'secondaire' : 'principal'} onClick={fin}>{attente ? 'Passer la vidéo' : 'Passer à la visite →'}</button>
      </div>
    </div>
  )
}
