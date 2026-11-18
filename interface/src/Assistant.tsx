// Assistant Yennenga : « Posez votre question ». Il reconnaît la question et répond avec les chiffres et les calculs de l'outil,
// sans IA générative ni service extérieur. Quelques kilo-octets par question : adapté aux connexions lentes.
import { useEffect, useRef, useState } from 'react'
import { assistantDisponible, demanderAssistant, type ActionAssistant, type Demande, type MessageAssistant } from './api'
import { demander } from './visiteActions'
import Mascotte from './Mascotte'

// suggestions adaptées à la vue ouverte
const SUGGESTIONS: Record<string, string[]> = {
  carte: ['Quelles régions sont les plus touchées ?', 'Compare le Soum et le Loroum', 'Pourquoi le Loroum n\'est-il que 7e priorité ?', 'Élèves par enseignant au Bam depuis 2017'],
  repartition: ['Compare 2 000 et 3 000 enseignants', '20 ou 40 milliards, quelle différence ?', 'Pourquoi le Soum ne reçoit-il pas de salles ?', 'Comment est calculé le plan ?'],
  donnees: ['Comment mettre à jour les données ?', 'D\'où viennent les données ?', 'Que faire si une province change de nom ?'],
  methode: ['Comment est calculé le plan ?', 'Qu\'est-ce que l\'indice de besoin ?', 'Quelles sont les limites de l\'outil ?'],
  accueil: ['Quelles régions sont les plus touchées ?', 'Compare le Soum et le Loroum', 'Que se passe-t-il avec seulement 2 000 enseignants ?', 'Comment mettre à jour les données ?'],
}

type Ligne = MessageAssistant & { plan?: Demande | null; actions?: ActionAssistant[]; suggestions?: string[] }

export default function Assistant({ aller, vue = 'accueil' }: { aller: (vue: string) => void; vue?: string }) {
  const [actif, setActif] = useState(false)
  const [ouvert, setOuvert] = useState(false)
  const [lignes, setLignes] = useState<Ligne[]>([])
  const [texte, setTexte] = useState('')
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const fin = useRef<HTMLDivElement>(null)
  const champ = useRef<HTMLTextAreaElement>(null)
  const lanceur = useRef<HTMLButtonElement>(null)
  const dejaOuvert = useRef(false)

  useEffect(() => { assistantDisponible().then(setActif) }, [])
  useEffect(() => { fin.current?.scrollIntoView({ block: 'end' }) }, [lignes, attente])
  // dialogue : le curseur va dans le champ à l'ouverture ; à la fermeture, il revient au bouton qui l'a ouvert
  useEffect(() => {
    if (ouvert) { dejaOuvert.current = true; champ.current?.focus() }
    else if (dejaOuvert.current) lanceur.current?.focus()
  }, [ouvert])
  useEffect(() => {
    if (!ouvert) return
    const touche = (e: KeyboardEvent) => { if (e.key === 'Escape') setOuvert(false) }
    window.addEventListener('keydown', touche)
    return () => window.removeEventListener('keydown', touche)
  }, [ouvert])
  if (!actif) return null

  const envoyer = (q: string) => {
    const question = q.trim()
    if (!question || attente) return
    const suite: Ligne[] = [...lignes, { role: 'user', content: question }]
    setLignes(suite); setTexte(''); setAttente(true); setErreur(null)
    demanderAssistant(suite.map(({ role, content }) => ({ role, content })))
      .then((r) => setLignes([...suite, { role: 'assistant', content: r.reponse, plan: r.plan, actions: r.actions, suggestions: r.suggestions }]))
      .catch((e) => { setErreur(String(e.message)); setLignes(lignes) ; setTexte(question) })
      .finally(() => setAttente(false))
  }

  const ouvrirPlan = (p: Demande) => { aller('repartition'); demander({ action: 'plan', arg: JSON.stringify(p) }) }

  return (
    <>
      {!ouvert && (
        <div className="assistant-lanceur">
          <button className="mascotte-bouton" ref={lanceur} onClick={() => setOuvert(true)} aria-label="Ouvrir l'assistant Yennenga : poser une question" title="Bonjour ! Une question sur les enseignants ou les salles ?">
            <Mascotte taille={58} />
          </button>
          <button className="assistant-bouton principal" onClick={() => setOuvert(true)} tabIndex={-1} aria-hidden="true">Poser une question</button>
        </div>
      )}
      {ouvert && (
        <section className="assistant" role="dialog" aria-modal="false" aria-label="Assistant Yennenga">
          <header>
            <span className="assistant-titre"><Mascotte taille={30} parle={attente} /><b>Assistant Yennenga</b></span>
            <button className="lien fermer-assistant" onClick={() => setOuvert(false)} aria-label="Fermer l'assistant (Échap)">×</button>
          </header>
          <div className="assistant-fil" aria-live="polite">
            <p className="petit">Il répond avec les chiffres et les calculs de l'outil, et indique leur source. Il comprend les questions sur une province ou une commune, un classement, un plan avec vos moyens, ou le sens d'un terme. La décision reste la vôtre.</p>
            {lignes.length === 0 && (
              <div className="assistant-suggestions">
                {(SUGGESTIONS[vue] ?? SUGGESTIONS.accueil).map((s) => <button key={s} className="secondaire" onClick={() => envoyer(s)}>{s}</button>)}
              </div>
            )}
            {lignes.map((l, i) => (
              <div key={i} className={`bulle-msg msg-${l.role}`}>
                {l.content.split('\n').filter(Boolean).map((p, j) => <p key={j}>{p}</p>)}
                {l.plan && <button className="lien" onClick={() => ouvrirPlan(l.plan!)}>Ouvrir ce plan dans Répartition →</button>}
                {(l.actions ?? []).map((a) => (
                  <button key={a.libelle} className="lien" onClick={() => { aller(a.vue); if (a.action) demander({ action: a.action, arg: a.arg }) }}>{a.libelle} →</button>
                ))}
                {i === lignes.length - 1 && (l.suggestions?.length ?? 0) > 0 && (
                  <div className="assistant-relances" aria-label="Questions suivantes">
                    {l.suggestions!.map((s) => <button key={s} className="relance" onClick={() => envoyer(s)}>{s}</button>)}
                  </div>
                )}
              </div>
            ))}
            {attente && <p className="petit">Calcul en cours…</p>}
            {erreur && <p className="erreur" role="alert">{navigator.onLine ? `L'assistant ne répond pas pour le moment (${erreur}).` : 'Hors ligne : l\'assistant demande le réseau.'} Votre question est restée dans le champ : renvoyez-la quand vous voulez.</p>}
            <div ref={fin} />
          </div>
          <form onSubmit={(e) => { e.preventDefault(); envoyer(texte) }}>
            <textarea ref={champ} value={texte} maxLength={600} rows={2} placeholder="Votre question…" aria-label="Votre question"
              onChange={(e) => setTexte(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); envoyer(texte) } }} />
            <button className="principal" disabled={attente || !texte.trim()}>Envoyer</button>
          </form>
        </section>
      )}
    </>
  )
}
