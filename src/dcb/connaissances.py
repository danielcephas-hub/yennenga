"""Fiches de connaissance sur le fonctionnement de l'outil, pour l'assistant « Poser une question ».

Chaque fiche a des mots-clés (formes normalisées : majuscules sans accents) et un texte court. La fiche retenue est celle
dont les mots-clés couvrent le mieux la question ; rien n'est généré, tout est écrit ici et relu. Une fiche peut proposer
d'ouvrir un onglet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Fiche:
    titre: str
    mots: tuple[str, ...]    # expressions recherchées dans la question (les plus précises pèsent plus)
    texte: str
    vue: str | None = None   # onglet à proposer


FICHES = [
    # --- l'outil en général
    Fiche("Ce que fait Yennenga", ("A QUOI SERT", "QUE FAIT", "C EST QUOI YENNENGA", "YENNENGA", "PRESENTE", "OBJECTIF DE L OUTIL", "FONCTIONNE L OUTIL", "COMMENT MARCHE L OUTIL"),
          "Yennenga aide à décider où affecter les nouveaux enseignants et où construire ou rouvrir des salles de classe dans le primaire public. "
          "Il mesure les besoins des 45 provinces et des 351 communes, prévoit les élèves jusqu'à la rentrée 2030 et calcule la répartition qui "
          "soulage d'abord les classes les plus chargées, avec vos moyens et vos exigences. Quatre onglets : Carte (comprendre), Répartition "
          "(décider), Données (mettre à jour), Méthode (sources, hypothèses, limites)."),
    Fiche("Visite guidée", ("VISITE", "PRISE EN MAIN", "TUTORIEL", "PAR OU COMMENCER", "DEBUTER", "COMMENCER"),
          "La visite guidée présente l'outil en deux minutes : cliquez sur « Visite guidée » en haut à droite. Elle ouvre les écrans un à un "
          "et lance un calcul en direct."),
    Fiche("L'assistant", ("ASSISTANT", "TU ES QUI", "QUI ES TU", "COMMENT TU MARCHES", "COMMENT TU FONCTIONNES", "FONCTIONNES", "COMMENT FONCTIONNES TU", "QUE SAIS TU FAIRE", "QUE PEUX TU"),
          "Je réponds avec les chiffres et les calculs de l'outil, sans intelligence artificielle générative : je reconnais dans votre question "
          "un lieu (pays, région, province, commune), une mesure (élèves, enseignants, salles, élèves par enseignant, privé, filles, écoles fermées, "
          "déplacés, enfants loin d'une école…), une année, et ce que vous voulez (une valeur, une comparaison, une évolution, un classement, un plan). "
          "Je ne peux rien inventer : si je ne comprends pas, je le dis. Exemples : « élèves par enseignant au Bam en 2019 », « compare le Soum et le "
          "Loroum », « que se passe-t-il avec 2 000 enseignants ? »."),
    Fiche("Téléphone et connexion lente", ("TELEPHONE", "MOBILE", "CONNEXION", "LENT", "MODE LEGER", "SANS INTERNET", "HORS LIGNE", "RESEAU", "DEBIT"),
          "L'outil s'ouvre avec environ 90 ko. Sur connexion lente, le mode léger remplace les cartes par des listes (lien « Connexion lente ? "
          "Passer en mode léger » dans l'onglet Carte). Après une première visite, la consultation fonctionne même sans réseau ; seul le calcul "
          "d'un plan en demande. Un tableau de bord autonome, hors ligne, est aussi disponible (lien dans l'onglet Méthode)."),
    Fiche("Coût et licence", ("LICENCE", "OPEN SOURCE", "LIBRE", "GRATUIT", "COMBIEN COUTE L OUTIL", "PRIX DE L OUTIL", "ABONNEMENT", "SERVEUR"),
          "Yennenga est protégé par le droit d'auteur (tous droits réservés) : son utilisation par une administration se convient avec son auteur. "
          "Il ne demande ni abonnement ni service d'IA payant. Un serveur modeste suffit "
          "(celui de la démonstration : 2 cœurs, 8 Go de mémoire, partagés avec d'autres applications). Le code, les tests et le guide "
          "d'installation sont fournis.", "methode"),
    Fiche("Mise en service", ("MISE EN SERVICE", "DEPLOYER AU MINISTERE", "QUI UTILISE", "QUI VA UTILISER", "FORMATION", "PILOTE", "ADOPTER", "INSTALLER L OUTIL"),
          "Un technicien de la DGESS met à jour l'outil chaque année (une journée de formation) ; les directions chargées des affectations et du "
          "budget calculent le plan et impriment la fiche de décision ; les directions régionales et provinciales consultent la carte ; le "
          "cabinet arbitre. Démarrage proposé : un pilote avec deux régions, puis l'extension, puis l'hébergement au ministère.", "methode"),
    # --- carte
    Fiche("Utiliser la carte", ("CARTE", "INDICATEUR", "COULEUR", "LEGENDE", "CHANGER D INDICATEUR", "LIRE LA CARTE"),
          "Dans l'onglet Carte, choisissez le niveau (Provinces ou Communes), puis l'indicateur. Les couleurs changent de teinte à la norme. "
          "Cliquez sur une province ou une commune pour ouvrir sa fiche ; le champ « Aller à » trouve un lieu par son nom, même sans accents.", "carte"),
    Fiche("Remonter les années", ("ANNEE PRECEDENTE", "ANNEES PRECEDENTES", "ANCIENNES ANNEES", "ANNEES PASSEES", "HISTORIQUE", "CURSEUR", "VOIR 2017", "AUTRE ANNEE", "CHANGER L ANNEE"),
          "Dans l'onglet Carte, au niveau Provinces, le curseur « Année scolaire » remonte de 2024-2025 à 2017-2018 pour les indicateurs relevés "
          "chaque année (élèves par enseignant, par salle, part du privé, filles, salles précaires). Les calculs de l'outil (indice, plan) "
          "portent sur 2024-2025.", "carte"),
    Fiche("Télécharger les données d'une fiche", ("TELECHARGER", "EXTRAIRE", "EXTRACTION", "EXPORTER LES DONNEES", "EXCEL DE LA PROVINCE", "CSV", "LISTE DES ECOLES", "RECUPERER LES DONNEES"),
          "Ouvrez la fiche d'une province ou d'une commune dans l'onglet Carte, puis cliquez sur « Télécharger les données ». Le fichier s'ouvre "
          "dans Excel : la fiche avec l'année et la source de chaque chiffre, l'évolution 2017-2025, la prévision, et pour une province la liste "
          "de ses communes, des sites proposés et des écoles repérées sur OpenStreetMap (liste partielle).", "carte"),
    Fiche("Sites proposés", ("SITE", "DISQUE", "CERCLE", "OU CONSTRUIRE UNE ECOLE", "NOUVELLE ECOLE", "IMPLANTATION"),
          "Au niveau Communes de la carte, les sites proposés sont des mailles de 1 km où une école rapprocherait le plus d'enfants restés à plus "
          "de 3 km d'une école. Disque plein : construire ; cercle : rouvrir d'abord les écoles fermées (province ayant perdu plus de 20 % de ses "
          "écoles). À vérifier sur le terrain.", "carte"),
    # --- répartition
    Fiche("Calculer un plan", ("CALCULER UN PLAN", "COMMENT CALCULER", "FAIRE UN PLAN", "REPARTITION", "UTILISER LA REPARTITION", "COMMENT REPARTIR"),
          "Dans l'onglet Répartition : indiquez les nouveaux enseignants et les salles à construire (ou seulement un budget), l'hypothèse sur les "
          "élèves attendus, la norme, les mutations et vos exigences, puis « Calculer le plan ». Le meilleur plan s'affiche en quelques secondes, "
          "comparé aux règles simples. Vous pouvez aussi me le demander : « que se passe-t-il avec 2 000 enseignants et 800 salles ? ».", "repartition"),
    Fiche("Budget seul", ("BUDGET SEUL", "AVEC UN BUDGET", "MODE BUDGET", "ENVELOPPE"),
          "En mode « Budget seul », vous donnez une enveloppe en milliards de FCFA : l'outil choisit lui-même combien de postes et de salles financer. "
          "Une salle se paie une fois ; un poste chaque année, compté sur 5 ans. C'est là que le plan Yennenga se distingue le plus des règles simples.", "repartition"),
    Fiche("Exigences du décideur", ("EXIGENCE", "CONTRAINTE", "AU MOINS", "AU PLUS", "IMPOSER", "PLANCHER", "PLAFOND"),
          "Dans l'onglet Répartition, « Vos exigences » imposent un minimum ou un maximum d'enseignants ou de salles à une province ou une région "
          "(par exemple au moins 300 enseignants pour le Sahel). Une exigence impossible à tenir est expliquée, jamais contournée.", "repartition"),
    Fiche("Mutations", ("MUTATION", "REDEPLOI", "MUTER", "DEPLACER DES ENSEIGNANTS"),
          "Une mutation déplace un enseignant déjà en poste d'une province qui en a plus que la norme vers une province surchargée. Elle ne crée "
          "pas de poste, mais il faut une salle à l'arrivée. Le réglage « Mutations d'enseignants en poste (au plus) » fixe un plafond ; le plan "
          "propose ensuite les mouvements les plus courts.", "repartition"),
    Fiche("Comparer deux plans", ("COMPARER DEUX PLANS", "GARDER CE PLAN", "DEUX PLANS", "COTE A COTE"),
          "Dans l'onglet Répartition, juste sous les chiffres clés du plan, cliquez sur « Garder ce plan pour comparer », changez les réglages, "
          "puis recalculez : les deux plans s'affichent aussitôt côte à côte, sous les chiffres clés (enseignants, salles, coût, élèves en trop, "
          "province la plus chargée, écart entre provinces). « Oublier ce plan » ou « Ne plus comparer » arrête la comparaison.", "repartition"),
    Fiche("Exporter et imprimer un plan", ("EXPORTER LE PLAN", "IMPRIMER", "FICHE DE DECISION", "CLASSEUR", "EXCEL DU PLAN", "VISA"),
          "Un plan calculé s'exporte en classeur Excel (fiche, plan par province avec le « pourquoi », comparaison, mouvements, hypothèses) et "
          "s'imprime en fiche de décision avec un espace pour le visa. Les boutons Excel, CSV et « Imprimer la fiche » sont juste sous les chiffres "
          "clés du plan, dans l'onglet Répartition.", "repartition"),
    Fiche("Lire le tableau du plan", ("COLONNE POURQUOI", "TABLEAU DU PLAN", "PLAN PAR PROVINCE", "LIRE LE PLAN", "COMPRENDRE LE PLAN"),
          "Le tableau « Plan par province » donne, pour chaque province, les élèves attendus, les enseignants et salles actuels, ce que le plan "
          "ajoute, les salles à rouvrir, les mutations et le nombre d'élèves par enseignant après le plan. La colonne « Pourquoi » explique en une "
          "phrase ce que reçoit la province (servie en priorité, limitée par ses salles, déjà à la norme…).", "repartition"),
    # --- données
    Fiche("Mettre à jour les données", ("METTRE A JOUR", "MISE A JOUR", "NOUVELLE ANNEE", "NOUVEL ANNUAIRE", "AJOUTER UNE ANNEE", "IMPORTER", "DEPOSER L ANNUAIRE", "CHARGER LES DONNEES"),
          "Dans l'onglet Données : 1) télécharger le fichier type de l'année (Excel), 2) le remplir puis le faire contrôler (le contrôle n'enregistre "
          "rien et signale chaque anomalie avec sa ligne), 3) l'importer avec le jeton d'administration. Chaque import est un lot daté et signé. "
          "Les résultats affichés changent après le recalcul par la chaîne sur le poste de calcul (environ 10 minutes).", "donnees"),
    Fiche("Retirer un lot", ("RETIRER", "ANNULER UN IMPORT", "ERREUR D IMPORT", "LOT", "REVENIR EN ARRIERE"),
          "Chaque dépôt est un lot daté avec son auteur ; pour une année, le lot le plus récent fait foi. Retirer un lot (administrateur, onglet "
          "Données) rétablit la version précédente : rien n'est jamais effacé.", "donnees"),
    Fiche("Nouveau découpage", ("DECOUPAGE", "NOUVELLES PROVINCES", "NOUVELLES REGIONS", "17 REGIONS", "47 PROVINCES", "REFORME"),
          "Les calculs utilisent les 45 provinces des annuaires ; la carte des communes utilise le découpage de 2025 (17 régions, 47 provinces). "
          "Un nouveau découpage se déclare dans l'onglet Données, sans programmation : les communes, unité stable, sont regroupées autrement.", "donnees"),
    # --- méthode
    Fiche("Prévision des élèves", ("PREVISION", "COMMENT PREVOIT", "PREVOY", "PREVOIR", "PROJECTION", "2030", "FUTUR", "SCENARIO"),
          "Les élèves de 2030 sont prévus par province : la tendance des dernières années, amortie, pour les provinces stables ; l'effectif actuel "
          "pour les provinces en choc (baisse de plus de 10 % en une année). La méthode a été testée sur le passé, contre une référence simple. "
          "Le scénario « si les écoles fermées rouvrent » rattrape la moitié de l'écart avec le plus haut niveau.", "methode"),
    Fiche("Le calcul du plan", ("OPTIMISATION", "ALGORITHME", "COMMENT EST CALCULE LE PLAN", "CALCULE LE PLAN", "COMMENT L OUTIL REPARTIT", "MODELE", "SOLVEUR", "PLNE"),
          "Le plan est calculé par un programme d'optimisation : il sert d'abord les provinces les plus chargées, avec une règle simple (un "
          "enseignant a besoin d'une salle), vos moyens et vos exigences. Le résultat est le meilleur possible, vérifié par le calcul. Il est "
          "toujours comparé à deux règles simples avec les mêmes moyens.", "methode"),
    Fiche("Fiabilité", ("FIABLE", "CONFIANCE", "VERIFIE", "TESTE", "PREUVE", "SE FIER"),
          "Les chiffres viennent des annuaires de la DGESS (totaux vérifiés sur 8 années, 222 comparaisons identiques sur 224 avec le fichier "
          "principal). La prévision est testée sur le passé. Placé en 2019, l'outil aurait laissé 14 % d'élèves en surnombre de moins que la "
          "répartition réelle. Les tests automatiques recalculent les résultats. L'outil éclaire la décision, il ne la remplace pas.", "methode"),
    Fiche("Sources", ("SOURCE", "D OU VIENNENT", "QUELLES DONNEES", "DONNEES UTILISEES"),
          "Annuaires statistiques du primaire de la DGESS (2017-2018 à 2024-2025) ; recensement 2019 et projections de l'INSD ; déplacés du "
          "CONASUR (fin 2022) ; population WorldPop ; écoles repérées sur OpenStreetMap ; limites administratives OCHA ; coûts : marchés publics "
          "communaux 2025 et grille salariale. Le détail est dans l'onglet Méthode.", "methode"),
    Fiche("Limites", ("LIMITE", "FAIBLESSE", "CE QUE L OUTIL NE FAIT PAS", "INCONVENIENT"),
          "Enseignants et salles ne sont connus que par province ; le besoin porte sur les élèves inscrits, pas sur les enfants non scolarisés ; "
          "coûts et seuils sont des hypothèses ; la remise en état des écoles fermées n'est pas chiffrée ; le post-primaire n'a qu'un diagnostic par "
          "région, décrit dans la documentation ; le secondaire n'est pas traité.", "methode"),
]

_VIDES = {"LE", "LA", "LES", "DE", "DES", "DU", "UN", "UNE", "ET", "A", "AU", "AUX", "EN", "D", "L", "QUE", "QUI", "QUOI", "EST", "CE",
          "JE", "TU", "IL", "ON", "NOUS", "VOUS", "MON", "MA", "MES", "POUR", "PAR", "SUR", "DANS", "AVEC", "COMMENT", "POURQUOI", "OU"}


def chercher(q: str) -> Fiche | None:
    """Fiche dont les mots-clés couvrent le mieux la question normalisée ; None si aucune ne correspond assez."""
    meilleur, score_max = None, 0.0
    for f in FICHES:
        score = 0.0
        for m in f.mots:
            if re.search(r"\b" + m + r"\b", q):
                score += 1 + 0.5 * m.count(" ")  # une expression de plusieurs mots est plus probante qu'un mot seul
        if score > score_max:
            meilleur, score_max = f, score
    return meilleur if score_max >= 1 else None
