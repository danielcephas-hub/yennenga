// Méthode : la chaîne de calcul en un schéma, les preuves de fiabilité, comment reproduire, les hypothèses,
// les limites et le vocabulaire. Tous les chiffres viennent des sorties de la chaîne (meta.json).
import type { Meta } from './api'
import { nb, pct } from './format'

const ETAPES_CHAINE = [
  { titre: 'Données', texte: 'Annuaires DGESS 2017-2025, recensement et projections INSD, WorldPop, OpenStreetMap, CONASUR' },
  { titre: 'Contrôles', texte: 'Totaux recoupés : provinces = régions = national ; rapprochement avec le fichier principal' },
  { titre: 'Diagnostic', texte: 'Élèves par enseignant et par salle, état du bâti, indice de besoin et sa robustesse' },
  { titre: 'Prévision', texte: 'Effectifs jusqu\'en 2030, méthode choisie sur son erreur mesurée sur le passé' },
  { titre: 'Répartition', texte: 'Programme d\'optimisation en nombres entiers, comparé aux règles simples' },
  { titre: 'Carte scolaire', texte: 'Enfants à 100 m, distance à l\'école, sites où construire ou rouvrir' },
]

export default function VueMethode({ meta }: { meta: Meta }) {
  const v = meta.validation
  const retro = meta.plan_reference?.retrospectif ?? []
  return (
    <div className="methode">
      <section className="carte-blanche">
        <h2>Comment l'outil calcule</h2>
        <ol className="chaine" aria-label="Chaîne de calcul">
          {ETAPES_CHAINE.map((e, i) => (
            <li key={e.titre}><span className="num">{i + 1}</span><b>{e.titre}</b><span>{e.texte}</span></li>
          ))}
        </ol>
        <p className="petit">Une seule commande refait tout, des fichiers d'origine à cette application. Aucun chiffre n'est saisi à la main.</p>
      </section>

      <section className="carte-blanche">
        <h2>Pourquoi on peut s'y fier</h2>
        <div className="preuves">
          {v?.rapprochement && <div><b>{v.rapprochement.identiques} / {v.rapprochement.total}</b><span>comparaisons identiques entre les annuaires et le fichier principal du challenge (élèves et écoles, 13 régions, 8 années)</span></div>}
          {v?.prevision && <div><b>{pct(v.prevision.erreur_1an, 1)} à {pct(v.prevision.erreur_max, 1)}</b><span>d'erreur de la prévision retenue, de 1 à {v.prevision.horizon_max} ans, dans les provinces stables ; {pct(v.prevision.reference_max, 1)} pour la référence « effectif inchangé »</span></div>}
          {retro.map((r) => <div key={r.origine}><b>−{pct(-r.ecart, 0)}</b><span>d'élèves en surnombre face à la répartition réelle de {r.origine.slice(0, 4)} à {r.fin.slice(5)}, avec la seule information disponible en {r.origine.slice(0, 4)}</span></div>)}
          {v?.scenarios && <div><b>{v.scenarios.optimaux} / {v.scenarios.total}</b><span>plans calculés à l'avance dont le solveur a vérifié qu'aucun meilleur plan n'existe</span></div>}
          {v?.tests != null && <div><b>{v.tests}</b><span>tests automatiques des calculs : lecture, référentiel, prévision, répartition, contrôle des imports</span></div>}
        </div>
      </section>

      <section className="carte-blanche">
        <h2>Hypothèses</h2>
        <ul>
          <li>Norme : {meta.normes.eleves_par_maitre} élèves par enseignant et par salle (DGESS).</li>
          <li>Coût d'une salle : {nb(meta.couts.salle / 1e6, 1)} millions de FCFA (médiane de marchés communaux de 2025){meta.couts.salle_complexe ? `, ou ${nb(meta.couts.salle_complexe / 1e6, 1)} millions par salle en complexe de 3 salles tout compris (standard ministériel)` : ''}. Coût d'un poste : {nb(meta.couts.enseignant / 1e6, 1)} millions de FCFA par an (enseignant débutant en zone rurale, salaire et indemnités).</li>
          <li>Un enseignant affecté doit disposer d'une salle : libre, construite ou rouverte.</li>
          <li>Au-delà de {nb(100 * meta.implantation.seuil_fermeture_rouvrir)} % d'écoles fermées dans la province, on rouvre d'abord : la répartition n'y construit pas de salle neuve. Les salles perdues depuis le maximum 2017-2025 y accueillent les enseignants envoyés avec la réouverture ; leur remise en état n'est pas chiffrée.</li>
          <li>Distance visée : {meta.implantation.rayon_km} km ; un site n'est proposé que s'il rapproche au moins {meta.implantation.seuil_enfants_site} enfants.</li>
          <li>Redéploiement (option) : un enseignant ne quitte qu'une province qui reste à la norme, et il lui faut une salle à l'arrivée.</li>
        </ul>
      </section>

      <section className="carte-blanche">
        <h2>Limites</h2>
        <ul>
          <li>Les annuaires décrivent les écoles ouvertes : en zone d'insécurité, les enfants déscolarisés n'y figurent pas.</li>
          <li>Enseignants et salles ne sont publiés que par province : la répartition des postes s'arrête à la province ; l'implantation descend à la commune.</li>
          <li>La liste des écoles géolocalisées (OpenStreetMap) est incomplète : la distance à l'école va d'une estimation favorable (écoles manquantes placées au mieux) aux seules écoles cartographiées. La liste officielle, chargée dans l'outil, la rendrait exacte.</li>
          <li>Les déplacés sont ceux du dernier relevé par commune publié (fin 2022) ; une commune absente du relevé est « non relevée », pas « sans déplacés ».</li>
        </ul>
      </section>

      <section className="carte-blanche">
        <h2>Mise en service</h2>
        <h3>Qui fait quoi</h3>
        <ul>
          <li><b>Un technicien de la DGESS</b> dépose l'annuaire de l'année (onglet Données), puis relance le calcul : environ 10 minutes. Formation : une journée.</li>
          <li><b>Les directions chargées des affectations et du budget</b> calculent le plan avec les moyens de l'année, le comparent aux règles simples et impriment la fiche de décision.</li>
          <li><b>Les directions régionales et provinciales</b> consultent la carte et les fiches, et signalent les écarts constatés sur le terrain.</li>
          <li><b>Le cabinet</b> arbitre à partir de la fiche de décision.</li>
        </ul>
        <h3>Chaque année</h3>
        <ol>
          <li>Publication de l'annuaire statistique.</li>
          <li>Dépôt dans l'outil : contrôle ligne par ligne, puis intégration.</li>
          <li>Recalcul des besoins et des prévisions.</li>
          <li>Plan avec les moyens de l'année : recrues, salles, budget, mutations.</li>
          <li>Arbitrage sur la fiche de décision, puis affectations, au moment fixé par le calendrier du ministère.</li>
        </ol>
        <h3>Démarrer en trois temps</h3>
        <ol>
          <li><b>Pilote</b> : la DGESS et deux régions, sur une campagne d'affectation.</li>
          <li><b>Extension</b> : toutes les régions, avec les retours du pilote.</li>
          <li><b>Appropriation</b> : hébergement sur un serveur du ministère, code et guide transmis.</li>
        </ol>
        <h3>Ce que ça coûte</h3>
        <p>Aucun abonnement ni service d'IA payant ; tous droits réservés, conditions d'utilisation à convenir avec l'auteur. Un serveur modeste suffit : celui de la démonstration a 2 cœurs et 8 Go de mémoire, partagés avec d'autres applications. L'outil reste utilisable sur une connexion lente (mode léger) et, après la première visite, sans réseau pour la consultation.</p>
      </section>

      <section className="carte-blanche">
        <h2>Reproduire</h2>
        <p>Le code complet, ses tests et le guide d'installation sont livrés avec la solution (tous droits réservés : voir le fichier LICENSE). Sur un poste avec Python 3.13 :</p>
        <pre>{`pip install -r requirements.txt
python -m dcb.pipeline        # des fichiers d'origine aux résultats, environ 10 minutes
python -m pytest -q tests     # tests des calculs`}</pre>
        <p className="petit">L'application se déploie sur un serveur par un conteneur Docker ; la mise à jour annuelle des données se fait depuis l'onglet Données, sans programmation.</p>
      </section>

      <section className="carte-blanche">
        <h2>Vocabulaire</h2>
        <dl className="glossaire">
          <dt>Norme</dt><dd>{meta.normes.eleves_par_maitre} élèves par enseignant : au-delà, les élèves sont comptés « en trop » dans des classes surchargées.</dd>
          <dt>Province la plus chargée</dt><dd>Celle qui a le plus d'élèves par enseignant après le plan.</dd>
          <dt>Écart entre provinces (indice de Gini)</dt><dd>0 si toutes les provinces ont le même nombre d'élèves par enseignant ; plus il est élevé, plus les dotations sont inégales.</dd>
          <dt>Meilleur plan possible</dt><dd>Le solveur a vérifié qu'aucune autre répartition des mêmes moyens ne fait mieux sur le critère retenu : soulager d'abord les classes les plus chargées.</dd>
          <dt>Rouvrir d'abord</dt><dd>Province ayant perdu plus de {nb(100 * meta.implantation.seuil_fermeture_rouvrir)} % de ses écoles : on y rouvre ou délocalise avant de construire.</dd>
          <dt>Complexe scolaire</dt><dd>Trois salles avec bureau, magasin, latrines et tables-bancs, standard de construction du ministère.</dd>
          <dt>Redéploiement</dt><dd>Mutation d'un enseignant en poste d'une province à la norme ou en dessous vers une province plus chargée.</dd>
          <dt>Lot</dt><dd>Un fichier de données importé, daté et signé ; le retirer rétablit la version précédente.</dd>
          <dt>DGESS, INSD, CONASUR</dt><dd>Direction générale des études et des statistiques sectorielles (éducation) ; Institut national de la statistique et de la démographie ; Conseil national de secours d'urgence et de réhabilitation (déplacés).</dd>
        </dl>
      </section>

      <section className="carte-blanche">
        <h2>Sans connexion</h2>
        <p>Si le réseau manque, <a href="/hors-ligne">le tableau de bord autonome</a> s'enregistre et s'ouvre sur n'importe quel poste, sans installation.</p>
      </section>
    </div>
  )
}
