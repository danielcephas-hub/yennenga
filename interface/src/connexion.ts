// Mode léger : sur une connexion lente (ou en économie de données), les cartes cèdent la place à des listes
// et le moteur de carte n'est pas téléchargé. Le choix de l'utilisateur, s'il en a fait un, l'emporte.

const CLE = 'yennenga-leger'

type InfoReseau = { saveData?: boolean; effectiveType?: string }

export function connexionLente(): boolean {
  try {
    const v = localStorage.getItem(CLE)
    if (v === '1') return true
    if (v === '0') return false
  } catch { /* stockage indisponible : on s'en tient au réseau */ }
  const c = (navigator as Navigator & { connection?: InfoReseau }).connection
  return !!c && (c.saveData === true || c.effectiveType === 'slow-2g' || c.effectiveType === '2g')
}

export function setModeLeger(v: boolean) {
  try { localStorage.setItem(CLE, v ? '1' : '0') } catch { /* sans effet si le stockage est bloqué */ }
}
