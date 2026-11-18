// Accès aux données et au service de calcul. Aucune donnée n'est calculée ici : tout vient de la chaîne Python.

export type Meta = {
  annee_reference: string
  annee_horizon: string
  normes: { eleves_par_maitre: number; eleves_par_salle: number }
  couts: { salle: number; enseignant: number; annees_budget: number; salle_complexe?: number }
  defauts: { enseignants: number; salles: number }
  implantation: { rayon_km: number; seuil_enfants_site: number; seuil_fermeture_rouvrir: number }
  national: {
    enfants_6_11_horizon: number
    communes: number
    eloignes_basse: number
    eloignes_haute: number
    sites: number
    sites_construire: number
    pdi: number
    communes_pdi_relevees?: number
  }
  noms?: Record<string, string>
  indice?: { ponderations: Record<string, number>; dimensions: Record<string, string[]>; plage_surcharge: [number, number]; seuil_changement_tiers: number; tirages: number }
  validation?: { rapprochement?: { identiques: number; total: number }; prevision?: { erreur_1an: number; erreur_max: number; horizon_max: number; reference_max: number }; scenarios?: { optimaux: number; total: number }; tests?: number | null }
  prive?: { part: number; province_max: string; part_max: number; provinces_sans: string[] }
  scenarios?: { eleves_tendance: number; eleves_reouverture: number; provinces_choc: number; rattrapage: number; choc_seuil: number; choc_depuis: number }
  plan_reference?: { enseignants: number; salles: number; salles_rouvertes: number; pire_avant: number; pire_optimisee: number; pire_proportionnelle: number; pire_besoins?: number
    surnombre_optimisee?: number; surnombre_proportionnelle?: number; surnombre_besoins?: number; surnombre_avant?: number; cout_fcfa?: number
    province_pire_avant?: string; province_pire_avant_apres?: Record<string, number>; province_pire_apres?: string; province_pire_apres_ratio?: number
    atouts?: { budget?: { budget_md: number; pire_optimisee: number; pire_besoins: number }[]
      mutations?: { recrues: number; salles: number; mutations_max: number; mutes: number; trop_optimisee: number; trop_besoins: number; pire_optimisee: number; pire_besoins: number } }
    gini_optimisee?: number; gini_besoins?: number; gini_proportionnelle?: number
    retrospectif?: { origine: string; fin: string; enseignants: number; salles: number; surnombre_reel: number; surnombre_outil: number; ecart: number }[] }
}

// chiffres observés d'une province une année donnée (annuaires) : public, privé, total
export type Obs = { e: number | null; m: number | null; s: number | null; ec: number | null; prec: number | null; f?: number; g?: number }
export type ProvAnnee = { pu?: Obs; pr?: Obs; t?: Obs }
export type Annees = { annees: string[]; valeurs: Record<string, Record<string, ProvAnnee>> }

export type Province = {
  province: string
  region: string
  eleves: number
  maitres: number
  salles: number
  ecoles: number
  eleves_par_maitre: number | null
  eleves_par_salle: number | null
  part_salles_precaires: number | null
  maitres_manquants: number
  salles_manquantes: number
  part_du_pic: number | null
  part_ecoles_fermees: number | null
  indice_besoin: number | null
  score_surcharge?: number | null
  score_bati?: number | null
  rang: number | null
  rang_p05: number | null
  rang_p95: number | null
  rang_instable: boolean | null
  eleves_horizon: number | null
  construction_possible: boolean | null
  enseignants_attribues: number | null
  salles_attribuees: number | null
  salles_rouvertes?: number | null
  ratio_maitre_apres: number | null
  serie: [number, number][]
  prevision: Record<string, [number, number, number, number][]>
}

export type Commune = {
  pcode_commune: string
  commune: string
  province: string
  region: string
  province_ancienne: string
  lat: number
  lon: number
  superficie_km2: number
  population_2019: number
  enfants_6_11_2019: number
  enfants_6_11_2030: number
  sites_scolaires_osm: number
  pdi_total: number | null
  pdi_releve?: boolean
  part_pdi_population: number
  population_estimee_insd: string | null
  eloignes_borne_haute: number | null
  eloignes_borne_basse: number | null
  part_eloignes_haute: number | null
  part_eloignes_basse: number | null
  part_ecoles_fermees_province: number | null
  construction_programmee: boolean | null
}

export type Site = {
  rang: number
  lon: number
  lat: number
  pcode_commune: string
  enfants_rapproches: number
  commune: string
  province: string
  region: string
  part_ecoles_fermees_province: number
  recommandation: string
}

export type Bornes = { min_enseignants?: number; max_enseignants?: number; min_salles?: number; max_salles?: number }

export type Demande = {
  enseignants?: number
  salles?: number
  budget_fcfa?: number
  budget_seul?: boolean
  scenario?: string
  eleves_par_maitre?: number
  redeploiement?: number
  cout_salle?: 'salle' | 'complexe'
  recul_prive?: number
  provinces?: Record<string, Bornes>
  regions?: Record<string, Bornes>
}

export type LigneRepartition = {
  province: string
  region: string
  eleves_horizon: number
  maitres: number
  salles: number
  enseignants_attribues: number
  salles_attribuees: number
  ratio_maitre_apres: number | null
  ratio_salle_apres: number | null
  construction_possible: boolean
  acces_construction?: boolean
  rouvrir_d_abord?: boolean
  part_ecoles_fermees?: number | null
  salles_a_rouvrir?: number
  salles_rouvertes?: number | null
  solde_redeploiement?: number | null
  motif?: string | null
}

