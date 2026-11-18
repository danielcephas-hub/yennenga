// Indicateurs cartographiés : classes fixes, calées sur les normes quand il y en a (comparables d'une année à l'autre).
import type { Classes } from './Legende'
import type { Commune, ProvAnnee, Province } from './api'
import { nb, pct } from './format'

const CHAUD = ['#f6ecd2', '#f0c987', '#e3955a', '#c95b37', '#8e2f22'] // plus foncé = besoin plus fort
// élèves par enseignant : teinte froide sous la norme de 50, chaude au-dessus (la norme se voit sur la carte)
// le passage de la norme se voit aussi en clarté (vert clair → orange franc), pas seulement en teinte : lisible pour un daltonien et en gris
export const NORME_DIV = ['#3d7d70', '#a9cfc3', '#e3955a', '#c95b37', '#a8402b', '#6e2418']
const BLEU = ['#e8f0f4', '#b9d3e0', '#7fb0c8', '#3f86a8', '#1d5b7a']
export const ratio = (a?: number | null, b?: number | null) => (a != null && b ? a / b : null)

export type Indicateur<T> = {
  cle: string
  libelle: string
  aide: string
  valeur: (x: T) => number | null
  // indicateur observé chaque année dans les annuaires : la carte peut remonter le temps
  annuel?: (o: ProvAnnee) => number | null
  classes: Classes
  format: (x: number) => string
}

export const INDICATEURS_PROVINCE: Indicateur<Province>[] = [
  {
    cle: 'eleves_par_maitre', libelle: 'Élèves par enseignant', aide: 'Écoles publiques, année choisie (annuaire DGESS). Vert : à la norme de 50 ou en dessous ; orange à rouge : au-dessus.',
    valeur: (p) => p.eleves_par_maitre, annuel: (o) => ratio(o.pu?.e, o.pu?.m), classes: { bornes: [45, 50, 55, 60, 75], couleurs: NORME_DIV }, format: (x) => nb(x),
  },
  {
    cle: 'eleves_par_salle', libelle: 'Élèves par salle de classe', aide: 'Écoles publiques, année choisie (annuaire DGESS). Repère : 50, une classe par enseignant.',
    valeur: (p) => p.eleves_par_salle, annuel: (o) => ratio(o.pu?.e, o.pu?.s), classes: { bornes: [45, 50, 55, 60, 75], couleurs: NORME_DIV }, format: (x) => nb(x),
  },
  {
    cle: 'part_prive', libelle: 'Part du privé', aide: 'Élèves scolarisés dans le privé, année choisie (annuaire DGESS). L\'État n\'affecte que dans le public ; là où le privé est absent, il est le seul acteur, et si le privé recule, ses élèves se reportent vers le public.',
    valeur: () => null, annuel: (o) => ratio(o.pr?.e ?? 0, o.t?.e), classes: { bornes: [0.05, 0.15, 0.3, 0.5], couleurs: BLEU }, format: (x) => pct(x),
  },
  {
    cle: 'filles_pour_100', libelle: 'Filles pour 100 garçons inscrits', aide: 'Élèves du primaire, public et privé, année choisie (annuaires DGESS, tableaux rétrospectifs). 100 = autant de filles que de garçons ; plus la teinte est foncée, plus les filles manquent à l\'école.',
    valeur: () => null, annuel: (o) => (o.t?.f != null && o.t?.g ? (100 * o.t.f) / o.t.g : null),
    classes: { bornes: [85, 90, 95, 100], couleurs: [...CHAUD].reverse() }, format: (x) => nb(x),
  },
  {
    cle: 'part_salles_precaires', libelle: 'Salles en paille ou banco', aide: 'Part des salles des écoles publiques, année choisie (annuaire DGESS).',
    valeur: (p) => p.part_salles_precaires, annuel: (o) => o.pu?.prec ?? null, classes: { bornes: [0.02, 0.05, 0.1, 0.2], couleurs: CHAUD }, format: (x) => pct(x),
  },
  {
    cle: 'indice_besoin', libelle: 'Indice de besoin', aide: 'Calcul de l\'outil sur 2024-2025 : surcharge des classes (70 %) et état du bâti (30 %). 0 = la mieux placée des 45 provinces, 1 = la plus en difficulté. Détail dans la fiche.',
    valeur: (p) => p.indice_besoin, classes: { bornes: [0.3, 0.45, 0.6, 0.75], couleurs: CHAUD }, format: (x) => nb(x, 2),
  },
  {
    cle: 'part_ecoles_fermees', libelle: 'Écoles fermées', aide: 'Écoles qui ne fonctionnent plus : écoles ouvertes en 2024-2025 comparées à l\'année où la province en comptait le plus (2017 à 2025), public et privé. Au-delà de 20 %, l\'outil propose de rouvrir avant de construire.',
    valeur: (p) => p.part_ecoles_fermees, classes: { bornes: [0.05, 0.2, 0.4, 0.6], couleurs: CHAUD }, format: (x) => pct(x),
  },
  {
    cle: 'enseignants_pour_mille', libelle: 'Enseignants reçus dans un plan type', aide: 'Exemple calculé par l\'outil : 3 000 enseignants et 1 500 salles à répartir (réglages par défaut de l\'onglet Répartition). Enseignants reçus pour 1 000 élèves attendus en 2030 ; le nombre exact est dans la fiche.',
    valeur: (p) => (p.enseignants_attribues != null && p.eleves_horizon ? (1000 * p.enseignants_attribues) / p.eleves_horizon : null),
    classes: { bornes: [0.5, 2, 4, 8], couleurs: BLEU }, format: (x) => nb(x, 1),
  },
]

