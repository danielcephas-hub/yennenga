// Extraction des données d'une fiche (province ou commune) en fichier CSV lisible par Excel : séparateur « ; »,
// virgule décimale, encodage UTF-8 avec marque d'ordre (accents corrects à l'ouverture). Construit dans le navigateur :
// rien à calculer sur le serveur, fonctionne aussi en mode léger.
import { donnees, type Annees, type Commune, type Meta, type Province, type Site } from './api'
import { joli } from './format'

type Cellule = string | number | null | undefined
const cellule = (v: Cellule): string => {
  if (v == null || (typeof v === 'number' && !Number.isFinite(v))) return ''
  // ratios et effectifs à une décimale ; parts (entre 0 et 1) et notes à trois décimales
  const s = typeof v === 'number' ? String(Math.abs(v) >= 10 ? Math.round(v * 10) / 10 : Math.round(v * 1000) / 1000).replace('.', ',') : v
  return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
const ratio = (a?: number | null, b?: number | null) => (a != null && b ? a / b : null)

function telecharger(nom: string, lignes: Cellule[][]) {
  const texte = '﻿' + lignes.map((l) => l.map(cellule).join(';')).join('\r\n')
  const url = URL.createObjectURL(new Blob([texte], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = nom
  a.click()
  URL.revokeObjectURL(url)
}

const fichier = (nom: string) => nom.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '')

export async function exporterProvince(p: Province, meta: Meta, obs: Annees | null) {
  const ref = meta.annee_reference, h = meta.annee_horizon.slice(0, 4)
  const src = `Annuaire DGESS ${ref}`
  const L: Cellule[][] = [
    [`Yennenga · fiche de la province ${joli(p.province)} (région ${joli(p.region)})`],
    [`Extraite le ${new Date().toLocaleDateString('fr-FR')} · public = écoles publiques ; total = public et privé`],
    [],
    ['Rubrique', 'Indicateur', 'Valeur', 'Année', 'Source'],
    ['Écoles publiques', 'Élèves', p.eleves, ref, src],
    ['Écoles publiques', 'Enseignants', p.maitres, ref, src],
    ['Écoles publiques', 'Salles de classe', p.salles, ref, src],
    ['Écoles publiques', 'Écoles', p.ecoles, ref, src],
    ['Écoles publiques', 'Élèves par enseignant', p.eleves_par_maitre, ref, `${src} ; norme ${meta.normes.eleves_par_maitre}`],
    ['Écoles publiques', 'Élèves par salle', p.eleves_par_salle, ref, src],
    ['Écoles publiques', 'Part des salles en paille ou banco', p.part_salles_precaires, ref, src],
    ['Écoles publiques', 'Enseignants manquants pour atteindre la norme', p.maitres_manquants, ref, 'Calcul de l\'outil'],
    ['Écoles publiques', 'Salles manquantes pour atteindre la norme', p.salles_manquantes, ref, 'Calcul de l\'outil'],
    ['Priorité', 'Indice de besoin (0 = mieux placée, 1 = plus en difficulté)', p.indice_besoin, ref, 'Calcul de l\'outil (surcharge 70 %, bâti 30 %)'],
    ['Priorité', 'Note de surcharge (0 à 1)', p.score_surcharge, ref, 'Calcul de l\'outil'],
    ['Priorité', 'Note du bâti (0 à 1)', p.score_bati, ref, 'Calcul de l\'outil'],
    ['Priorité', 'Rang de priorité sur 45 (1 = la plus en difficulté)', p.rang, ref, 'Calcul de l\'outil'],
    ['Priorité', 'Rang le plus favorable selon les poids', p.rang_p05, ref, 'Calcul de l\'outil (1 000 essais)'],
    ['Priorité', 'Rang le moins favorable selon les poids', p.rang_p95, ref, 'Calcul de l\'outil (1 000 essais)'],
    ['Priorité', 'Classement à confirmer', p.rang_instable ? 'oui' : 'non', ref, 'Calcul de l\'outil'],
    ['Écoles', 'Part des écoles fermées depuis le plus haut niveau 2017-2025', p.part_ecoles_fermees, ref, 'Annuaires DGESS, public et privé'],
    ['Écoles', 'Construction de salles possible', p.construction_possible === false ? 'non (rouvrir d\'abord ou accès trop difficile)' : 'oui', ref, 'Règle de l\'outil'],
    ['Prévision', `Élèves du public attendus à la rentrée ${h}`, p.eleves_horizon, h, 'Prévision de l\'outil'],
    ['Plan type', `Enseignants reçus (plan de ${meta.defauts.enseignants} enseignants et ${meta.defauts.salles} salles)`, p.enseignants_attribues, h, 'Calcul de l\'outil'],
    ['Plan type', 'Salles reçues', p.salles_attribuees, h, 'Calcul de l\'outil'],
    ['Plan type', 'Salles d\'écoles fermées à rouvrir', p.salles_rouvertes, h, 'Calcul de l\'outil'],
    ['Plan type', `Élèves par enseignant à la rentrée ${h}, avec ce plan`, p.ratio_maitre_apres, h, 'Calcul de l\'outil'],
  ]
  if (obs) {
    L.push([], ['Évolution par année (annuaires DGESS)'],
      ['Année', 'Élèves public', 'Enseignants public', 'Salles public', 'Écoles public', 'Élèves par enseignant (public)', 'Élèves par salle (public)',
        'Salles en paille ou banco (public)', 'Élèves privé', 'Enseignants privé', 'Écoles privé', 'Part du privé', 'Élèves total', 'Filles', 'Garçons', 'Filles pour 100 garçons'])
    for (const an of obs.annees) {
      const o = obs.valeurs[an]?.[p.province]
      if (!o) continue
      L.push([an, o.pu?.e, o.pu?.m, o.pu?.s, o.pu?.ec, ratio(o.pu?.e, o.pu?.m), ratio(o.pu?.e, o.pu?.s), o.pu?.prec, o.pr?.e, o.pr?.m, o.pr?.ec,
        ratio(o.pr?.e ?? 0, o.t?.e), o.t?.e, o.t?.f, o.t?.g, o.t?.f != null && o.t?.g ? (100 * o.t.f) / o.t.g : null])
    }
  }
  L.push([], ['Élèves inscrits, public et privé (série longue des annuaires)'], ['Année scolaire (début)', 'Élèves'], ...p.serie.map(([a, e]) => [a, e]))
  L.push([], ['Prévision des élèves (public et privé), avec sa marge'], ['Scénario', 'Année scolaire (début)', 'Élèves prévus', 'Borne basse', 'Borne haute'])
  for (const [sc, lignes] of Object.entries(p.prevision)) {
    const lib = sc === 'tendance' ? 'Tendance actuelle' : sc === 'reouverture' ? 'Si les écoles fermées rouvrent' : sc
    for (const [a, v, b, hh] of lignes) L.push([lib, a, v, b, hh])
  }
  // le détail : communes de la province, sites proposés, écoles repérées (téléchargés seulement au moment de l'extraction)
  const [communes, sites, ecoles] = await Promise.all([donnees<Commune[]>('communes'), donnees<Site[]>('sites'), lireEcoles()])
  const cs = communes.filter((c) => c.province_ancienne === p.province).sort((a, b) => a.commune.localeCompare(b.commune, 'fr'))
  const codes = new Set(cs.map((c) => c.pcode_commune))
  const nomCommune = Object.fromEntries(cs.map((c) => [c.pcode_commune, c.commune]))
  L.push([], [`Communes de la province (${cs.length})`], ENTETE_COMMUNES, ...cs.map((c) => ligneCommune(c, sites)))
  ajouterSites(L, sites.filter((x) => codes.has(x.pcode_commune)), nomCommune)
  ajouterEcoles(L, ecoles.filter((e) => e[0] && codes.has(e[0])), nomCommune)
  telecharger(`yennenga_province_${fichier(joli(p.province))}.csv`, L)
}

export async function exporterCommune(c: Commune, sites: Site[], meta: Meta) {
  const h = meta.annee_horizon.slice(0, 4)
  const L: Cellule[][] = [
    [`Yennenga · fiche de la commune ${c.commune} (province ${c.province}, région ${c.region} ; ${joli(c.province_ancienne)} dans les annuaires)`],
    [`Extraite le ${new Date().toLocaleDateString('fr-FR')} · code ${c.pcode_commune}`],
    [],
    ['Rubrique', 'Indicateur', 'Valeur', 'Année', 'Source'],
    ['Population', 'Habitants', c.population_2019, '2019', 'Recensement général (RGPH) 2019, INSD'],
    ['Population', 'Enfants de 6 à 11 ans', c.enfants_6_11_2019, '2019', 'RGPH 2019, INSD'],
    ['Population', 'Enfants de 6 à 11 ans attendus', c.enfants_6_11_2030, h, 'Projection INSD de la province répartie selon la part de la commune'],
    ['Population', 'Superficie (km²)', c.superficie_km2, '', 'OCHA COD-AB'],
    ['Accès à l\'école', `Enfants à plus de ${meta.implantation.rayon_km} km d'une école, au minimum`, c.eloignes_borne_basse == null ? null : Math.round(c.eloignes_borne_basse), h, 'WorldPop calé sur l\'INSD ; écoles manquantes placées au plus près'],
    ['Accès à l\'école', 'Part de ces enfants, au minimum', c.part_eloignes_basse, h, 'Calcul de l\'outil'],
    ['Accès à l\'école', `Enfants à plus de ${meta.implantation.rayon_km} km d'une école, au maximum`, c.eloignes_borne_haute == null ? null : Math.round(c.eloignes_borne_haute), h, 'Seules écoles repérées sur OpenStreetMap'],
    ['Accès à l\'école', 'Part de ces enfants, au maximum', c.part_eloignes_haute, h, 'Calcul de l\'outil'],
    ['Accès à l\'école', 'Écoles repérées sur OpenStreetMap', c.sites_scolaires_osm, '', 'OpenStreetMap (liste partielle)'],
    ['Contexte', 'Personnes déplacées accueillies', c.pdi_releve === false ? 'non relevé' : c.pdi_total, 'fin 2022', 'CONASUR'],
    ['Contexte', 'Déplacés rapportés à la population de 2019', c.part_pdi_population, 'fin 2022', 'CONASUR, INSD'],
    ['Contexte', 'Part des écoles fermées dans la province', c.part_ecoles_fermees_province, meta.annee_reference, 'Annuaires DGESS'],
    ['Contexte', 'Construction programmée dans la province', c.construction_programmee === false ? 'non' : 'oui', '', 'Règle de l\'outil'],
  ]
  const nomCommune = { [c.pcode_commune]: c.commune }
  ajouterSites(L, sites, nomCommune)
  ajouterEcoles(L, (await lireEcoles()).filter((e) => e[0] === c.pcode_commune), nomCommune)
  telecharger(`yennenga_commune_${fichier(c.commune)}.csv`, L)
}

// --- sections de détail communes aux deux extractions ---

type Ecole = [string | null, string | null, number, number, number]  // commune, nom, latitude, longitude, objets regroupés
const lireEcoles = () => donnees<Ecole[]>('ecoles').catch(() => [] as Ecole[])

const ENTETE_COMMUNES = ['Commune', 'Code', 'Province (2025)', 'Habitants 2019', 'Enfants 6-11 ans 2019', 'Enfants 6-11 ans 2030',
  'Enfants à plus de 3 km, au minimum', 'Enfants à plus de 3 km, au maximum', 'Écoles repérées (OSM)', 'Déplacés fin 2022', 'Sites proposés']

function ligneCommune(c: Commune, sites: Site[]): Cellule[] {
  const r = (v: number | null) => (v == null ? null : Math.round(v))
  return [c.commune, c.pcode_commune, c.province, c.population_2019, c.enfants_6_11_2019, c.enfants_6_11_2030, r(c.eloignes_borne_basse),
    r(c.eloignes_borne_haute), c.sites_scolaires_osm, c.pdi_releve === false ? 'non relevé' : c.pdi_total,
    sites.filter((s) => s.pcode_commune === c.pcode_commune).length]
}

function ajouterSites(L: Cellule[][], sites: Site[], nomCommune: Record<string, string>) {
  L.push([], [`Sites proposés pour une école (${sites.length}) : mailles de 1 km qui rapprochent le plus d'enfants restés à plus de 3 km d'une école ; à vérifier sur le terrain`],
    ['Rang national', 'Commune', 'Recommandation', 'Enfants rapprochés', 'Latitude', 'Longitude'])
  if (!sites.length) L.push(['aucun'])
  for (const s of [...sites].sort((a, b) => a.rang - b.rang)) L.push([s.rang, nomCommune[s.pcode_commune] ?? s.commune, s.recommandation, s.enfants_rapproches, s.lat, s.lon])
}

function ajouterEcoles(L: Cellule[][], ecoles: Ecole[], nomCommune: Record<string, string>) {
  const nommees = ecoles.filter((e) => e[1]).length
  L.push([], [`Écoles repérées sur OpenStreetMap (${ecoles.length}, dont ${nommees} avec un nom) : liste PARTIELLE (environ un tiers des écoles de l'annuaire), tous établissements d'enseignement confondus (primaire, collèges, lycées) ; © contributeurs OpenStreetMap (ODbL)`],
    ['Nom', 'Commune', 'Latitude', 'Longitude', 'Bâtiments ou objets regroupés'])
  if (!ecoles.length) L.push(['aucune école repérée'])
  // par commune, puis les écoles nommées par ordre alphabétique, les écoles sans nom à la fin
  const tri = [...ecoles].sort((a, b) => (nomCommune[a[0] ?? ''] ?? '').localeCompare(nomCommune[b[0] ?? ''] ?? '', 'fr')
    || Number(!a[1]) - Number(!b[1]) || (a[1] ?? '').localeCompare(b[1] ?? '', 'fr'))
  for (const e of tri) L.push([e[1] ?? '(sans nom)', nomCommune[e[0] ?? ''] ?? '', e[2], e[3], e[4]])
}