export type Bilan = {
  methode: string
  enseignants_attribues: number
  salles_attribuees: number
  salles_rouvertes?: number
  eleves_au_dela_norme_maitre: number
  eleves_au_dela_norme_salle: number
  provinces_au_dessus_norme_maitre: number
  pire_ratio_eleves_maitre: number
  gini_ratio_maitre: number
  part_eleves_province_conforme: number
}

export type Resultat = {
  statut: string
  duree_s: number
  horizon: string
  scenario: string
  recul_prive?: number
  eleves_horizon_public?: number
  norme_eleves_par_maitre: number
  enseignants_utilises: number
  salles_utilisees: number
  enseignants_redeployes?: number
  cout_fcfa: number
  cout_salle_fcfa?: number
  cout_salles_fcfa?: number
  salaires_annuels_fcfa?: number
  annees_budget?: number
  mouvements?: { de: string; vers: string; enseignants: number; distance_km: number }[]
  bilan: Bilan[]
  repartitions: Record<string, LigneRepartition[]>
}

export type Etat = {
  annee_reference: string
  horizon: string
  provinces: string[]
  regions: string[]
  scenarios: string[]
  defauts: { enseignants: number; salles: number }
  limites: { enseignants_max: number; salles_max: number; budget_max_fcfa: number; normes_acceptees: number[]; recul_prive_max?: number }
}

export type Lot = {
  lot: number
  type_donnee: string
  fichier: string
  decoupage: string
  annees: string
  lignes: number
  auteur: string
  depose_le: string
  statut: string
}

export type TypeDonnee = { libelle: string; niveau: string; source_habituelle: string; variables: Record<string, string> }

export type Rapport = {
  accepte: boolean
  decoupage: string
  decoupage_libelle?: string
  lignes: number
  annees: string[]
  bloquants: string[]
  avertissements: string[]
  apercu?: string[]
  lot?: number | null
  suite?: string
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = `${r.status}`
    try {
      const j = await r.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* réponse sans corps JSON */
    }
    throw new Error(detail)
  }
  return r.json() as Promise<T>
}

const cache = new Map<string, Promise<unknown>>()
export function donnees<T>(nom: string): Promise<T> {
  if (!cache.has(nom)) {
    const p = fetch(`/api/donnees/${nom}.json`).then((r) => json<T>(r))
    p.catch(() => cache.delete(nom)) // un échec réseau n'est pas mémorisé : recharger la page suffit
    cache.set(nom, p)
  }
  return cache.get(nom) as Promise<T>
}

export const etat = () => fetch('/api/etat').then((r) => json<Etat>(r))

export const repartir = (d: Demande) =>
  fetch('/api/repartir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d) }).then((r) =>
    json<Resultat>(r),
  )

export async function repartirExcel(d: Demande): Promise<{ blob: Blob; nom: string }> {
  const r = await fetch('/api/repartir.xlsx', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d) })
  if (!r.ok) await json(r)
  const nom = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') ?? '')?.[1] ?? 'plan_repartition.xlsx'
  return { blob: await r.blob(), nom }
}

export const lots = () => fetch('/api/entrepot/lots').then((r) => json<Lot[]>(r))
export const typesDonnees = () => fetch('/api/entrepot/types').then((r) => json<Record<string, TypeDonnee>>(r))

export function controler(type: string, fichier: File) {
  const f = new FormData()
  f.append('type_donnee', type)
  f.append('fichier', fichier)
  return fetch('/api/entrepot/controler', { method: 'POST', body: f }).then((r) => json<Rapport>(r))
}

export function retirerLot(lot: number, auteur: string, jeton: string) {
  const f = new FormData()
  f.append('lot', String(lot))
  f.append('auteur', auteur)
  return fetch('/api/entrepot/retirer', { method: 'POST', body: f, headers: { Authorization: `Bearer ${jeton}` } })
    .then((r) => json<{ lot: number; statut: string; suite: string }>(r))
}

export function importer(type: string, fichier: File, auteur: string, jeton: string) {
  const f = new FormData()
  f.append('type_donnee', type)
  f.append('auteur', auteur)
  f.append('fichier', fichier)
  return fetch('/api/entrepot/importer', { method: 'POST', body: f, headers: { Authorization: `Bearer ${jeton}` } }).then((r) =>
    json<Rapport>(r),
  )
}

// assistant : bouton d'action proposé avec une réponse (ouvrir un onglet, voir un lieu sur la carte)
export type ActionAssistant = { libelle: string; vue: string; action?: 'province' | 'communes'; arg?: string }

// assistant IA : désactivé tant que le serveur ne l'a pas activé
export type MessageAssistant = { role: 'user' | 'assistant'; content: string }
export function assistantDisponible() {
  return fetch('/api/assistant').then((r) => json<{ disponible: boolean }>(r)).then((x) => x.disponible).catch(() => false)
}
export function demanderAssistant(messages: MessageAssistant[]) {
  return fetch('/api/assistant', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages }) })
    .then((r) => json<{ reponse: string; plan: Demande | null; outils: string[]; actions?: ActionAssistant[]; suggestions?: string[] }>(r))
}
