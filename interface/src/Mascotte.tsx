// Mascotte de l'assistant : un petit personnage rond, tableau noir en guise de visage (l'école), antenne dorée.
// Dessin SVG dans le code : aucun fichier à télécharger, net à toutes les tailles. Clignement des yeux discret,
// coupé si l'utilisateur a demandé moins d'animations.

export default function Mascotte({ taille = 56, parle = false }: { taille?: number; parle?: boolean }) {
  return (
    <svg className={`mascotte${parle ? ' parle' : ''}`} width={taille} height={taille} viewBox="0 0 64 64" aria-hidden="true">
      {/* antenne */}
      <line x1="32" y1="9" x2="32" y2="15" stroke="#1f5c4a" strokeWidth="2.5" strokeLinecap="round" />
      <circle className="mascotte-antenne" cx="32" cy="7" r="3.6" fill="#f2c14e" />
      {/* corps */}
      <circle cx="32" cy="37" r="23" fill="#1f5c4a" />
      <ellipse cx="25" cy="25" rx="9" ry="5" fill="#ffffff" opacity="0.12" />
      {/* visage : un petit tableau d'école */}
      <rect x="16" y="25" width="32" height="21" rx="6" fill="#173f33" stroke="#f2c14e" strokeWidth="1.6" />
      <g className="mascotte-yeux">
        <ellipse cx="26" cy="33" rx="3" ry="3.4" fill="#ffffff" />
        <ellipse cx="38" cy="33" rx="3" ry="3.4" fill="#ffffff" />
      </g>
      <path className="mascotte-bouche" d="M27 39.5 Q32 43.5 37 39.5" stroke="#ffffff" strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* joues et bras */}
      <circle cx="21" cy="40" r="2" fill="#e3955a" opacity="0.8" />
      <circle cx="43" cy="40" r="2" fill="#e3955a" opacity="0.8" />
      <path className="mascotte-bras" d="M54 34 q6 -4 5 -11" stroke="#1f5c4a" strokeWidth="4" fill="none" strokeLinecap="round" />
    </svg>
  )
}
