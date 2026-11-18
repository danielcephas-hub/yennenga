// Accueil : la question, le résultat en trois chiffres, le contexte, puis les trois usages de l'outil.
import { useState } from 'react'
import type { Meta } from './api'
import { joli, nb, pct } from './format'

type Props = { meta: Meta; aller: (vue: string) => void; visite: () => void }

export default function VueAccueil({ meta, aller, visite }: Props) {
  const n = meta.national
  const h = meta.annee_horizon.slice(0, 4)
  const pr = meta.plan_reference
  const retro = pr?.retrospectif?.[0]
  // le chiffre du ministre : élèves sortis des classes surchargées pour un milliard de FCFA, plan Yennenga et partage simple
  const md = pr?.cout_fcfa ? pr.cout_fcfa / 1e9 : null
  const sortisO = pr?.surnombre_avant != null && pr.surnombre_optimisee != null ? pr.surnombre_avant - pr.surnombre_optimisee : null
  const sortisP = pr?.surnombre_avant != null && pr.surnombre_proportionnelle != null ? pr.surnombre_avant - pr.surnombre_proportionnelle : null
  const gainArgent = sortisO != null && sortisP ? sortisO / sortisP - 1 : null
  return (
    <div className="accueil">
      <div className="entree">
      <section className="intro">
        <p className="surtitre">Outil d'aide à la décision · enseignement primaire · Burkina Faso</p>
        <h1>Où affecter les enseignants, où construire ou rouvrir des classes ?</h1>
        <p>Yennenga mesure les besoins de chaque province et de chaque commune, prévoit les effectifs jusqu'en {h} et calcule
          la répartition qui soulage d'abord les classes les plus chargées, avec vos moyens et vos exigences.</p>
        <div className="boutons">
          <button className="principal" onClick={visite} data-visite="demarrer">Découvrir l'outil en 2 minutes</button>
          <button className="secondaire" onClick={() => aller('repartition')}>Calculer un plan</button>
        </div>
      </section>
      <Demonstration />
      </div>

      {pr && (
        <section className="resultats-cles" data-visite="resultat" aria-label="Résultats clés">
          <h2>Ce que l'outil change, avec {nb(pr.enseignants)} enseignants et {nb(pr.salles)} salles</h2>
          <div className="cles">
            {sortisO != null && sortisP != null && (
              <div className="cle cle-phare">
                <b>{nb(sortisO)}</b>
                <span>élèves sortis des classes surchargées, contre {nb(sortisP)} en partageant les mêmes moyens selon le nombre d'élèves (sur {nb(pr.surnombre_avant)} élèves en trop aujourd'hui).</span>
              </div>
            )}
            {gainArgent != null && md && sortisO != null && sortisP != null && (
              <div className="cle">
                <b>+{pct(gainArgent, 0)}</b>
                <span>pour le même argent : {nb(sortisO / md)} élèves sortis de la surcharge par milliard de FCFA, contre {nb(sortisP / md)} ({nb(md, 1)} milliards, salaires comptés sur {meta.couts.annees_budget} ans).</span>
              </div>
            )}
            <div className="cle cle-province">
              {pr.province_pire_avant && pr.province_pire_avant_apres?.optimisee != null ? (
                <>
                  <b><span className="avant">{nb(pr.pire_avant)}</span><span className="fleche" aria-label="devient">→</span>{nb(pr.province_pire_avant_apres.optimisee)}</b>
                  <span>élèves par enseignant au {joli(pr.province_pire_avant)}, la province la plus chargée aujourd'hui, à la rentrée {h} (norme : {meta.normes.eleves_par_maitre}).
                    Avec la meilleure règle simple (partage selon les manques) : {nb(pr.province_pire_avant_apres.besoins)}.
                    {pr.province_pire_apres && <> Après le plan, la plus chargée est {joli(pr.province_pire_apres)} ({nb(pr.province_pire_apres_ratio)}), faute de salles.</>}</span>
                </>
              ) : (
                <>
                  <b><span className="avant">{nb(pr.pire_avant)}</span><span className="fleche" aria-label="devient">→</span>{nb(pr.pire_optimisee)}</b>
                  <span>élèves par enseignant dans la province la plus chargée en {h} (norme : {meta.normes.eleves_par_maitre}).</span>
                </>
              )}
            </div>
            {retro && (
              <div className="cle">
                <b>−{pct(-retro.ecart, 0)}</b>
                <span>sur le passé : placé en {retro.origine.slice(0, 4)}, l'outil aurait réparti les moyens réellement ajoutés jusqu'en {retro.fin.slice(5)} avec {nb(retro.surnombre_outil)} élèves en surnombre, contre {nb(retro.surnombre_reel)} en réalité.</span>
              </div>
            )}
          </div>
          <p className="petit">
            {pr.salles_rouvertes ? <>Là où plus de {nb(100 * meta.implantation.seuil_fermeture_rouvrir)} % des écoles ont fermé, l'outil ne construit pas : il envoie les enseignants avec {nb(pr.salles_rouvertes)} salles d'écoles fermées à rouvrir. </> : null}
            <button className="lien" onClick={() => aller('repartition')}>Refaire le calcul avec vos moyens →</button>
          </p>
          {(() => {
            // ce que Yennenga fait de plus qu'une règle simple : chiffres calculés par la chaîne
            const b = pr.atouts?.budget?.find((x) => x.pire_besoins - x.pire_optimisee >= 5)
            const mu = pr.atouts?.mutations
            return (
              <div className="encart-atouts">
                <b>Et face à la meilleure règle simple ?</b> Avec les moyens ci-dessus, partager selon les manques de chaque province retire autant d'élèves des classes surchargées. Yennenga fait la différence quand les moyens sont serrés ou les choix plus fins :
                <ul>
                  {b && <li>avec un budget de {nb(b.budget_md)} milliards, la province la plus chargée finit à <b>{nb(b.pire_optimisee)}</b> élèves par enseignant, contre {nb(b.pire_besoins)} avec la règle simple ;</li>}
                  {mu && mu.trop_besoins > mu.trop_optimisee && <li>avec {nb(mu.recrues)} recrues et {nb(mu.mutes)} mutations d'enseignants déjà en poste, <b>{nb(mu.trop_besoins - mu.trop_optimisee)}</b> élèves de plus sortent des classes surchargées, sans dépense supplémentaire : la règle simple ne sait pas muter ;</li>}
                  <li>il respecte les exigences du décideur et choisit entre recruter et construire quand on lui donne un budget.</li>
                </ul>
              </div>
            )
          })()}
        </section>
      )}

      <section className="contexte" aria-label="Contexte">
        <div className="chiffre"><b>{nb(n.enfants_6_11_horizon)}</b><span>enfants de 6 à 11 ans attendus en {h}, commune par commune</span></div>
        <div className="chiffre"><b>{pct(n.eloignes_basse / n.enfants_6_11_horizon, 0)} au moins</b><span>vivent à plus de {meta.implantation.rayon_km} km d'une école (au minimum ; jusqu'à {pct(n.eloignes_haute / n.enfants_6_11_horizon, 0)} en ne comptant que les écoles repérées sur les cartes)</span></div>
        <div className="chiffre"><b>{nb(n.sites)}</b><span>zones sans école proche : {nb(n.sites_construire)} où construire, {nb(n.sites - n.sites_construire)} où rouvrir d'abord les écoles fermées</span></div>
        <div className="chiffre"><b>{nb(n.pdi)}</b><span>personnes déplacées accueillies (fin 2022{n.communes_pdi_relevees ? `, ${nb(n.communes_pdi_relevees)} communes relevées` : ''})</span></div>
      </section>

      <section className="usages">
        <button className="usage" onClick={() => aller('carte')}>
          <b>Comprendre</b>
          <span>La carte, de la province à la commune : surcharge des classes, priorités, accès à l'école, sites proposés.</span>
        </button>
        <button className="usage" onClick={() => aller('repartition')}>
          <b>Décider</b>
          <span>Vos moyens, vos exigences : le meilleur plan par province, comparé aux règles simples, exportable et imprimable.</span>
        </button>
        <button className="usage" onClick={() => aller('donnees')}>
          <b>Mettre à jour</b>
          <span>Déposer l'annuaire de l'année : l'outil le contrôle et l'intègre. Le découpage territorial peut évoluer.</span>
        </button>
      </section>
    </div>
  )
}

