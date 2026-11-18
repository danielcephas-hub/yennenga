// Vue « Répartition » : le décideur fixe ses moyens et ses contraintes, le serveur calcule le plan optimal en direct.
import { Suspense, lazy, useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { ecouter, prendre } from './visiteActions'
import Aide from './Aide'
import AvantApres from './AvantApres'
import { Legende } from './Legende'
import { connexionLente, setModeLeger } from './connexion'

// le moteur de carte (250 ko) n'est téléchargé que si la carte s'affiche
const Carte = lazy(() => import('./Carte'))
import { donnees, etat as lireEtat, repartir, repartirExcel, type Bornes, type Demande, type Etat, type LigneRepartition, type Meta, type Resultat } from './api'
import { joli, mds, nb, pct, statutClair } from './format'

type Contrainte = { niveau: 'provinces' | 'regions'; nom: string; cle: keyof Bornes; valeur: number }

type Reglages = {
  scenario: string; norme: number; redep: number; coutSalle: 'salle' | 'complexe'; reculPrive: number
  mode: 'moyens' | 'budget'; n: number; m: number; budget: number; contraintes: Contrainte[]
}

// la demande envoyée au calcul, toujours construite de la même façon (sert aussi à repérer un plan périmé)
function construire(v: Reglages): Demande {
  const d: Demande = { scenario: v.scenario, eleves_par_maitre: v.norme, redeploiement: v.redep, cout_salle: v.coutSalle, recul_prive: v.reculPrive, provinces: {}, regions: {} }
  if (v.mode === 'moyens') { d.enseignants = v.n; d.salles = v.m } else { d.budget_seul = true; d.budget_fcfa = v.budget * 1e9 }
  for (const c of v.contraintes) {
    const cible = (d[c.niveau] ??= {})
    cible[c.nom] = { ...(cible[c.nom] ?? {}), [c.cle]: c.valeur }
  }
  return d
}

const LIB_METHODE: Record<string, string> = {
  sans_moyens_nouveaux: 'Sans moyens nouveaux',
  proportionnelle: 'Partage selon le nombre d\'élèves',
  besoins: 'Partage selon les manques',
  optimisee: 'Plan Yennenga',
}
const LIB_BORNE: Record<keyof Bornes, string> = {
  min_enseignants: 'au moins … enseignants', max_enseignants: 'au plus … enseignants',
  min_salles: 'au moins … salles', max_salles: 'au plus … salles',
}
// après répartition, les provinces se resserrent entre 50 et 60 : classes fines autour de la norme, vert en dessous
const CLASSES_RATIO = { bornes: [45, 50, 55, 60], couleurs: ['#3d7d70', '#a9cfc3', '#e3955a', '#c95b37', '#8e2f22'] }

export default function VueRepartition({ meta }: { meta: Meta }) {
  const [etat, setEtat] = useState<Etat | null>(null)
  const [mode, setMode] = useState<'moyens' | 'budget'>('moyens')
  const [n, setN] = useState(meta.defauts.enseignants)
  const [m, setM] = useState(meta.defauts.salles)
  const [budget, setBudget] = useState(20)
  const [scenario, setScenario] = useState('tendance')
  const [norme, setNorme] = useState(meta.normes.eleves_par_maitre)
  const [redep, setRedep] = useState(0)
  const [reculPrive, setReculPrive] = useState(0)
  const [coutSalle, setCoutSalle] = useState<'salle' | 'complexe'>('salle')
  const [contraintes, setContraintes] = useState<Contrainte[]>([])
  const [res, setRes] = useState<Resultat | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [calcul, setCalcul] = useState(false)
  const [geo, setGeo] = useState<GeoJSON.FeatureCollection | null>(null)
  const [tri, setTri] = useState<'enseignants' | 'ratio'>('enseignants')
  const [toutes, setToutes] = useState(false)
  const [region, setRegion] = useState('')
  const [epingle, setEpingle] = useState<PlanEpingle | null>(null)
  const [leger, setLeger] = useState(connexionLente)
  const [calculee, setCalculee] = useState<string | null>(null)
  // réglages du plan affiché : les exports et la fiche les reprennent, jamais les réglages en cours de saisie
  const [planDe, setPlanDe] = useState<{ mode: 'moyens' | 'budget'; n: number; m: number; budget: number; redep: number; contraintes: Contrainte[] } | null>(null)

  useEffect(() => {
    lireEtat().then(setEtat).catch((e) => setErreur(String(e.message)))
  }, [])
  // contours seulement si la carte s'affiche (pas en mode léger)
  useEffect(() => { if (!leger && !geo) donnees<GeoJSON.FeatureCollection>('geo_provinces_annuaires').then(setGeo) }, [leger, geo])

  const demande = (): Demande => construire({ scenario, norme, redep, coutSalle, reculPrive, mode, n, m, budget, contraintes })

  // plan proposé par l'assistant : les réglages de l'écran prennent ses valeurs, puis le plan est calculé ici, sous les yeux du décideur
  const appliquer = (arg?: string) => {
    if (!arg) return
    const p = JSON.parse(arg) as Demande
    const v: Reglages = {
      scenario: p.scenario ?? 'tendance', norme: p.eleves_par_maitre ?? meta.normes.eleves_par_maitre, redep: p.redeploiement ?? 0,
      coutSalle: p.cout_salle ?? 'salle', reculPrive: p.recul_prive ?? 0, mode: p.budget_seul ? 'budget' : 'moyens',
      n: p.enseignants ?? meta.defauts.enseignants, m: p.salles ?? meta.defauts.salles, budget: p.budget_fcfa ? p.budget_fcfa / 1e9 : budget,
      contraintes: (['provinces', 'regions'] as const).flatMap((niveau) => Object.entries(p[niveau] ?? {}).flatMap(([nom, b]) =>
        (Object.entries(b) as [keyof Bornes, number][]).map(([cle, valeur]) => ({ niveau, nom, cle, valeur })))),
    }
    setScenario(v.scenario); setNorme(v.norme); setRedep(v.redep); setCoutSalle(v.coutSalle); setReculPrive(v.reculPrive)
    setMode(v.mode); setN(v.n); setM(v.m); setBudget(v.budget); setContraintes(v.contraintes)
    lancer(v)
  }

  const lancer = (v?: Reglages) => {
    const d = v ? construire(v) : demande()
    const r0 = v ?? { mode, n, m, budget, redep, contraintes }
    setCalcul(true); setErreur(null)
    // en cas d'erreur, le plan précédent reste affiché (signalé comme périmé) : le décideur ne perd pas son travail
    const reglages = { mode: r0.mode, n: r0.n, m: r0.m, budget: r0.budget, redep: r0.redep, contraintes: [...r0.contraintes] }
    repartir(d).then((r) => { setRes(r); setCalculee(JSON.stringify(d)); setPlanDe(reglages) })
      .catch((e) => setErreur(String(e.message))).finally(() => setCalcul(false))
  }
  // à l'ouverture : le plan demandé par l'assistant s'il y en a un, sinon le plan par défaut
  useEffect(() => { const a = prendre(['plan']); if (a) appliquer(a.arg); else lancer() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // visite guidée (lancer un calcul) et assistant (ouvrir un plan)
  useEffect(() => ecouter(['calculer', 'plan'], (a) => (a.action === 'plan' ? appliquer(a.arg) : lancer())), []) // eslint-disable-line react-hooks/exhaustive-deps

  const opt = res?.repartitions.optimisee ?? []
  const valeurs = useMemo(() => Object.fromEntries(opt.map((l) => [l.province, l.ratio_maitre_apres])), [opt])
  const parProv = useMemo(() => Object.fromEntries(opt.map((l) => [l.province, l])), [opt])
  const triees = [...opt].sort((a, b) => tri === 'enseignants'
    ? b.enseignants_attribues - a.enseignants_attribues
    : (b.ratio_maitre_apres ?? 0) - (a.ratio_maitre_apres ?? 0))
  const bilan = Object.fromEntries((res?.bilan ?? []).map((b) => [b.methode, b]))
  const o = bilan.optimisee
  // élèves sortis de la surcharge pour un milliard de FCFA : chaque façon de répartir avec son propre coût
  const parMilliard = (x: Resultat['bilan'][number]) => {
    const avant = bilan.sans_moyens_nouveaux?.eleves_au_dela_norme_maitre
    const cout = x.salles_attribuees * (res?.cout_salle_fcfa ?? meta.couts.salle) + x.enseignants_attribues * meta.couts.enseignant * (res?.annees_budget ?? meta.couts.annees_budget)
    return avant != null && cout > 0 ? (avant - x.eleves_au_dela_norme_maitre) / (cout / 1e9) : null
  }
  const plusChargee = opt.reduce<LigneRepartition | null>((m, l) => (!m || (l.ratio_maitre_apres ?? 0) > (m.ratio_maitre_apres ?? 0) ? l : m), null)
  const perime = res !== null && calculee !== null && calculee !== JSON.stringify(demande())
  const sansConstruction = useMemo(() => new Set(opt.filter((l) => !l.construction_possible).map((l) => l.province)), [opt])

  const [excel, setExcel] = useState(false)
  // exporte le plan affiché (ses réglages), même si les réglages ont changé depuis
  const exporterExcel = () => {
    if (!calculee) return
    setExcel(true)
    repartirExcel(JSON.parse(calculee) as Demande).then(({ blob, nom }) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = nom; a.click()
      URL.revokeObjectURL(url)
    }).catch((e) => setErreur(String(e.message))).finally(() => setExcel(false))
  }

  const exporter = () => {
    if (!res || !planDe) return
    const { mode, n, m, budget, redep, contraintes } = planDe
    const params = [
      `Plan de répartition Yennenga;horizon ${res.horizon};scénario ${res.scenario}${res.recul_prive ? `, ${res.recul_prive} % des élèves du privé passés au public` : ""};norme ${res.norme_eleves_par_maitre} élèves par enseignant`,
      `Moyens;${mode === 'moyens' ? `${n} enseignants, ${m} salles` : `budget ${budget} milliards FCFA`}${redep ? `, jusqu'à ${redep} redéployés` : ''};utilisés ${res.enseignants_utilises} enseignants, ${res.salles_utilisees} salles;coût ${Math.round(res.cout_fcfa)} FCFA`,
      `Contraintes;${contraintes.map((c) => `${joli(c.nom)} ${LIB_BORNE[c.cle].replace('…', String(c.valeur))}`).join(' / ') || 'aucune'}`,
      `Coûts;poste ${meta.couts.enseignant} FCFA par an sur ${meta.couts.annees_budget} ans;salle ${res.cout_salle_fcfa ?? meta.couts.salle} FCFA`,
      `Statut;${statutClair(res.statut)};calculé le ${new Date().toLocaleString('fr-FR')}`,
      '',
    ]
    const t = [...params, ['province', 'region', 'eleves_attendus', 'enseignants_actuels', 'salles_actuelles', 'enseignants_attribues', 'salles_construites', 'salles_d_ecoles_fermees_a_rouvrir', 'solde_redeploiement', 'eleves_par_enseignant_apres'].join(';'),
      ...opt.map((l) => [joli(l.province), joli(l.region), l.eleves_horizon, l.maitres, l.salles, l.enseignants_attribues, l.salles_attribuees,
        l.salles_rouvertes ?? 0, l.solde_redeploiement ?? 0, (l.ratio_maitre_apres ?? 0).toFixed(1).replace('.', ',')].join(';'))]
    const url = URL.createObjectURL(new Blob(['﻿' + t.join('\n')], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url; a.download = `plan_repartition_${res.enseignants_utilises}_enseignants_${res.salles_utilisees}_salles.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  const sortis = (x?: Resultat['bilan'][number]) => (x && bilan.sans_moyens_nouveaux ? bilan.sans_moyens_nouveaux.eleves_au_dela_norme_maitre - x.eleves_au_dela_norme_maitre : null)
  const resumeHypotheses = [
    scenario === 'reouverture' ? 'écoles fermées rouvertes' : 'tendance actuelle',
    `norme ${norme}`,
    reculPrive ? `${reculPrive} % du privé au public` : 'privé stable',
    redep ? `jusqu'à ${nb(redep)} mutations` : 'aucune mutation',
  ].join(' · ')
  const moyensAffiches = planDe ? (planDe.mode === 'moyens' ? `${nb(planDe.n)} enseignants · ${nb(planDe.m)} salles` : `budget ${nb(planDe.budget)} Md FCFA`) : ''
  const pr = meta.prive

  return (
    <div className="vue-repartition">
      <h1 className="visuellement-masque">Répartition : calculer un plan</h1>
      <aside className="panneau panneau-reglages" aria-label="Réglages du plan">
        <a className="lien vers-resultat" href="#resultat-plan">Voir le résultat ↓</a>
        <fieldset className="groupe" data-visite="moyens">
          <legend>Vos moyens</legend>
          <div className="segments" role="group" aria-label="Type de moyens">
            <button type="button" aria-pressed={mode === 'moyens'} className={mode === 'moyens' ? 'actif' : ''} onClick={() => setMode('moyens')}>Postes et salles</button>
            <button type="button" aria-pressed={mode === 'budget'} className={mode === 'budget' ? 'actif' : ''} onClick={() => setMode('budget')}>Budget seul</button>
          </div>
          {mode === 'moyens' ? (
            <>
              <Nombre libelle="Nouveaux enseignants à affecter" valeur={n} setValeur={setN} pas={100} max={etat?.limites.enseignants_max}
                aide={<>Les recrues de l'année, à répartir entre les 45 provinces. Valeur proposée : {nb(meta.defauts.enseignants)}, un ordre de grandeur à remplacer par le nombre réel de sortants des écoles de formation (ENEP).</>} />
              <Nombre libelle="Salles à construire" valeur={m} setValeur={setM} pas={100} max={etat?.limites.salles_max}
                aide={<>Salles de classe neuves que l'État peut financer. Un enseignant ajouté a besoin d'une salle : sans salle, il ne peut pas être affecté (sauf salle d'école fermée à rouvrir). Valeur proposée : {nb(meta.defauts.salles)}.</>} />
            </>
          ) : (
            <>
              <Nombre libelle="Budget (milliards de FCFA)" valeur={budget} setValeur={setBudget} pas={5} max={500}
                aide={<>Enveloppe totale. L'outil choisit lui-même combien de postes et de salles financer. Une salle se paie une fois ; un poste se paie chaque année, il est donc compté {meta.couts.annees_budget} fois ({meta.couts.annees_budget} ans de salaire).</>} />
              <Liste libelle="Coût d'une salle" valeur={coutSalle} changer={(v) => setCoutSalle(v as 'salle' | 'complexe')} aide={<>
                <b>Salle seule ({nb(meta.couts.salle / 1e6, 1)} M FCFA)</b> : médiane de 5 marchés communaux d'écoles primaires publiés en 2025 (Quotidien des marchés publics, DGCMEF), entre 7,2 et 9,3 M FCFA.
                {meta.couts.salle_complexe && <> <b>Complexe ({nb(meta.couts.salle_complexe / 1e6, 1)} M FCFA par salle)</b> : école de 3 salles avec bureau, magasin, latrines et 75 tables-bancs, 50 M FCFA au total (bilan 2024 de la gratuité de l'éducation, rapporté par la presse), divisé par 3.</>}
                {' '}<b>Poste d'enseignant ({nb(meta.couts.enseignant / 1e6, 1)} M FCFA par an)</b> : enseignant débutant en zone rurale, salaire et indemnités (environ 200 000 FCFA par mois, CN-EPT 2023), hors cotisations.
              </>}>
                <option value="salle">Salle seule : {nb(meta.couts.salle / 1e6, 1)} M FCFA (marchés communaux 2025)</option>
                {meta.couts.salle_complexe && <option value="complexe">Complexe de 3 salles tout compris : {nb(meta.couts.salle_complexe / 1e6, 1)} M FCFA par salle</option>}
              </Liste>
              <p className="petit">L'outil choisit le meilleur partage entre postes ({nb(meta.couts.enseignant / 1e6, 1)} M FCFA par an, comptés sur {meta.couts.annees_budget} ans) et salles.</p>
            </>
          )}
        </fieldset>

        <details className="groupe">
          <summary><span className="groupe-titre">Hypothèses</span><span className="groupe-resume">{resumeHypotheses}</span></summary>
          <Liste libelle={`Élèves attendus en ${meta.annee_horizon.slice(0, 4)}`} valeur={scenario} changer={setScenario} aide={<>
            Le plan se calcule sur les élèves prévus en {meta.annee_horizon.slice(0, 4)}, pas sur ceux d'aujourd'hui.
            {' '}<b>Tendance</b> : chaque province prolonge, en l'amortissant, l'évolution de ses dernières années.
            {meta.scenarios && <> <b>Réouverture</b> : les {meta.scenarios.provinces_choc} provinces qui ont perdu plus de {pct(meta.scenarios.choc_seuil, 0)} de leurs élèves d'une année sur l'autre depuis {meta.scenarios.choc_depuis} regagnent d'ici là {pct(meta.scenarios.rattrapage, 0)} de l'écart avec leur plus haut niveau d'élèves.
              Au total, {nb(meta.scenarios.eleves_reouverture)} élèves au lieu de {nb(meta.scenarios.eleves_tendance)} (public et privé), soit {nb(meta.scenarios.eleves_reouverture - meta.scenarios.eleves_tendance)} de plus : le plan envoie alors davantage de moyens vers ces provinces.</>}
          </>}>
            <option value="tendance">Tendance actuelle (scénario central)</option>
            <option value="reouverture">Si les écoles fermées rouvrent</option>
          </Liste>
          <Liste libelle="Élèves du privé qui passent au public" valeur={String(reculPrive)} changer={(v) => setReculPrive(Number(v))} aide={<>
            {pr ? <>En {meta.annee_reference}, le privé scolarise {pct(pr.part, 0)} des élèves du primaire, jusqu'à {pct(pr.part_max, 0)} au {joli(pr.province_max)}{pr.provinces_sans.length ? <>, aucun au {pr.provinces_sans.map(joli).join(', ')}</> : null}. </> : null}
            Par défaut, l'outil suppose que cette part reste stable.
            Si des écoles privées ferment ou si les familles ne peuvent plus payer, leurs élèves se reportent vers le public, qui doit les accueillir.
            Ce réglage simule ce report : « 20 % » veut dire qu'un élève du privé sur cinq passe dans le public d'ici {meta.annee_horizon.slice(0, 4)}, dans chaque province.
          </>}>
            {[0, 10, 20, 30, 50].filter((v) => v <= (etat?.limites.recul_prive_max ?? 50)).map((v) => <option key={v} value={v}>{v === 0 ? 'Aucun (part du privé stable)' : `${v} % des élèves du privé`}</option>)}
          </Liste>
          <Liste libelle="Norme d'élèves par enseignant" valeur={String(norme)} changer={(v) => setNorme(Number(v))} aide={<>
            Le seuil au-delà duquel une classe est jugée surchargée. 50 : norme nationale (tableau de bord 2023-2024 de la DGESS). 40 : objectif du plan sectoriel de l'éducation 2017-2030.
            Une norme plus basse fait apparaître plus de besoins ; elle ne change pas les moyens disponibles.
          </>}>
            {(etat?.limites.normes_acceptees ?? [40, 45, 50]).map((v) => <option key={v} value={v}>{v}{v === meta.normes.eleves_par_maitre ? ' (norme nationale)' : v === 40 ? ' (plan sectoriel)' : ''}</option>)}
          </Liste>
          <Nombre libelle="Mutations d'enseignants en poste (au plus)" valeur={redep} setValeur={setRedep} pas={100} max={etat?.limites.enseignants_max}
            aide={<>En plus des recrues, l'outil peut déplacer des enseignants déjà en poste, d'une province qui en a plus que la norme vers une province surchargée.
              Le nombre saisi est un plafond : l'outil en déplace moins si cela ne sert à rien. 0 = aucune mutation.
              Une mutation ne crée pas de poste (pas de salaire en plus), mais l'enseignant doit trouver une salle à l'arrivée.</>} />
        </details>

        <details className="groupe" data-visite="contraintes" open={contraintes.length > 0 || undefined}>
          <summary><span className="groupe-titre">Vos exigences</span><span className="groupe-resume">{contraintes.length ? `${contraintes.length} exigence${contraintes.length > 1 ? 's' : ''}` : 'aucune'}</span></summary>
          <p className="petit">Par exemple : au moins 300 enseignants pour une région. Une exigence impossible à tenir est expliquée.</p>
          {contraintes.map((c, i) => {
            const texte = `${c.niveau === 'regions' ? 'Région' : 'Province'} ${joli(c.nom)} : ${LIB_BORNE[c.cle].replace('…', nb(c.valeur))}`
            return (
              <div key={i} className="contrainte">
                <span>{texte}</span>
                <button className="lien retirer" aria-label={`Retirer l'exigence ${texte}`} onClick={() => setContraintes(contraintes.filter((_, j) => j !== i))}>×</button>
              </div>
            )
          })}
          {etat && <AjoutContrainte etat={etat} sansConstruction={sansConstruction} ajouter={(c) => setContraintes([...contraintes, c])} />}
        </details>

        <div className="pied-panneau">
          {perime && !calcul && <p className="petit alerte-reglages" role="status">Réglages modifiés : calculez pour mettre le plan à jour.</p>}
          <button className="principal large" onClick={() => lancer()} disabled={calcul} data-visite="calculer">
            {calcul ? 'Calcul en cours…' : 'Calculer le plan'}
          </button>
          {res && !epingle && <button className="secondaire large garder-plan" onClick={() => setEpingle({ res, o, titre: titrePlan(planDe) })}
            title="Garde ce plan en mémoire : changez ensuite les réglages et recalculez pour voir les deux plans côte à côte">Garder ce plan pour comparer</button>}
          {epingle && <p className="encart petit garder-plan">Plan gardé pour comparer : <b>{epingle.titre}</b>. {epingle.res === res ? 'Modifiez les réglages puis calculez : les deux plans s\'afficheront côte à côte.' : 'La comparaison s\'affiche avec les résultats.'} <button className="lien" onClick={() => setEpingle(null)}>Oublier ce plan</button></p>}
        </div>
      </aside>

      <section className={`resultats${perime ? ' perime' : ''}`} id="resultat-plan" aria-label="Résultat du plan" tabIndex={-1}>
        {erreur && <div className="bandeau-erreur" role="alert"><b>Calcul impossible.</b> {erreur}{res ? ' Le plan affiché est le précédent.' : ''} <button className="secondaire" onClick={() => lancer()}>Réessayer</button></div>}
        {!res && !erreur && <div className="squelette-resultat" aria-busy="true"><p>Calcul du plan en cours…</p><span></span><span></span><span></span><span></span></div>}
        {res && o && (
          <>
            <div className="barre-plan" role="region" aria-label="Plan affiché">
              <div className="barre-plan-texte">
                <b>{moyensAffiches} · {mds(res.cout_fcfa)}</b>
                {calcul ? <span className="etat-plan calcul" role="status">Calcul en cours{mode === 'budget' ? ' (jusqu\'à une dizaine de secondes avec un budget seul)' : ''}…</span>
                  : perime ? <span className="etat-plan perime" role="status">Réglages modifiés : ce plan correspond aux réglages précédents.</span>
                  : <span className="etat-plan">{statutClair(res.statut).replace(/^./, (c) => c.toUpperCase())} · {nb(res.duree_s, 1)} s · rentrée {res.horizon.slice(0, 4)}</span>}
              </div>
              <div className="barre-plan-boutons">
                {epingle && epingle.res === res && <span className="plan-garde">Plan gardé ✓</span>}
                {perime && !calcul && <button className="principal" onClick={() => lancer()}>Recalculer</button>}
                <details className="menu-export">
                  <summary className="secondaire">Exporter</summary>
                  <div className="menu-export-liste">
                    <button className="lien" onClick={exporterExcel} disabled={excel}>{excel ? 'Préparation…' : 'Excel complet (.xlsx)'}</button>
                    <button className="lien" onClick={exporter}>Tableau du plan (.csv)</button>
                    <button className="lien" onClick={() => window.print()}>Fiche de décision à imprimer</button>
                  </div>
                </details>
              </div>
            </div>

            <div className="tuiles" data-visite="tuiles">
              <Tuile titre="Élèves sortis des classes surchargées" valeur={nb(sortis(o))} forte
                aide={<>Élèves en trop dans les classes surchargées sans moyens nouveaux ({nb(bilan.sans_moyens_nouveaux?.eleves_au_dela_norme_maitre)}), moins ceux qui restent après le plan ({nb(o.eleves_au_dela_norme_maitre)}).</>}
                note={(() => { const rO = parMilliard(o), rP = bilan.proportionnelle ? parMilliard(bilan.proportionnelle) : null
                  return rO != null && rP ? `${nb(rO)} par milliard de FCFA, contre ${nb(rP)} en partageant selon le nombre d'élèves : ${rO >= rP ? '+' : '−'}${pct(Math.abs(rO / rP - 1), 0)} pour le même argent` : undefined })()} />
              <Tuile titre="Enseignants affectés" valeur={nb(res.enseignants_utilises)} note={[mode === 'moyens' && res.enseignants_utilises < n ? `${nb(n - res.enseignants_utilises)} restent : pas de salle pour eux` : '', res.enseignants_redeployes ? `+ ${nb(res.enseignants_redeployes)} mutés` : ''].filter(Boolean).join(' · ') || undefined} />
              <Tuile titre="Salles construites" valeur={nb(res.salles_utilisees)}
                note={[`≈ ${nb(Math.ceil(res.salles_utilisees / 3))} complexes de 3 salles`, o.salles_rouvertes ? `et ${nb(o.salles_rouvertes)} salles d'écoles fermées à rouvrir` : ''].filter(Boolean).join(' ; ')} />
              <Tuile titre="Coût du plan" valeur={mds(res.cout_fcfa)}
                aide={<>Coût = salles construites × prix d'une salle + nouveaux postes × salaire annuel × {res.annees_budget ?? meta.couts.annees_budget} ans.
                  Ici : {nb(res.salles_utilisees)} × {nb((res.cout_salle_fcfa ?? meta.couts.salle) / 1e6, 1)} M + {nb(res.enseignants_utilises)} × {nb(meta.couts.enseignant / 1e6, 1)} M × {res.annees_budget ?? meta.couts.annees_budget}.
                  Les mutations et les salles d'écoles fermées à rouvrir ne sont pas comptées (pas de poste ni de construction neuve). Prix retenus : salle seule, médiane de 5 marchés communaux d'écoles primaires de 2025 ; poste, enseignant débutant en zone rurale (salaire et indemnités, hors cotisations).</>}
                note={[
                  res.cout_salles_fcfa != null ? `${mds(res.cout_salles_fcfa)} de salles (une fois) + ${mds(res.salaires_annuels_fcfa ?? 0)} de salaires par an, sur ${res.annees_budget ?? meta.couts.annees_budget} ans` : `postes comptés sur ${meta.couts.annees_budget} ans`,
                  res.enseignants_redeployes ? `${nb(res.enseignants_redeployes)} mutés : ${mds(res.enseignants_redeployes * meta.couts.enseignant)} de salaires nouveaux évités par an` : '',
                ].filter(Boolean).join(' · ')} />
            </div>

            {epingle && epingle.res !== res && (
              <section className="bloc-comparer">
                <ComparaisonPlans a={epingle} b={{ res, o, titre: titrePlan(planDe) }} retirer={() => setEpingle(null)} />
              </section>
            )}

            <div className="carte-et-lecture">
              <section className="bloc-carte-plan">
                <h2 className="titre-bloc">Élèves par enseignant en {res.horizon.slice(0, 4)}, après répartition</h2>
                {leger ? (
                  <div className="carte-masquee">
                    <p><b>Mode léger</b> : carte masquée pour économiser la connexion. Le détail par province est dans le tableau plus bas.</p>
                    <button className="secondaire" onClick={() => { setModeLeger(false); setLeger(false) }}>Afficher la carte (≈ 300 ko)</button>
                  </div>
                ) : (
                  <>
                    <div className="carte-petite">
                      <Suspense fallback={<div className="squelette-carte" aria-busy="true"><p>Chargement de la carte…</p></div>}>
                        {geo ? <Carte zones={geo} idProp="province" valeurs={valeurs} classes={CLASSES_RATIO}
                          infobulle={(id) => { const l = parProv[id]; return l ? `<b>${joli(id)}</b><br>+${nb(l.enseignants_attribues)} enseignants, +${nb(l.salles_attribuees)} salles${l.salles_rouvertes ? `, ${nb(l.salles_rouvertes)} à rouvrir` : ''}<br>${nb(l.ratio_maitre_apres)} élèves par enseignant` : id }} />
                          : <div className="squelette-carte" aria-busy="true"><p>Chargement des contours…</p></div>}
                      </Suspense>
                    </div>
                    <Legende classes={CLASSES_RATIO} format={(x) => nb(x)} titre="Élèves par enseignant" />
                    <button className="lien bouton-leger" onClick={() => { setModeLeger(true); setLeger(true) }}>Connexion lente ? Passer en mode léger</button>
                  </>
                )}
              </section>

              <div className="colonne-lecture">
                {bilan.proportionnelle && bilan.besoins && <LectureComparaison o={o} p={bilan.proportionnelle} b={bilan.besoins} parMilliard={parMilliard} plusChargee={plusChargee} />}
              </div>
            </div>

            <section className="bloc-avant-apres" data-visite="avant-apres">
              <div className="entete-tableau">
                <h2 className="titre-bloc">Avant et après le plan, province par province</h2>
                <button className="lien" onClick={() => setToutes(!toutes)}>{toutes ? 'Voir les 20 plus chargées' : `Voir les ${opt.length} provinces`}</button>
              </div>
              <AvantApres lignes={opt} norme={res.norme_eleves_par_maitre} max={toutes ? 99 : 20} horizon={res.horizon} />
            </section>

            <section data-visite="comparaison">
              <h2 className="titre-bloc">Plan Yennenga et règles simples, avec les mêmes moyens</h2>
              <ComparaisonCourte bilan={bilan} parMilliard={parMilliard} />
              <details className="details-comparaison">
                <summary>Voir les 7 indicateurs et la situation sans moyens nouveaux</summary>
                <div className="defile">
                  <table className="tableau comparaison">
                    <thead><tr><th>Façon de répartir</th><th>Élèves en trop dans les classes surchargées</th><th>Province la plus chargée (élèves par enseignant)</th><th>Écart entre provinces<Aide titre="Explication : écart entre provinces">Indice de Gini : 0 si toutes les provinces ont le même nombre d'élèves par enseignant, plus haut quand les dotations sont inégales.</Aide></th><th>Provinces encore surchargées</th><th>Élèves dans une province sans surcharge</th><th>Élèves sortis de la surcharge pour 1 milliard de FCFA<Aide titre="Explication : élèves sortis par milliard">Élèves en trop en moins par rapport à « sans moyens nouveaux », divisés par le coût de la répartition (salles + salaires comptés sur {res.annees_budget ?? meta.couts.annees_budget} ans), en milliards de FCFA.</Aide></th></tr></thead>
                    <tbody>
                      {['sans_moyens_nouveaux', 'proportionnelle', 'besoins', 'optimisee'].filter((k) => bilan[k]).map((k) => (
                        <tr key={k} className={k === 'optimisee' ? 'ligne-forte' : ''}>
                          <th scope="row">{LIB_METHODE[k]}</th>
                          <td>{nb(bilan[k].eleves_au_dela_norme_maitre)}</td>
                          <td>{nb(bilan[k].pire_ratio_eleves_maitre)}</td>
                          <td>{nb(bilan[k].gini_ratio_maitre, 3)}</td>
                          <td>{bilan[k].provinces_au_dessus_norme_maitre}</td>
                          <td>{pct(bilan[k].part_eleves_province_conforme)}</td>
                          <td>{k === 'sans_moyens_nouveaux' ? '—' : nb(parMilliard(bilan[k]))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>

            {(res.mouvements?.length ?? 0) > 0 && (
              <section className="bloc-mouvements">
                <h2 className="titre-bloc">Mutations proposées ({nb(res.enseignants_redeployes ?? 0)} enseignants)</h2>
                <p className="petit">Le plan fixe combien d'enseignants quittent chaque province et combien arrivent ; l'appariement propose les mouvements les plus courts. Le choix des personnes relève des services.</p>
                <div className="defile"><table className="tableau compact">
                  <thead><tr><th>De</th><th>Vers</th><th>Enseignants</th><th>Distance</th></tr></thead>
                  <tbody>{res.mouvements!.map((m) => <tr key={m.de + m.vers}><td>{joli(m.de)}</td><td>{joli(m.vers)}</td><td className="num">{nb(m.enseignants)}</td><td className="num">{nb(m.distance_km)} km</td></tr>)}</tbody>
                </table></div>
              </section>
            )}
            <div className="entete-tableau">
              <h2 className="titre-bloc">Plan par province</h2>
              <select aria-label="Filtrer par région" value={region} onChange={(e) => setRegion(e.target.value)} className="filtre-region">
                <option value="">Toutes les régions</option>
                {Array.from(new Set(opt.map((l) => l.region))).sort().map((r) => <option key={r} value={r}>{joli(r)}</option>)}
              </select>
              <div className="segments petit-seg" role="group" aria-label="Trier le plan">
                <button type="button" aria-pressed={tri === 'enseignants'} className={tri === 'enseignants' ? 'actif' : ''} onClick={() => setTri('enseignants')}>par enseignants</button>
                <button type="button" aria-pressed={tri === 'ratio'} className={tri === 'ratio' ? 'actif' : ''} onClick={() => setTri('ratio')}>par charge</button>
              </div>
            </div>
            <TablePlan lignes={triees.filter((l) => !region || l.region === region)} />
          </>
        )}
      </section>
      {res && o && planDe && <FicheImpression res={res} bilan={bilan} lignes={triees} contraintes={planDe.contraintes} meta={meta} redep={planDe.redep} />}
    </div>
  )
}

// Fiche de décision : visible seulement à l'impression (une à deux pages A4)
function FicheImpression({ res, bilan, lignes, contraintes, meta, redep }: {
  res: Resultat; bilan: Record<string, Resultat['bilan'][number]>; lignes: LigneRepartition[]; contraintes: Contrainte[]; meta: Meta; redep: number
}) {
  const o = bilan.optimisee
  const servies = lignes.filter((l) => l.enseignants_attribues || l.salles_attribuees || l.solde_redeploiement)
  const avecRedep = servies.some((l) => l.solde_redeploiement)
  return (
    <div className="fiche-impression" aria-hidden="true">
      <h1>Plan de répartition des enseignants et des salles de classe</h1>
      <p className="fiche-sous-titre">Primaire public · rentrée {res.horizon.slice(0, 4)} · calculé le {new Date().toLocaleDateString('fr-FR')} par l'outil Yennenga · {statutClair(res.statut)}</p>
      <div className="fiche-deux">
        <div>
          <h2>Paramètres</h2>
          <table><tbody>
            <tr><th>Évolution des effectifs</th><td>{res.scenario === 'reouverture' ? 'réouverture des écoles fermées' : 'scénario central (tendance)'}</td></tr>
            <tr><th>Élèves du privé passés au public</th><td>{res.recul_prive ? `${nb(res.recul_prive)} % d'ici ${res.horizon.slice(0, 4)}` : 'aucun (part du privé stable)'}</td></tr>
            <tr><th>Norme</th><td>{res.norme_eleves_par_maitre} élèves par enseignant</td></tr>
            <tr><th>Redéploiement accepté</th><td>{redep ? `jusqu'à ${nb(redep)}` : 'aucun'}</td></tr>
            <tr><th>Coût d'un poste</th><td>{nb(meta.couts.enseignant / 1e6, 1)} M FCFA par an, sur {meta.couts.annees_budget} ans</td></tr>
            <tr><th>Coût d'une salle</th><td>{nb((res.cout_salle_fcfa ?? meta.couts.salle) / 1e6, 1)} M FCFA</td></tr>
            <tr><th>Exigences</th><td>{contraintes.length ? contraintes.map((c) => `${joli(c.nom)} : ${LIB_BORNE[c.cle].replace('…', nb(c.valeur))}`).join(' ; ') : 'aucune'}</td></tr>
          </tbody></table>
        </div>
        <div>
          <h2>Résultat</h2>
          <table><tbody>
            <tr><th>Enseignants affectés</th><td>{nb(res.enseignants_utilises)}{res.enseignants_redeployes ? ` + ${nb(res.enseignants_redeployes)} mutés` : ''}</td></tr>
            <tr><th>Salles construites</th><td>{nb(res.salles_utilisees)}{o.salles_rouvertes ? ` ; ${nb(o.salles_rouvertes)} à rouvrir` : ''}</td></tr>
            <tr><th>Coût du plan</th><td>{mds(res.cout_fcfa)}{res.cout_salles_fcfa != null ? ` : ${mds(res.cout_salles_fcfa)} de salles + ${mds(res.salaires_annuels_fcfa ?? 0)} de salaires par an` : ''}</td></tr>
            <tr><th>Province la plus chargée</th><td>{nb(o.pire_ratio_eleves_maitre)} élèves par enseignant (sans moyens nouveaux : {nb(bilan.sans_moyens_nouveaux?.pire_ratio_eleves_maitre)} ; en partageant selon le nombre d'élèves : {nb(bilan.proportionnelle?.pire_ratio_eleves_maitre)})</td></tr>
            <tr><th>Élèves dans une province sans surcharge</th><td>{pct(o.part_eleves_province_conforme)}</td></tr>
          </tbody></table>
        </div>
      </div>
      <h2>Plan par province ({servies.length} provinces reçoivent des moyens)</h2>
      <table className="fiche-plan">
        <thead><tr><th>Province</th><th>Région</th><th>Élèves attendus</th><th>Enseignants</th><th>Affectés</th>{avecRedep && <th>Redéployés</th>}<th>Salles construites</th><th>À rouvrir</th><th>Élèves par enseignant après</th></tr></thead>
        <tbody>
          {servies.map((l) => (
            <tr key={l.province}><td>{joli(l.province)}</td><td>{joli(l.region)}</td><td>{nb(l.eleves_horizon)}</td><td>{nb(l.maitres)}</td>
              <td>{l.enseignants_attribues ? `+${nb(l.enseignants_attribues)}` : ''}</td>
              {avecRedep && <td>{l.solde_redeploiement ? (l.solde_redeploiement > 0 ? `+${nb(l.solde_redeploiement)}` : `−${nb(-l.solde_redeploiement)}`) : ''}</td>}
              <td>{l.salles_attribuees ? `+${nb(l.salles_attribuees)}` : ''}</td><td>{l.salles_rouvertes ? nb(l.salles_rouvertes) : ''}</td>
              <td>{nb(l.ratio_maitre_apres)}</td></tr>
          ))}
        </tbody>
        <tfoot><tr><td>Total</td><td>{servies.length} provinces</td><td>{nb(servies.reduce((t, l) => t + l.eleves_horizon, 0))}</td><td>{nb(servies.reduce((t, l) => t + l.maitres, 0))}</td>
          <td>+{nb(servies.reduce((t, l) => t + l.enseignants_attribues, 0))}</td>{avecRedep && <td></td>}
          <td>+{nb(servies.reduce((t, l) => t + l.salles_attribuees, 0))}</td><td>{nb(servies.reduce((t, l) => t + (l.salles_rouvertes ?? 0), 0))}</td><td></td></tr></tfoot>
      </table>
      <p className="fiche-note">Hypothèses : un enseignant affecté dispose d'une salle (libre, construite ou rouverte) ; pas de construction là où l'accès est trop dégradé ni là où plus de {nb(100 * meta.implantation.seuil_fermeture_rouvrir)} % des écoles sont fermées (on rouvre d'abord ; remise en état non chiffrée). Détail complet dans l'export Excel.</p>
      <div className="fiche-visa"><div>Préparé par</div><div>Validé par</div><div>Date et signature</div></div>
    </div>
  )
}

function Liste({ libelle, valeur, changer, aide, children }: { libelle: string; valeur: string; changer: (v: string) => void; aide?: ReactNode; children: ReactNode }) {
  const id = useId()
  return (
    <div className="champ">
      <span><label htmlFor={id}>{libelle}</label>{aide && <Aide titre={`Explication : ${libelle}`}>{aide}</Aide>}</span>
      <select id={id} value={valeur} onChange={(e) => changer(e.target.value)}>{children}</select>
    </div>
  )
}

function Nombre({ libelle, valeur, setValeur, pas, max, aide }: { libelle: string; valeur: number; setValeur: (v: number) => void; pas: number; max?: number; aide?: ReactNode }) {
  // le libellé ne contient que le champ : toucher le libellé ne déclenche jamais « − » ou « + »
  const id = useId()
  return (
    <div className="champ">
      <span><label htmlFor={id}>{libelle}</label>{aide && <Aide titre={`Explication : ${libelle}`}>{aide}</Aide>}</span>
      <div className="nombre">
        <button type="button" onClick={() => setValeur(Math.max(0, valeur - pas))} aria-label={`Diminuer de ${pas} : ${libelle}`}>−</button>
        <input id={id} type="number" inputMode="numeric" min={0} max={max} step={pas} value={valeur}
          onChange={(e) => setValeur(Math.max(0, Number(e.target.value) || 0))} />
        <button type="button" onClick={() => setValeur(Math.min(max ?? Infinity, valeur + pas))} aria-label={`Augmenter de ${pas} : ${libelle}`}>+</button>
      </div>
    </div>
  )
}

function AjoutContrainte({ etat, sansConstruction, ajouter }: { etat: Etat; sansConstruction: Set<string>; ajouter: (c: Contrainte) => void }) {
  const [niveau, setNiveau] = useState<'provinces' | 'regions'>('provinces')
  const [nom, setNom] = useState(etat.provinces[0])
  const [cle, setCle] = useState<keyof Bornes>('min_enseignants')
  const [valeur, setValeur] = useState(100)
  const liste = niveau === 'provinces' ? etat.provinces : etat.regions
  // pas de plancher de salles là où le plan ne construit pas (accès dégradé, ou écoles fermées à rouvrir d'abord)
  const interdit = niveau === 'provinces' && sansConstruction.has(nom) && cle === 'min_salles'
  return (
    <div className="ajout">
      <select aria-label="Niveau de l'exigence" value={niveau} onChange={(e) => { const v = e.target.value as 'provinces' | 'regions'; setNiveau(v); setNom((v === 'provinces' ? etat.provinces : etat.regions)[0]) }}>
        <option value="provinces">Province</option><option value="regions">Région</option>
      </select>
      <select aria-label={niveau === 'provinces' ? 'Province' : 'Région'} value={nom} onChange={(e) => setNom(e.target.value)}>{liste.map((x) => <option key={x} value={x}>{joli(x)}</option>)}</select>
      <select aria-label="Type d'exigence" value={cle} onChange={(e) => setCle(e.target.value as keyof Bornes)}>
        {(Object.keys(LIB_BORNE) as (keyof Bornes)[]).map((k) => <option key={k} value={k}>{LIB_BORNE[k]}</option>)}
      </select>
      <input aria-label="Nombre" type="number" inputMode="numeric" min={0} value={valeur} onChange={(e) => setValeur(Math.max(0, Number(e.target.value) || 0))} />
      <button className="secondaire" disabled={interdit} onClick={() => ajouter({ niveau, nom, cle, valeur })}>Ajouter</button>
      {interdit && <p className="petit">{joli(nom)} : on n'y construit pas (écoles fermées à rouvrir d'abord, ou accès trop difficile).</p>}
    </div>
  )
}

// Ce que l'optimisation gagne, et ce qu'elle cède : dit franchement, chiffres à l'appui
function LectureComparaison({ o, p, b, parMilliard, plusChargee }: { o: Resultat['bilan'][number]; p: Resultat['bilan'][number]; b: Resultat['bilan'][number]; parMilliard: (x: Resultat['bilan'][number]) => number | null; plusChargee: LigneRepartition | null }) {
  const rO = parMilliard(o), rP = parMilliard(p)
  const gain = 1 - o.eleves_au_dela_norme_maitre / Math.max(p.eleves_au_dela_norme_maitre, 1)
  const egalBesoins = Math.abs(o.eleves_au_dela_norme_maitre - b.eleves_au_dela_norme_maitre) <= 0.01 * Math.max(b.eleves_au_dela_norme_maitre, 1)
  return (
    <div className="lecture" aria-label="Lecture du résultat">
      <p><b>Avec les mêmes moyens, le plan Yennenga laisse {nb(o.eleves_au_dela_norme_maitre)} élèves en trop dans des classes surchargées, contre {nb(p.eleves_au_dela_norme_maitre)} en partageant selon le nombre d'élèves ({gain > 0 ? '−' : '+'}{pct(Math.abs(gain), 0)}).</b>
        {rO != null && rP ? <> Pour 1 milliard de FCFA, il sort {nb(rO)} élèves des classes surchargées, contre {nb(rP)} : {rO >= rP ? '+' : '−'}{pct(Math.abs(rO / rP - 1), 0)} pour le même argent.</> : null}</p>
      <p>{egalBesoins
        ? `Partager selon les manques en laisse autant. Ce que Yennenga apporte en plus : il sert d'abord les provinces les plus chargées, d'où un écart plus faible entre provinces (${nb(o.gini_ratio_maitre, 3)} contre ${nb(b.gini_ratio_maitre, 3)}).`
        : `Partager selon les manques en laisse ${nb(b.eleves_au_dela_norme_maitre)}.`}
        {plusChargee && ` Après le plan, la province la plus chargée est ${joli(plusChargee.province)} (${nb(o.pire_ratio_eleves_maitre)} élèves par enseignant, contre ${nb(p.pire_ratio_eleves_maitre)} en partageant selon le nombre d'élèves)${plusChargee.construction_possible === false ? " : on n'y construit pas (accès trop difficile ou écoles fermées à rouvrir), ce chiffre ne baisse qu'avec des mutations ou une réouverture" : ''}.`}
        {o.part_eleves_province_conforme < p.part_eleves_province_conforme && ` En contrepartie, partager selon le nombre d'élèves fait passer plus de provinces juste sous la norme (${pct(p.part_eleves_province_conforme)} des élèves contre ${pct(o.part_eleves_province_conforme)}) : il donne des enseignants à des provinces presque à la norme, au détriment des plus surchargées.`}</p>
    </div>
  )
}

function ComparaisonCourte({ bilan, parMilliard }: { bilan: Record<string, Resultat['bilan'][number]>; parMilliard: (x: Resultat['bilan'][number]) => number | null }) {
  const cles = ['proportionnelle', 'besoins', 'optimisee'].filter((k) => bilan[k])
  const cols: { titre: string; val: (x: Resultat['bilan'][number]) => number | null; fmt: (v: number | null) => string; mieux: 'bas' | 'haut' }[] = [
    { titre: 'Élèves en trop dans les classes surchargées', val: (x) => x.eleves_au_dela_norme_maitre, fmt: (v) => nb(v), mieux: 'bas' },
    { titre: 'Province la plus chargée (élèves par enseignant)', val: (x) => x.pire_ratio_eleves_maitre, fmt: (v) => nb(v), mieux: 'bas' },
    { titre: 'Écart entre provinces (0 = égalité)', val: (x) => x.gini_ratio_maitre, fmt: (v) => nb(v, 3), mieux: 'bas' },
    { titre: 'Élèves sortis pour 1 milliard de FCFA', val: (x) => parMilliard(x), fmt: (v) => nb(v), mieux: 'haut' },
  ]
  const meilleur = cols.map((c) => {
    const v = cles.map((k) => c.val(bilan[k])).filter((x): x is number => x != null)
    return c.mieux === 'bas' ? Math.min(...v) : Math.max(...v)
  })
  const egal = (a: number | null, b: number) => a != null && Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(b))
  const sm = bilan.sans_moyens_nouveaux
  return (
    <>
      <div className="defile">
        <table className="tableau comparaison courte">
          <thead><tr><th>Façon de répartir</th>{cols.map((c) => <th key={c.titre}>{c.titre}</th>)}</tr></thead>
          <tbody>
            {cles.map((k) => (
              <tr key={k} className={k === 'optimisee' ? 'ligne-forte' : ''}>
                <th scope="row">{LIB_METHODE[k]}</th>
                {cols.map((c, i) => { const v = c.val(bilan[k]); const top = egal(v, meilleur[i])
                  return <td key={c.titre} className={top ? 'meilleur' : ''}>{c.fmt(v)}{top && <span className="marque-meilleur"> ▲ meilleur</span>}</td> })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sm && <p className="petit">Sans moyens nouveaux : {nb(sm.eleves_au_dela_norme_maitre)} élèves en trop, province la plus chargée à {nb(sm.pire_ratio_eleves_maitre)} élèves par enseignant.</p>}
    </>
  )
}

type PlanEpingle = { res: Resultat; o: Resultat['bilan'][number]; titre?: string }

function titrePlan(p: { mode: string; n: number; m: number; budget: number; redep: number; contraintes: unknown[] } | null): string {
  if (!p) return 'Plan gardé'
  const moyens = p.mode === 'moyens' ? `${nb(p.n)} enseignants, ${nb(p.m)} salles` : `budget ${nb(p.budget)} Md FCFA`
  return [moyens, p.redep ? `${nb(p.redep)} mutations possibles` : '', p.contraintes.length ? `${p.contraintes.length} exigence(s)` : ''].filter(Boolean).join(' · ')
}

// deux plans côte à côte : le plan gardé et le plan affiché
function ComparaisonPlans({ a, b, retirer }: { a: PlanEpingle; b: PlanEpingle; retirer: () => void }) {
  // libellé, valeur, mise en forme, et si une valeur plus basse est meilleure (null : neutre)
  const lignes: [string, (p: PlanEpingle) => number, (v: number) => string, boolean | null][] = [
    ['Enseignants affectés', (p) => p.res.enseignants_utilises, (v) => nb(v), null],
    ['Enseignants mutés', (p) => p.res.enseignants_redeployes ?? 0, (v) => nb(v), null],
    ['Salles construites', (p) => p.res.salles_utilisees, (v) => nb(v), null],
    ['Coût du plan', (p) => p.res.cout_fcfa, (v) => mds(v), true],
    ['Élèves en trop dans les classes surchargées', (p) => p.o.eleves_au_dela_norme_maitre, (v) => nb(v), true],
    ['Province la plus chargée (élèves par enseignant)', (p) => p.o.pire_ratio_eleves_maitre, (v) => nb(v), true],
    ['Écart entre provinces (0 = égalité)', (p) => p.o.gini_ratio_maitre, (v) => nb(v, 3), true],
    ['Provinces encore surchargées', (p) => p.o.provinces_au_dessus_norme_maitre, (v) => nb(v), true],
  ]
  const ecart = (va: number, vb: number, f: (v: number) => string, basMieux: boolean | null) => {
    const d = vb - va
    if (Math.abs(d) < 1e-9) return { t: '=', c: '' }
    const t = `${d > 0 ? '+' : '−'}${f(Math.abs(d))}`
    return { t, c: basMieux == null ? '' : (d < 0) === basMieux ? 'ecart-mieux' : 'ecart-moins' }
  }
  return (
    <div>
      <div className="entete-tableau"><h3>Deux plans côte à côte</h3><button className="lien" onClick={retirer}>Ne plus comparer</button></div>
      <div className="defile"><table className="tableau compact comparaison">
        <thead><tr><th></th><th>Plan gardé<br /><small>{a.titre}</small></th><th>Plan affiché<br /><small>{b.titre}</small></th><th>Écart</th></tr></thead>
        <tbody>{lignes.map(([lib, f, fmt, bas]) => { const e = ecart(f(a), f(b), fmt, bas)
          return <tr key={lib}><th scope="row">{lib}</th><td>{fmt(f(a))}</td><td className="fort">{fmt(f(b))}</td><td className={e.c}>{e.t}{e.c === 'ecart-mieux' ? ' (mieux)' : e.c === 'ecart-moins' ? ' (moins bien)' : ''}</td></tr> })}</tbody>
      </table></div>
    </div>
  )
}

function Tuile({ titre, valeur, note, unite, aide, forte }: { titre: string; valeur: string; note?: string; unite?: string; aide?: ReactNode; forte?: boolean }) {
  return <div className={`tuile${forte ? ' tuile-forte' : ''}`}><span>{titre}{aide && <Aide titre={`Explication : ${titre}`}>{aide}</Aide>}</span><b>{valeur}{unite && <em className="unite"> {unite}</em>}</b>{note && <small>{note}</small>}</div>
}

function TablePlan({ lignes }: { lignes: LigneRepartition[] }) {
  const somme = (f: (l: LigneRepartition) => number) => lignes.reduce((t, l) => t + (f(l) || 0), 0)
  return (
    <div className="defile">
      <table className="tableau plan">
        <thead><tr><th>Province</th><th>Région</th><th className="num">Élèves attendus<Aide titre="Explication : élèves attendus">Élèves du public prévus pour la rentrée de l'horizon du plan. Dans les provinces touchées par l'insécurité (baisse brutale des effectifs), la prévision garde l'effectif actuel faute de tendance fiable ; le scénario « Si les écoles fermées rouvrent » donne l'autre hypothèse.</Aide></th><th className="num">Enseignants</th><th className="num">Affectés</th><th className="num">Salles</th><th className="num">Construites</th><th className="num">À rouvrir</th><th className="num">Mutés</th><th className="num">Élèves par enseignant après</th><th>Pourquoi</th></tr></thead>
        <tbody>
          {lignes.map((l) => (
            <tr key={l.province}>
              <td>{joli(l.province)}</td><td>{joli(l.region)}</td><td className="num">{nb(l.eleves_horizon)}</td><td className="num">{nb(l.maitres)}</td>
              <td className="num fort">{l.enseignants_attribues ? `+${nb(l.enseignants_attribues)}` : '—'}</td><td className="num">{nb(l.salles)}</td>
              <td className="num">{l.salles_attribuees ? <b>+{nb(l.salles_attribuees)}</b> : l.construction_possible ? '—'
                : <span className={l.rouvrir_d_abord && l.acces_construction ? 'etat-pastille rouvrir' : 'etat-pastille acces'}>{l.rouvrir_d_abord && l.acces_construction ? "rouvrir d'abord" : 'accès dégradé'}</span>}</td>
              <td className="num">{l.salles_rouvertes ? nb(l.salles_rouvertes) : '—'}</td>
              <td className="num">{l.solde_redeploiement ? (l.solde_redeploiement > 0 ? `+${nb(l.solde_redeploiement)}` : `−${nb(-l.solde_redeploiement)}`) : '—'}</td>
              <td className="num">{nb(l.ratio_maitre_apres)}</td>
              <td className="motif">{l.motif ?? ''}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>Total</td><td>{lignes.length} provinces</td><td className="num">{nb(somme((l) => l.eleves_horizon))}</td><td className="num">{nb(somme((l) => l.maitres))}</td>
            <td className="num">+{nb(somme((l) => l.enseignants_attribues))}</td><td className="num">{nb(somme((l) => l.salles))}</td>
            <td className="num">+{nb(somme((l) => l.salles_attribuees))}</td><td className="num">{nb(somme((l) => l.salles_rouvertes ?? 0))}</td>
            <td></td><td></td><td></td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
