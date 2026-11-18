// Mise en forme française des nombres et noms.

const fr0 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const fr1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

export const nb = (x: number | null | undefined, d = 0) =>
  x == null || Number.isNaN(x) ? '—' : d === 0 ? fr0.format(x) : d === 1 ? fr1.format(x) : x.toFixed(d).replace('.', ',')

export const pct = (x: number | null | undefined, d = 0) => (x == null || Number.isNaN(x) ? '—' : `${nb(100 * x, d)} %`)

export const mds = (fcfa: number) => `${nb(fcfa / 1e9, 1)} Md FCFA`

// noms officiels (accents, traits d'union) fournis par le serveur : « SENO » -> « Séno »
let NOMS: Record<string, string> = {}
export function definirNoms(n: Record<string, string> | undefined) { NOMS = n ?? {} }

/** « BOUCLE DU MOUHOUN » -> « Boucle du Mouhoun » (noms des annuaires, en majuscules sans accent). */
export function joli(nom: string): string {
  if (!nom) return ''
  if (NOMS[nom]) return NOMS[nom]
  if (nom !== nom.toUpperCase()) return nom
  const petits = new Set(['du', 'de', 'des', 'la', 'le', 'les'])
  return nom
    .toLowerCase()
    .split(/(\s|-)/)
    .map((m, i) => (i > 0 && petits.has(m) ? m : m.charAt(0).toUpperCase() + m.slice(1)))
    .join('')
}

export const cleNom = (s: string) =>
  s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .replace(/[^A-Z]/g, '')

/** Statut du solveur en langage clair. */
export const statutClair = (s: string) =>
  s === 'Optimal' ? 'meilleur plan possible (vérifié par le calcul)'
    : s === 'Non prouvé optimal' ? 'meilleur plan trouvé dans le temps de calcul' : s.toLowerCase()
