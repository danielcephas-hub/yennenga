// Actions que la visite guidée demande aux vues : ouvrir une fiche, descendre aux communes, lancer un calcul.
// Une action est gardée en attente jusqu'à ce que la vue concernée soit affichée et la prenne.

export type ActionVisite = { action: 'province' | 'communes' | 'calculer' | 'plan'; arg?: string }

let attente: ActionVisite | null = null
const EVENEMENT = 'yennenga-visite'

export function demander(a: ActionVisite): void {
  attente = a
  window.dispatchEvent(new CustomEvent(EVENEMENT))
}

/** Prend l'action en attente si elle concerne cette vue. */
export function prendre(actions: ActionVisite['action'][]): ActionVisite | null {
  if (attente && actions.includes(attente.action)) {
    const a = attente
    attente = null
    return a
  }
  return null
}

/** Exécute `agir` pour toute action en attente (au montage de la vue, puis à chaque demande). */
export function ecouter(actions: ActionVisite['action'][], agir: (a: ActionVisite) => void): () => void {
  const essayer = () => { const a = prendre(actions); if (a) agir(a) }
  essayer()
  window.addEventListener(EVENEMENT, essayer)
  return () => window.removeEventListener(EVENEMENT, essayer)
}
