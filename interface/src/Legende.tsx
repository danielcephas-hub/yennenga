// Légende, classes de couleurs et types communs aux cartes : sans le moteur de carte (MapLibre, 250 ko),
// pour que le mode léger et les listes n'aient pas à le télécharger.

export type Classes = { bornes: number[]; couleurs: string[] } // couleurs.length === bornes.length + 1

export type Point = { id: string; lon: number; lat: number; couleur: string; taille: number; titre: string; creux?: boolean; ordre?: number }

export const SANS_DONNEE = '#9ea39f' // gris moyen : ne se confond ni avec la classe la plus claire ni avec le fond

/** Couleur de la classe d'une valeur (même règle que la carte). */
export function couleurDe(c: Classes, v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return SANS_DONNEE
  const i = c.bornes.findIndex((b) => v < b)
  return c.couleurs[i === -1 ? c.bornes.length : i]
}

export function Legende({ classes, format, titre }: { classes: Classes; format: (x: number) => string; titre: string }) {
  const lib = classes.couleurs.map((_, i) =>
    i === 0 ? `moins de ${format(classes.bornes[0])}` : i === classes.bornes.length ? `${format(classes.bornes[i - 1])} et plus`
      : `${format(classes.bornes[i - 1])} à ${format(classes.bornes[i])}`,
  )
  return (
    <div className="legende">
      <div className="legende-titre">{titre}</div>
      {classes.couleurs.map((c, i) => (
        <div key={c + i} className="legende-ligne"><span className="pastille" style={{ background: c }} />{lib[i]}</div>
      ))}
      <div className="legende-ligne"><span className="pastille" style={{ background: SANS_DONNEE }} />sans donnée</div>
    </div>
  )
}