// La démonstration vidéo : rien n'est téléchargé avant le clic (connexions lentes), sous-titres incrustés (lecture sans le son).
function Demonstration() {
  const [lancee, setLancee] = useState(false)
  const enLigne = typeof navigator === 'undefined' || navigator.onLine
  return (
    <figure className="demo">
      {lancee ? (
        <video src="/video/demonstration.mp4?v=4" poster="/video/demonstration.jpg" controls autoPlay playsInline preload="auto"
          aria-label="Démonstration de Yennenga, 2 minutes 38, sous-titrée" />
      ) : (
        <button className="demo-lancer" onClick={() => setLancee(true)} disabled={!enLigne}
          aria-label="Lancer la démonstration vidéo (2 min 38, sous-titrée, 10 Mo)">
          <img src="/video/demonstration.jpg" alt="" width={1280} height={720} loading="lazy" />
          <span className="demo-lecture" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="30" height="30"><path d="M8 5.5v13l11-6.5z" fill="currentColor" /></svg>
          </span>
          <span className="demo-duree" aria-hidden="true">2:38</span>
        </button>
      )}
      <figcaption>
        <b>L'outil en vidéo</b> · 2 min 38, sous-titrée{lancee ? '' : ' · 10 Mo'}
        {!enLigne && <span className="petit"> · disponible avec une connexion</span>}
      </figcaption>
    </figure>
  )
}
