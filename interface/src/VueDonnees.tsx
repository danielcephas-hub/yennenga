// Vue « Données » : ce que contient l'outil, et comment un technicien ajoute les données d'une nouvelle année.
import { useEffect, useState } from 'react'
import { controler, importer, retirerLot, lots as lireLots, typesDonnees, type Lot, type Rapport, type TypeDonnee } from './api'
import { nb } from './format'

// années proposées : celle qui suit la dernière publiée (la prochaine à déposer), puis les deux précédentes pour corriger
const listeAnnees = (reference: string) => {
  const a = Number(reference.slice(0, 4))
  return [a + 1, a, a - 1].map((x) => `${x}-${x + 1}`)
}

export default function VueDonnees({ anneeReference }: { anneeReference: string }) {
  const annees = listeAnnees(anneeReference)
  const [types, setTypes] = useState<Record<string, TypeDonnee>>({})
  const [lots, setLots] = useState<Lot[]>([])
  const [type, setType] = useState('primaire_province')
  const [annee, setAnnee] = useState(annees[0])
  const [chargement, setChargement] = useState<string | null>(null)
  const [fichier, setFichier] = useState<File | null>(null)
  const [rapport, setRapport] = useState<Rapport | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [jeton, setJeton] = useState('')
  const [auteur, setAuteur] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [suite, setSuite] = useState<string | null>(null)

  const recharger = () => { setChargement(null); return lireLots().then(setLots).catch(() => { setLots([]); setChargement('La liste des données en place n\'a pas pu être chargée.') }) }
  const toutRecharger = () => { typesDonnees().then(setTypes).catch(() => setChargement('Les types de fichiers n\'ont pas pu être chargés.')); recharger() }
  useEffect(() => { toutRecharger() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const agir = (f: () => Promise<Rapport>) => {
    setOccupe(true); setErreur(null); setRapport(null)
    f().then((r) => { setRapport(r); recharger() }).catch((e) => setErreur(String(e.message))).finally(() => setOccupe(false))
  }

  return (
    <div className="vue-donnees">
      <section className="carte-blanche" data-visite="ajout-donnees">
        <h2>Ajouter les données d'une nouvelle année</h2>
        <p>Chaque année, la direction des statistiques publie un nouvel annuaire. Il suffit de reporter ses chiffres dans le fichier type, puis de le déposer ici : l'outil le contrôle et, s'il est juste, l'intègre à tous les calculs. Aucune programmation n'est nécessaire.</p>
        <p className="encart"><b>Un fichier remplace toute l'année.</b> Il doit couvrir au moins 90 % des provinces ; une province laissée vide sera comptée comme inconnue cette année-là. Une case vide signifie « inconnu » : ne pas écrire 0.</p>
        <ol className="etapes">
          <li>
            <b>Télécharger le fichier Excel à remplir.</b>
            <div className="ligne-champs choix-fichier">
              <label className="champ-ligne"><span>Données</span>
                <select value={type} onChange={(e) => setType(e.target.value)}>
                  {Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v.libelle}</option>)}
                </select></label>
              <label className="champ-ligne"><span>Année scolaire</span>
                <select value={annee} onChange={(e) => setAnnee(e.target.value)}>{annees.map((a, i) => <option key={a} value={a}>{a}{i === 0 ? ' · nouvelle' : a === anneeReference ? ' · en place' : ' · en place'}</option>)}</select></label>
            </div>
            {annee === annees[0] ? (
              <div className="choix-telechargement">
                <a className="principal bouton" href={`/api/entrepot/gabarit/${type}/${annee}`}>Télécharger le fichier vide ({annee})</a>
                <p className="petit">Pour une <b>nouvelle année</b> : le fichier contient une ligne par province, à remplir avec les chiffres du nouvel annuaire.</p>
              </div>
            ) : (
              <div className="choix-telechargement">
                <a className="principal bouton" href={`/api/entrepot/donnees/${type}/${annee}`}>Télécharger les données en place ({annee})</a>
                <p className="petit">Pour <b>corriger une année déjà dans l'outil</b> : le fichier est prérempli avec les chiffres actuels ; modifiez les cases fausses puis déposez-le à l'étape 2. <a href={`/api/entrepot/gabarit/${type}/${annee}`}>Ou repartir d'un fichier vide</a>.</p>
              </div>
            )}
            <small>Codes des provinces verrouillés, onglet d'explications inclus, seuls des nombres positifs acceptés. Source habituelle : {types[type]?.source_habituelle}.</small>
          </li>
          <li>
            <b>Le remplir, puis le faire contrôler.</b> Le contrôle n'enregistre rien.
            <div className="ligne-champs">
              <input type="file" accept=".xlsx,.csv" aria-label="Fichier rempli (.xlsx ou .csv)" onChange={(e) => { setFichier(e.target.files?.[0] ?? null); setRapport(null) }} />
              <button className="secondaire" disabled={!fichier || occupe} onClick={() => fichier && agir(() => controler(type, fichier))}>Contrôler</button>
            </div>
          </li>
          <li>
            <b>L'importer</b> (administrateur). Le fichier est contrôlé de nouveau ; il est refusé tant qu'une anomalie bloquante subsiste.
            <div className="ligne-champs">
              <label className="champ-ligne"><span>Votre nom</span><input value={auteur} onChange={(e) => setAuteur(e.target.value)} autoComplete="name" /></label>
              <label className="champ-ligne"><span>Jeton d'administration</span><input type="password" value={jeton} onChange={(e) => setJeton(e.target.value)} autoComplete="off" /></label>
              <button className="principal" disabled={!fichier || !jeton || !auteur || occupe} onClick={() => fichier && agir(() => importer(type, fichier, auteur, jeton))}>Importer</button>
            </div>
            {(!fichier || !jeton || !auteur) && <p className="petit">Pour importer : {[!fichier && 'choisissez le fichier à l\'étape 2', !auteur && 'indiquez votre nom', !jeton && 'saisissez le jeton d\'administration'].filter(Boolean).join(', ')}.</p>}
          </li>
        </ol>
        {erreur && <p className="erreur" role="alert">{erreur}</p>}
        {chargement && <p className="erreur" role="alert">{chargement} <button className="secondaire" onClick={toutRecharger}>Réessayer</button></p>}
        {rapport && (
          <div className={rapport.accepte ? 'rapport rapport-ok' : 'rapport rapport-ko'}>
            <b>{rapport.accepte ? (rapport.lot ? `Importé : lot n° ${rapport.lot}` : 'Fichier accepté par le contrôle') : 'Fichier refusé : rien n\'a été enregistré'}</b>
            <span> · {nb(rapport.lignes)} lignes · {rapport.annees.length > 1 ? 'années' : 'année'} {rapport.annees.join(', ') || '—'} · découpage {rapport.decoupage_libelle || rapport.decoupage || '—'}</span>
            {rapport.bloquants.length > 0 && <><h3>À corriger ({rapport.bloquants.length})</h3><ul>{rapport.bloquants.map((b) => <li key={b} className="bloquant">{b}</li>)}</ul></>}
            {rapport.avertissements.length > 0 && <><h3>À vérifier ({rapport.avertissements.length})</h3><ul>{rapport.avertissements.map((a) => <li key={a}>{a}</li>)}</ul></>}
            {rapport.accepte && (rapport.apercu?.length ?? 0) > 0 && <><h3>Ce que l'import changera</h3><ul>{rapport.apercu!.map((a) => <li key={a}>{a}</li>)}</ul></>}
            {rapport.suite && <p className="petit">Prochaine étape : {rapport.suite}.</p>}
          </div>
        )}
      </section>

      <section className="carte-blanche">
        <h2>Ce que contient l'outil</h2>
        <p className="petit">Chaque dépôt est un lot daté, avec son auteur. Pour une année donnée, c'est le lot le plus récent qui fait foi ; retirer un lot rétablit le précédent. Rien n'est jamais effacé. {jeton ? '' : 'Le retrait d\'un lot est réservé à l\'administrateur : saisir le jeton plus haut.'}</p>
        {suite && <p className="encart">{suite}</p>}
        <div className="defile">
          <table className="tableau">
            <thead><tr><th>Lot</th><th>Données</th><th>Années</th><th>Lignes</th><th>Découpage</th><th>Déposé par</th><th>Date</th><th>État</th>{jeton && <th>Action</th>}</tr></thead>
            <tbody>
              {lots.map((l) => (
                <tr key={l.lot}>
                  <td>{l.lot}</td><td>{types[l.type_donnee]?.libelle ?? l.type_donnee}</td>
                  <td>{l.annees.split(',').length > 3 ? `${l.annees.split(',')[0]} à ${l.annees.split(',').slice(-1)[0]}` : l.annees.split(',').join(', ')}</td>
                  <td>{nb(l.lignes)}</td><td>{l.decoupage === 'reforme_2025' ? '2025 (17 régions)' : 'annuaires (13 régions)'}</td>
                  <td>{l.auteur.replace('systeme', 'système')}</td><td>{l.depose_le ? new Date(l.depose_le).toLocaleDateString('fr-FR') : '—'}</td><td>{l.statut === 'publie' ? 'en vigueur' : 'retiré'}</td>
                  {jeton && <td>{l.statut === 'publie' && <button className="lien" disabled={occupe || !auteur}
                    title={auteur ? '' : 'Indiquer votre nom plus haut'}
                    onClick={() => { if (window.confirm(`Retirer le lot n° ${l.lot} ? La version précédente de ses années refera foi ; rien n'est effacé.`)) { setOccupe(true); retirerLot(l.lot, auteur, jeton).then((r) => { setErreur(null); setSuite(r.suite); recharger() }).catch((e) => setErreur(String(e.message))).finally(() => setOccupe(false)) } }}>Retirer</button>}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="carte-blanche">
        <h2>Le découpage territorial peut changer</h2>
        <p>Provinces et régions sont des regroupements de communes, décrits dans des tables datées. Quand une province est créée, scindée ou renommée, on déclare le nouveau découpage : les données déposées dans l'ancien sont relues dans le nouveau, exactement quand des provinces se regroupent, au prorata de la population des communes quand une province est scindée (valeurs alors marquées « estimées »). L'outil connaît aujourd'hui deux découpages : celui des annuaires (13 régions, 45 provinces) et celui de 2025 (17 régions, 47 provinces).</p>
      </section>
    </div>
  )
}