export const INDICATEURS_COMMUNE: Indicateur<Commune>[] = [
  {
    cle: 'part_eloignes_basse', libelle: 'Enfants à plus de 3 km d\'une école', aide: 'Au minimum : les écoles de l\'annuaire absentes des cartes (OpenStreetMap) sont supposées placées au plus près des enfants. Le maximum est dans la fiche. Population 2030 (WorldPop, calée sur l\'INSD).',
    valeur: (c) => c.part_eloignes_basse, classes: { bornes: [0.02, 0.05, 0.1, 0.2], couleurs: CHAUD }, format: (x) => pct(x),
  },
  {
    cle: 'enfants_6_11_2030', libelle: 'Enfants de 6 à 11 ans en 2030', aide: 'Recensement 2019 projeté avec la croissance INSD de la province. Effectif de la commune : les grandes communes ressortent par leur taille.',
    valeur: (c) => c.enfants_6_11_2030, classes: { bornes: [5000, 10000, 20000, 40000], couleurs: BLEU }, format: (x) => nb(x),
  },
  {
    cle: 'part_pdi_population', libelle: 'Déplacés accueillis', aide: 'Personnes déplacées internes (CONASUR, fin 2022) rapportées à la population de 2019. Gris : commune non relevée.',
    valeur: (c) => c.part_pdi_population, classes: { bornes: [0.02, 0.1, 0.2, 0.5], couleurs: CHAUD }, format: (x) => pct(x),
  },
  {
    cle: 'part_ecoles_fermees_province', libelle: 'Écoles fermées (province)', aide: 'Part des écoles fermées dans la province de la commune.',
    valeur: (c) => c.part_ecoles_fermees_province, classes: { bornes: [0.05, 0.2, 0.4, 0.6], couleurs: CHAUD }, format: (x) => pct(x),
  },
]

// sites : disque plein sombre = construire ; cercle violet = rouvrir d'abord (distincts aussi pour les daltoniens)
export const COULEUR_CONSTRUIRE = '#1b2420'
export const COULEUR_ROUVRIR = '#6d3fa0'
