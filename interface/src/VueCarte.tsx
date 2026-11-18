// Vue « Carte » : du pays à la province (45 provinces des annuaires), puis à la commune (351) et aux sites proposés.
import { Suspense, lazy, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ecouter } from './visiteActions'
import { Legende, couleurDe, type Point } from './Legende'
import { connexionLente, setModeLeger } from './connexion'
import Courbe from './Courbe'
import Aide from './Aide'
import { donnees, type Annees, type Commune, type Meta, type ProvAnnee, type Province, type Site } from './api'
import { joli, nb, pct } from './format'
import { exporterCommune, exporterProvince } from './export'
import { COULEUR_CONSTRUIRE, COULEUR_ROUVRIR, INDICATEURS_COMMUNE, INDICATEURS_PROVINCE, ratio } from './indicateurs'

type FC = GeoJSON.FeatureCollection

// recherche d'un lieu sans tenir compte des accents ni des majuscules (« Koulpelogo » trouve le Koulpélogo)
const sansAccent = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()

// le moteur de carte (250 ko) n'est téléchargé que si la carte s'affiche (pas en mode léger)
const Carte = lazy(() => import('./Carte'))

type LigneLieu = { id: string; nom: string; sous: string; v: number | null }

// Mode léger : la carte devient une liste classée, de la valeur la plus forte à la plus faible
function ListeLieux({ lignes, indicateur, choix, choisir, charge, afficherCarte }: {
  lignes: LigneLieu[]; indicateur: { libelle: string; classes: import('./Legende').Classes; format: (x: number) => string }
  choix: string | null; choisir: (id: string) => void; charge: boolean; afficherCarte: () => void
}) {
  const triees = [...lignes].sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity))
  return (
    <div className="liste-lieux">
      <div className="entete-tableau">
        <p className="petit"><b>Mode léger</b> : la carte est remplacée par cette liste, pour économiser la connexion.</p>
        <button className="lien" onClick={afficherCarte}>Afficher la carte (≈ 300 ko)</button>
      </div>
      {!charge ? <p className="petit">Chargement…</p> : (
        <ol>
          {triees.map((l) => (
            <li key={l.id}>
              <button className={l.id === choix ? 'actif' : ''} onClick={() => choisir(l.id)}>
                <span className="pastille" style={{ background: couleurDe(indicateur.classes, l.v) }} />
                <span className="nom">{l.nom} <small>{l.sous}</small></span>
                <b>{l.v == null ? '—' : indicateur.format(l.v)}</b>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

export default function VueCarte({ meta }: { meta: Meta }) {
  const [niveau, setNiveau] = useState<'provinces' | 'communes'>('provinces')
  const [indP, setIndP] = useState(INDICATEURS_PROVINCE[0].cle)
  const [indC, setIndC] = useState(INDICATEURS_COMMUNE[0].cle)
  const [geoP, setGeoP] = useState<FC | null>(null)
  const [geoC, setGeoC] = useState<FC | null>(null)
  const [geoR, setGeoR] = useState<FC | null>(null)
  const [provinces, setProvinces] = useState<Province[]>([])
  const [communes, setCommunes] = useState<Commune[]>([])
  const [sites, setSites] = useState<Site[]>([])
  const [voirConstruire, setVoirConstruire] = useState(true)
  const [voirRouvrir, setVoirRouvrir] = useState(true)
  const [choix, setChoix] = useState<string | null>(null)
  const [site, setSite] = useState<Site | null>(null)
  const [cadre, setCadre] = useState<string | null>(null) // province des annuaires dont on regarde les communes
  const [recherche, setRecherche] = useState('')
  const [leger, setLeger] = useState(connexionLente)
  const [obs, setObs] = useState<Annees | null>(null)
  const [annee, setAnnee] = useState(meta.annee_reference)
  // sur téléphone, la fiche est sous la carte : on y descend quand un lieu est choisi
  useEffect(() => {
    if (!choix || window.innerWidth > 980) return
    window.setTimeout(() => document.querySelector('.fiche')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150)
  }, [choix])

  useEffect(() => {
    donnees<Province[]>('provinces').then(setProvinces)
    donnees<Annees>('provinces_annees').then(setObs).catch(() => setObs(null))
  }, [])
  useEffect(() => { if (!leger && !geoP) donnees<FC>('geo_provinces_annuaires').then(setGeoP) }, [leger, geoP])
  // connexions lentes : les communes (contours, chiffres, sites) ne se chargent qu'à la première ouverture du niveau
  useEffect(() => {
    if (niveau !== 'communes') return
    if (!communes.length) {
      donnees<Commune[]>('communes').then(setCommunes)
      donnees<Site[]>('sites').then(setSites)
    }
    // contours : seulement si la carte s'affiche
    if (!leger && !geoC) {
      donnees<FC>('geo_communes').then(setGeoC)
      donnees<FC>('geo_regions_2025').then(setGeoR)
    }
  }, [niveau, geoC, leger, communes.length])

  const parProvince = useMemo(() => Object.fromEntries(provinces.map((p) => [p.province, p])), [provinces])
  const rangCharge = useMemo(() => Object.fromEntries([...provinces].filter((p) => p.eleves_par_maitre != null)
    .sort((a, b) => (b.eleves_par_maitre ?? 0) - (a.eleves_par_maitre ?? 0)).map((p, i) => [p.province, i + 1])), [provinces])
  const parCommune = useMemo(() => Object.fromEntries(communes.map((c) => [c.pcode_commune, c])), [communes])
  const ip = INDICATEURS_PROVINCE.find((i) => i.cle === indP)!
  const ic = INDICATEURS_COMMUNE.find((i) => i.cle === indC)!

  // indicateur observé chaque année : valeur de l'année choisie ; calcul de l'outil : 2024-2025
  const annuel = Boolean(ip.annuel && obs)
  const anCarte = annuel ? annee : meta.annee_reference
  const valP = (p: Province) => (ip.annuel && obs ? ip.annuel(obs.valeurs[annee]?.[p.province] ?? {}) : ip.valeur(p))
  const valeurs = useMemo(
    () =>
      niveau === 'provinces'
        ? Object.fromEntries(provinces.map((p) => [p.province, valP(p)]))
        : Object.fromEntries(communes.map((c) => [c.pcode_commune, ic.valeur(c)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [niveau, provinces, communes, ip, ic, obs, annee],
  )

  const cadrage = useMemo<FC | null>(() => {
    if (niveau !== 'communes' || !geoC || !cadre) return null
    return { type: 'FeatureCollection', features: geoC.features.filter((f) => f.properties?.province_ancienne === cadre) }
  }, [niveau, geoC, cadre])

  const points: Point[] = useMemo(
    () =>
      niveau === 'communes'
        ? sites.filter((s) => (s.recommandation === 'construire' ? voirConstruire : voirRouvrir)).map((s) => ({
            id: String(s.rang), lon: s.lon, lat: s.lat,
            couleur: s.recommandation === 'construire' ? COULEUR_CONSTRUIRE : COULEUR_ROUVRIR,
            creux: s.recommandation !== 'construire', ordre: s.recommandation === 'construire' ? 2 : 1,
            taille: Math.max(3, Math.min(9, Math.sqrt(s.enfants_rapproches) / 4)),
            titre: `<b>Site n° ${s.rang}</b> · ${s.commune}<br>${nb(s.enfants_rapproches)} enfants rapprochés<br><i>${s.recommandation}</i>`,
          }))
        : [],
    [niveau, voirConstruire, voirRouvrir, sites],
  )

  const infobulle = (id: string) => {
    if (niveau === 'provinces') {
      const p = parProvince[id]
      const v = p ? valP(p) : null
      return `<b>${joli(id)}</b><br>${ip.libelle} en ${anCarte} : ${v == null ? '—' : ip.format(v)}`
    }
    const c = parCommune[id]
    const v = c ? ic.valeur(c) : null
    return c ? `<b>${c.commune}</b> (${c.province})<br>${ic.libelle} : ${v == null ? '—' : ic.format(v)}` : id
  }

  const ouvrirCommunes = (prov: string) => {
    setNiveau('communes'); setCadre(prov); setChoix(null); setSite(null); setRecherche('')
  }

  // visite guidée : ouvrir la fiche d'une province, ou ses communes
  useEffect(() => ecouter(['province', 'communes'], (a) => {
    if (!a.arg) return
    if (a.action === 'province') { setNiveau('provinces'); setCadre(null); setSite(null); setChoix(a.arg) }
    else ouvrirCommunes(a.arg)
  }), [])

  const indicateur = niveau === 'provinces' ? ip : ic
  const sitesCommune = choix && niveau === 'communes' ? sites.filter((s) => s.pcode_commune === choix) : []

  return (
    <div className="vue-carte">
      <h1 className="visuellement-masque">Carte des besoins par province et par commune</h1>
      <aside className="panneau" data-visite="panneau-carte">
        <div className="segments" role="group" aria-label="Niveau de la carte">
          <button aria-pressed={niveau === 'provinces'} className={niveau === 'provinces' ? 'actif' : ''} onClick={() => { setNiveau('provinces'); setChoix(null); setCadre(null); setSite(null); setRecherche('') }}>
            Provinces <small>45</small>
          </button>
          <button aria-pressed={niveau === 'communes'} className={niveau === 'communes' ? 'actif' : ''} onClick={() => { setNiveau('communes'); setChoix(null) }} data-visite="bouton-communes">
            Communes <small>351</small>
          </button>
        </div>
        <label className="champ">
          <span>Aller à {niveau === 'provinces' ? 'une province' : 'une commune'}</span>
          <input list="liste-lieux" placeholder="Tapez un nom…" value={recherche}
            onChange={(e) => {
              const v = e.target.value
              setRecherche(v)
              const id = niveau === 'provinces'
                ? provinces.find((p) => sansAccent(joli(p.province)) === sansAccent(v))?.province
                : communes.find((c) => sansAccent(c.commune) === sansAccent(v))?.pcode_commune
              if (id) { setChoix(id); setSite(null) }
            }} />
          <datalist id="liste-lieux">
            {niveau === 'provinces'
              ? provinces.map((p) => <option key={p.province} value={joli(p.province)} />)
              : communes.map((c) => <option key={c.pcode_commune} value={c.commune}>{c.province}</option>)}
          </datalist>
        </label>
        <label className="champ">
          <span>Indicateur</span>
          {niveau === 'provinces' ? (
            <select value={indP} onChange={(e) => setIndP(e.target.value)}>
              {INDICATEURS_PROVINCE.map((i) => <option key={i.cle} value={i.cle}>{i.libelle}</option>)}
            </select>
          ) : (
            <select value={indC} onChange={(e) => setIndC(e.target.value)}>
              {INDICATEURS_COMMUNE.map((i) => <option key={i.cle} value={i.cle}>{i.libelle}</option>)}
            </select>
          )}
        </label>
        {niveau === 'provinces' && obs && (annuel ? (
          <label className="champ annee-choix">
            <span>Année scolaire : <b>{annee}</b></span>
            <input type="range" min={0} max={obs.annees.length - 1} step={1} value={Math.max(0, obs.annees.indexOf(annee))}
              aria-valuetext={annee} onChange={(e) => setAnnee(obs.annees[Number(e.target.value)])} />
            <span className="bornes-annee"><small>{obs.annees[0]}</small><small>{obs.annees[obs.annees.length - 1]}</small></span>
          </label>
        ) : <p className="petit">Calcul de l'outil sur {meta.annee_reference} : pas d'historique pour cet indicateur. Les élèves par enseignant, par salle, la part du privé et les salles précaires se consultent de {obs.annees[0]} à {obs.annees[obs.annees.length - 1]}.</p>)}
        <p className="aide">{indicateur.aide}</p>
        <div className={leger ? undefined : "legende-panneau"}><Legende classes={indicateur.classes} format={indicateur.format} titre={niveau === 'provinces' ? `${indicateur.libelle} · ${anCarte}` : indicateur.libelle} /></div>
        {niveau === 'communes' && (
          <>
            <fieldset className="sites-choix">
              <legend>Zones sans école à moins de {meta.implantation.rayon_km} km</legend>
              <label className="case">
                <input type="checkbox" checked={voirConstruire} onChange={(e) => setVoirConstruire(e.target.checked)} />
                <span className="rond" style={{ background: COULEUR_CONSTRUIRE }} />construire ({meta.national.sites_construire})
              </label>
              <label className="case">
                <input type="checkbox" checked={voirRouvrir} onChange={(e) => setVoirRouvrir(e.target.checked)} />
                <span className="rond creux" style={{ borderColor: COULEUR_ROUVRIR }} />rouvrir ou délocaliser d'abord ({meta.national.sites - meta.national.sites_construire})
              </label>
              <p className="petit">Taille : enfants rapprochés. Sites choisis pour rapprocher le plus d'enfants (WorldPop 2030, écoles OpenStreetMap).</p>
            </fieldset>
            {cadre && <button className="lien" onClick={() => setCadre(null)}>← Tout le pays</button>}
          </>
        )}
        <p className="petit">Provinces : découpage des annuaires (45). Communes : découpage de 2025 (17 régions, 47 provinces).</p>
        {!leger && <button className="lien bouton-leger" onClick={() => { setModeLeger(true); setLeger(true) }}>Voir en liste (mode léger, sans carte)</button>}
      </aside>

      <section className="zone-carte" data-visite="carte">
        {leger ? (
          <ListeLieux
            lignes={niveau === 'provinces'
              ? provinces.map((p) => ({ id: p.province, nom: joli(p.province), sous: joli(p.region), v: valeurs[p.province] ?? null }))
              : communes.filter((c) => !cadre || c.province_ancienne === cadre).map((c) => ({ id: c.pcode_commune, nom: c.commune, sous: c.province, v: valeurs[c.pcode_commune] ?? null }))}
            indicateur={indicateur} choix={choix} choisir={(id) => { setChoix(id); setSite(null) }}
            charge={niveau === 'provinces' ? provinces.length > 0 : communes.length > 0}
            afficherCarte={() => { setModeLeger(false); setLeger(false) }} />
        ) : (
          <Suspense fallback={<div className="squelette-carte" aria-busy="true"><p>Chargement de la carte…</p></div>}>
            <div className="legende-sur-carte"><Legende classes={indicateur.classes} format={indicateur.format} titre={niveau === 'provinces' ? `${indicateur.libelle} · ${anCarte}` : indicateur.libelle} /></div>
            <Carte
              zones={niveau === 'provinces' ? geoP : geoC}
              idProp={niveau === 'provinces' ? 'province' : 'pcode_commune'}
              valeurs={valeurs}
              classes={indicateur.classes}
              contours={niveau === 'communes' ? geoR : null}
              points={points}
              selection={choix}
              cadrage={cadrage}
              infobulle={infobulle}
              surClic={(id) => { setChoix(id); setSite(null) }}
              surClicPoint={(id) => setSite(sites.find((s) => String(s.rang) === id) ?? null)}
            />
          </Suspense>
        )}
      </section>

      <aside className="fiche" aria-live="polite" aria-label="Fiche du lieu choisi" data-visite="fiche">
        {site ? <FicheSite s={site} fermer={() => setSite(null)} meta={meta} />
          : !choix ? <AideFiche niveau={niveau} />
          : niveau === 'provinces' && parProvince[choix] ? <FicheProvince p={parProvince[choix]} meta={meta} ouvrir={ouvrirCommunes} rangCharge={rangCharge[choix]} nbProvinces={provinces.length}
              annee={annuel ? annee : meta.annee_reference} obs={obs} />
          : niveau === 'communes' && parCommune[choix] ? <FicheCommune c={parCommune[choix]} sites={sitesCommune} meta={meta} />
          : null}
      </aside>
    </div>
  )
}

function AideFiche({ niveau }: { niveau: string }) {
  return (
    <div className="fiche-vide">
      <h3>Cliquez sur {niveau === 'provinces' ? 'une province' : 'une commune'}</h3>
      <p>La fiche donne ses chiffres clés, sa place dans les priorités et {niveau === 'provinces' ? 'l\'évolution de ses effectifs avec la prévision' : 'l\'accès des enfants à l\'école'}.</p>
    </div>
  )
}

function Ligne({ l, v, n, aide }: { l: string; v: string; n?: string; aide?: ReactNode }) {
  return (
    <div className="kv">
      <span>{l}{aide && <Aide titre={`Explication : ${l}`}>{aide}</Aide>}</span><b>{v}</b>{n && <small>{n}</small>}
    </div>
  )
}

function FicheProvince({ p, meta, ouvrir, annee, obs, rangCharge, nbProvinces }: { p: Province; meta: Meta; ouvrir: (prov: string) => void; annee: string; obs: Annees | null; rangCharge?: number; nbProvinces: number }) {
  const norme = meta.normes.eleves_par_maitre
  const ind = meta.indice
  const poids = (d: string) => (ind ? pct(ind.ponderations[d] / Object.values(ind.ponderations).reduce((a, b) => a + b, 0), 0) : '')
  const o: ProvAnnee = obs?.valeurs[annee]?.[p.province] ?? {}
  const pu = o.pu, pr = o.pr
  // écoles ouvertes : année où la province en comptait le plus (public et privé)
  const pic = obs ? obs.annees.map((a) => [a, obs.valeurs[a]?.[p.province]?.t?.ec ?? 0] as const).reduce((m, x) => (x[1] > m[1] ? x : m), ['', 0] as readonly [string, number]) : null
  const ouvertes = obs?.valeurs[meta.annee_reference]?.[p.province]?.t?.ec
  const partPrive = ratio(pr?.e ?? 0, o.t?.e)
  const report = pr?.e ? Math.round(0.2 * pr.e) : 0
  const epm = ratio(pu?.e, pu?.m)
  // filles pour 100 garçons inscrits (public et privé) : la province, le pays, et la première année disponible
  const f100 = (x?: ProvAnnee) => (x?.t?.f != null && x.t.g ? (100 * x.t.f) / x.t.g : null)
  const fP = f100(o)
  const an0 = obs?.annees[0]
  const fP0 = an0 ? f100(obs?.valeurs[an0]?.[p.province]) : null
  const pays = obs ? Object.values(obs.valeurs[annee] ?? {}).reduce((t, x) => ({ f: t.f + (x.t?.f ?? 0), g: t.g + (x.t?.g ?? 0) }), { f: 0, g: 0 }) : null
  const fPays = pays && pays.g ? (100 * pays.f) / pays.g : null
  return (
    <div>
      <p className="surtitre">Province · {joli(p.region)}</p>
      <h2>{joli(p.province)}</h2>
      {p.rang != null && (
        <div className="pastille-rang">
          {rangCharge != null && (
            <p className="phrase-rang">{rangCharge === 1 ? <>La plus chargée du pays</> : <>{rangCharge}<sup>e</sup> plus chargée du pays</>} ({nb(p.eleves_par_maitre)} élèves par enseignant dans le public)
              {Math.abs(rangCharge - p.rang) >= 3 && p.score_surcharge != null && p.score_bati != null
                ? (p.rang > rangCharge
                  ? <>, mais {p.rang}<sup>e</sup> priorité : ses salles sont en meilleur état qu'ailleurs (bâti {nb(p.score_bati, 2)} sur 1, contre surcharge {nb(p.score_surcharge, 2)}), et l'indice tient compte des deux.</>
                  : <>, et {p.rang}<sup>e</sup> priorité : l'état de ses salles (bâti {nb(p.score_bati, 2)} sur 1) la fait remonter.</>)
                : <> : {p.rang}<sup>e</sup> priorité.</>}</p>
          )}
          <p><b>Priorité n° {p.rang} sur {nbProvinces}</b> <small>(n° 1 = la plus en difficulté selon l'indice de besoin)</small></p>
          {p.score_surcharge != null && p.score_bati != null && (
            <p className="petit">Le rang combine la surcharge des classes (note {nb(p.score_surcharge, 2)} sur 1) et l'état du bâti (note {nb(p.score_bati, 2)} sur 1).
              {rangCharge == null && p.score_surcharge - p.score_bati >= 0.4 && <> Ses classes sont parmi les plus chargées, mais ses salles sont en meilleur état qu'ailleurs : d'où ce rang.</>}</p>
          )}
          {p.rang_p05 != null && p.rang_p95 != null && ind && (
            <p className="petit">Selon le poids donné à la surcharge des classes (de {pct(ind.plage_surcharge[0], 0)} à {pct(ind.plage_surcharge[1], 0)}), son rang va de {p.rang_p05} à {p.rang_p95}.
              {p.rang_instable
                ? <> <span className="etat-pastille attention">classement à confirmer</span> Sur {nb(ind.tirages)} essais avec des poids différents, elle change de tiers (haut, milieu, bas du classement) dans plus de {pct(ind.seuil_changement_tiers, 0)} des cas : sa place dépend du poids choisi.</>
                : <> Classement stable : elle reste dans le même tiers quel que soit le poids.</>}
            </p>
          )}
        </div>
      )}
      <h4>Observé en {annee} · écoles publiques</h4>
      <Ligne l="Élèves" v={nb(pu?.e ?? p.eleves)} />
      <Ligne l="Élèves par enseignant" v={nb(epm ?? p.eleves_par_maitre)} n={(epm ?? 0) > norme ? `norme ${norme}` : undefined} />
      <Ligne l="Élèves par salle" v={nb(ratio(pu?.e, pu?.s) ?? p.eleves_par_salle)} />
      <Ligne l="Salles en paille ou banco" v={pct(pu?.prec ?? p.part_salles_precaires)} />
      <p className="source">Source : annuaire statistique du primaire {annee} (DGESS). Choisir l'année avec le curseur, à gauche.</p>

      {o.t?.e != null && (
        <>
          <h4>Public et privé en {annee}</h4>
          <table className="tableau compact pub-prive">
            <thead><tr><th></th><th className="num">Public</th><th className="num">Privé</th></tr></thead>
            <tbody>
              <tr><td>Élèves</td><td className="num">{nb(pu?.e)}</td><td className="num">{nb(pr?.e ?? 0)}</td></tr>
              <tr><td>Enseignants</td><td className="num">{nb(pu?.m)}</td><td className="num">{nb(pr?.m ?? 0)}</td></tr>
              <tr><td>Élèves par enseignant</td><td className="num">{nb(epm)}</td><td className="num">{pr?.m ? nb(ratio(pr.e, pr.m)) : '—'}</td></tr>
              <tr><td>Écoles</td><td className="num">{nb(pu?.ec)}</td><td className="num">{nb(pr?.ec ?? 0)}</td></tr>
            </tbody>
          </table>
          <p className="petit">
            {!pr?.e ? <>Aucun élève dans le privé : l'État est le seul acteur de la province.</>
              : <>Le privé scolarise <b>{pct(partPrive, 0)}</b> des élèves. L'État n'y affecte pas d'enseignants : l'outil répartit les moyens sur le public.
                {(partPrive ?? 0) >= 0.15 && <> Si un élève du privé sur cinq passait au public, cela ferait environ {nb(report)} élèves de plus, soit {nb(Math.ceil(report / norme))} enseignants à la norme de {norme}. Simulable dans l'onglet Répartition.</>}</>}
          </p>
        </>
      )}
      {fP != null && (
        <Ligne l={`Filles pour 100 garçons inscrits, ${annee}`} v={nb(fP)}
          n={`pays : ${nb(fPays, 1)}${fP0 != null && an0 !== annee ? ` ; en ${an0} : ${nb(fP0)}` : ''} · public et privé, annuaires DGESS`}
          aide={<>100 = autant de filles que de garçons à l'école. En dessous, des filles manquent, souvent retirées plus tôt de l'école. L'outil répartit les enseignants selon la charge des classes ; cet indicateur signale où accompagner l'arrivée des moyens d'actions pour la scolarisation des filles.</>} />
      )}

      <h4>Calculs de l'outil (sur {meta.annee_reference})</h4>
      <Ligne l="Indice de besoin" v={nb(p.indice_besoin, 2)} n="0 = la mieux placée, 1 = la plus en difficulté"
        aide={<>Deux dimensions. <b>Surcharge</b> (poids {poids('surcharge')}) : élèves par enseignant et par salle. <b>Bâti</b> (poids {poids('bati')}) : salles en paille ou banco et salles en mauvais état.
          Pour chaque indicateur, la province reçoit son rang parmi les 45, ramené entre 0 et 1 ; l'indice est la moyenne pondérée.
          Ici : surcharge {nb(p.score_surcharge, 2)}, bâti {nb(p.score_bati, 2)}.</>} />
      <Ligne l="Écoles fermées" v={pct(p.part_ecoles_fermees)}
        n={pic && ouvertes != null ? (ouvertes >= pic[1]
          ? `aucune baisse : ${nb(ouvertes)} écoles ouvertes en ${meta.annee_reference}, le plus haut niveau depuis ${obs?.annees[0].slice(0, 4)}`
          : `${nb(ouvertes)} écoles ouvertes en ${meta.annee_reference}, contre ${nb(pic[1])} en ${pic[0]}, l'année où elles étaient le plus nombreuses`) : undefined}
        aide={<>Part des écoles (public et privé) qui ne fonctionnent plus par rapport à l'année où la province en comptait le plus, entre 2017 et 2025. Au-delà de {pct(meta.implantation.seuil_fermeture_rouvrir, 0)}, l'outil propose de rouvrir ces écoles avant de construire.</>} />

      <h4>Dans un plan type ({nb(meta.defauts.enseignants)} enseignants, {nb(meta.defauts.salles)} salles)</h4>
      <p className="petit">Exemple calculé avec les réglages par défaut de l'onglet Répartition, où vous pouvez changer les moyens.</p>
      <Ligne l="Enseignants reçus" v={nb(p.enseignants_attribues)} />
      <Ligne l="Salles reçues" v={nb(p.salles_attribuees)} n={p.construction_possible === false ? 'construction non programmée : rouvrir d\'abord ou accès trop dégradé' : undefined} />
      <Ligne l={`Élèves par enseignant en ${meta.annee_horizon.slice(0, 4)}, avec ce plan`} v={nb(p.ratio_maitre_apres)} />
      <h4>Élèves inscrits et prévision</h4>
      <Courbe serie={p.serie} prevision={p.prevision.tendance} />
      <p className="petit">Trait plein : observé (public et privé). Pointillé : prévision tendancielle, avec sa marge.</p>
      <button className="principal" onClick={() => ouvrir(p.province)}>Voir ses communes et les sites proposés →</button>
      <button className="secondaire bouton-extraire" onClick={() => exporterProvince(p, meta, obs)} title="Toutes les données de la fiche, l'évolution 2017-2025, la série des élèves et la prévision, en fichier lisible par Excel">Télécharger les données de la province</button>
    </div>
  )
}

function FicheCommune({ c, sites, meta }: { c: Commune; sites: Site[]; meta: Meta }) {
  const r = meta.implantation.rayon_km
  return (
    <div>
      <p className="surtitre">Commune · province {c.province} (découpage 2025){c.province_ancienne && joli(c.province_ancienne) !== c.province ? ` · ${joli(c.province_ancienne)} dans les annuaires` : ''} · région {c.region}</p>
      <h2>{c.commune}</h2>
      <button className="secondaire bouton-extraire" onClick={() => exporterCommune(c, sites, meta)} title="Toutes les données de la fiche et les sites proposés, en fichier lisible par Excel">Télécharger les données de la commune</button>
      <p className="encart petit">Les annuaires ne publient ni enseignants ni salles par commune : la commune sert à <b>localiser</b> les enfants, l'accès à l'école et les déplacés, et à placer les sites. Les moyens se répartissent par province (onglet Répartition). Chaque chiffre porte son année et sa source.</p>
      {c.population_estimee_insd && <p className="alerte">Population {c.population_estimee_insd} en 2019 : effectifs estimés par l'INSD.</p>}
      <h4>Population</h4>
      <Ligne l="Habitants en 2019" v={nb(c.population_2019)} n="Recensement général (RGPH) 2019, INSD : le plus récent par commune" />
      <Ligne l="Enfants de 6 à 11 ans en 2019" v={nb(c.enfants_6_11_2019)} n="RGPH 2019, INSD" />
      <Ligne l={`Enfants de 6 à 11 ans en ${meta.annee_horizon.slice(0, 4)}`} v={nb(c.enfants_6_11_2030)} n="Calcul de l'outil à partir des projections INSD de la province"
        aide={<>Il n'existe pas de projection officielle par commune. L'outil répartit la projection INSD de la province (2020-2035) entre ses communes selon leur part d'enfants en 2019, la méthode de l'INSD : le total reste égal à la projection officielle.</>} />
      <h4>Accès à l'école (à moins de {r} km)</h4>
      <Ligne l="Enfants loin d'une école, au minimum" v={nb(c.eloignes_borne_basse)} n={`${pct(c.part_eloignes_basse, 1)} des enfants · population WorldPop calée sur l'INSD, ${meta.annee_horizon.slice(0, 4)}`}
        aide={<>Les écoles de l'annuaire qui manquent sur OpenStreetMap sont placées au plus près des enfants : c'est l'hypothèse la plus favorable, donc un minimum.</>} />
      <Ligne l="Enfants loin d'une école, au maximum" v={nb(c.eloignes_borne_haute)} n={`${pct(c.part_eloignes_haute, 0)} des enfants · avec les seules écoles d'OpenStreetMap : un maximum`} />
      <Ligne l="Écoles repérées sur OpenStreetMap" v={nb(c.sites_scolaires_osm)} n="liste partielle : environ un tiers des écoles de l'annuaire" />
      <h4>Contexte</h4>
      {c.pdi_releve === false
        ? <Ligne l="Déplacés accueillis (fin 2022)" v="non relevé" n="commune absente du relevé CONASUR" />
        : <Ligne l="Déplacés accueillis (fin 2022)" v={nb(c.pdi_total)} n={`${pct(c.part_pdi_population)} de la population de 2019 · CONASUR, dernier relevé par commune`} />}
      <Ligne l="Écoles fermées dans la province" v={pct(c.part_ecoles_fermees_province)} n={`annuaires ${meta.annee_reference}, comparés à l'année où la province comptait le plus d'écoles`} />
      {c.construction_programmee === false && <p className="alerte">Province où la construction n'est pas programmée (accès trop dégradé).</p>}
      <h4>Sites proposés dans la commune</h4>
      {sites.length === 0 ? <p className="petit">Aucun.</p> : (
        <ul className="liste-sites">
          {sites.map((s) => (
            <li key={s.rang}>
              <span className={s.recommandation === 'construire' ? 'rond' : 'rond creux'} style={s.recommandation === 'construire' ? { background: COULEUR_CONSTRUIRE } : { borderColor: COULEUR_ROUVRIR }} />
              n° {s.rang} · {nb(s.enfants_rapproches)} enfants · {s.recommandation}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function FicheSite({ s, fermer, meta }: { s: Site; fermer: () => void; meta: Meta }) {
  return (
    <div>
      <button className="lien" onClick={fermer}>← Retour</button>
      <p className="surtitre">Site proposé · rang {s.rang} sur {meta.national.sites}</p>
      <h2>{s.commune}</h2>
      <Ligne l="Province" v={s.province} />
      <Ligne l="Enfants rapprochés à moins de 3 km" v={nb(s.enfants_rapproches)} />
      <Ligne l="Coordonnées" v={`${s.lat.toFixed(4)} N, ${Math.abs(s.lon).toFixed(4)} ${s.lon < 0 ? 'O' : 'E'}`} />
      <Ligne l="Écoles fermées dans la province" v={pct(s.part_ecoles_fermees_province)} />
      <p className={s.recommandation === 'construire' ? 'reco reco-construire' : 'reco reco-rouvrir'}>
        {s.recommandation === 'construire'
          ? 'Recommandation : construire. Le manque d\'école ne s\'explique pas par des fermetures.'
          : `Recommandation : rouvrir ou délocaliser d'abord. La province a perdu ${pct(s.part_ecoles_fermees_province)} de ses écoles ouvertes : l'éloignement vient surtout des fermetures.`}
      </p>
      <p className="petit">À vérifier sur le terrain : un site est une maille de 1 km, choisie pour rapprocher le plus d'enfants restés à plus de 3 km d'une école même dans l'hypothèse la plus favorable.</p>
    </div>
  )
}
