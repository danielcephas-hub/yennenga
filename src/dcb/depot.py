"""Prépare les fichiers à déposer et les contrôle.

Nom des fichiers : EQUIPE_ETAPE_DEFI_ROLE_description_vN (sans espace ni accent).
Le code d'équipe, le défi et la version sont dans config.yaml (rubrique `depot`).

Contrôle avant dépôt : chaque fichier produit (y compris l'intérieur des archives et des classeurs) est
parcouru à la recherche des termes listés dans le fichier local `controle_depot.local.txt` (un terme par
ligne ; ce fichier n'est jamais déposé). Le moindre terme trouvé fait échouer la commande.

Usage : PYTHONPATH=src python -m dcb.depot   (après dcb.pipeline)
Produit le dossier depot/
"""
from __future__ import annotations

import hashlib
import io
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd

from dcb import geo
from dcb.audit_annuaires import annuaires_primaire
from dcb.indicateurs import config
from dcb.lecture import CSV, DATAPACK, RACINE

DEPOT = RACINE / "depot"
INTERIM = RACINE / "data" / "interim"
TRAITE = RACINE / "data" / "processed"
DOCS = RACINE / "docs" / "depot"
TERMES = RACINE / "controle_depot.local.txt"
DATE_COLLECTE = "2026-11-13"

DICTIONNAIRE = {
    "carte-scolaire-commune": ("Une ligne par commune (351, découpage de 2025) : demande scolaire, accès, déplacés, sites proposés.", {
        "pcode_commune": "Code P de la commune (COD-AB, identifiant stable du référentiel territorial)",
        "commune, province, region": "Noms dans le découpage de 2025 (17 régions, 47 provinces)",
        "province_ancienne, region_ancienne": "Province et région dans le découpage des annuaires (13 régions, 45 provinces)",
        "lat, lon": "Point intérieur de la commune (degrés)",
        "population_2019, enfants_6_11_2019": "Recensement 2019, fichier des localités (INSD)",
        "enfants_6_11_2030": "Enfants de 6-11 ans à la rentrée 2030 : part de la commune dans sa province en 2019 x projection INSD",
        "sites_scolaires_osm": "Sites scolaires repérés dans OpenStreetMap (bâtiments à moins de 150 m regroupés) ; couverture partielle",
        "pdi_total, pdi_enfants_plus_5": "Personnes déplacées internes accueillies (CONASUR, 31 décembre 2022)",
        "population_estimee_insd": "Commune non ou partiellement recensée en 2019, effectifs estimés par l'INSD",
        "eloignes_borne_haute, eloignes_borne_basse": "Enfants de 6-11 ans à plus de 3 km d'une école : écoles OSM seules / OSM + écoles de l'annuaire placées au mieux",
        "part_ecoles_fermees_province": "1 - écoles ouvertes en 2024-2025 / maximum 2017-2025 de la province (annuaires)",
        "construction_programmee": "Faux si la province est exclue de la construction (même règle que la répartition)",
    }),
    "sites-proposes": ("Une ligne par site où ouvrir une école, dans l'ordre de choix (couverture maximale gloutonne).", {
        "rang": "Ordre de choix (1 = site qui rapproche le plus d'enfants)",
        "lon, lat": "Centre du site (maille de 1 km, degrés)",
        "enfants_rapproches": "Enfants de 6-11 ans en 2030 ramenés à moins de 3 km d'une école par ce site",
        "recommandation": "construire, ou rouvrir ou délocaliser d'abord si la province a perdu plus de 20 % de ses écoles ouvertes",
    }),
    "table-province-annee": ("Une ligne par année scolaire, province et statut (public, prive, total). Primaire.", {
        "annee_scolaire": "Année scolaire, forme 2024-2025",
        "region": "Région (découpage des annuaires, 13 régions)",
        "province": "Province (découpage des annuaires, 45 provinces), en majuscules sans accent",
        "statut": "public, prive ou total",
        "ecoles": "Nombre d'écoles",
        "salles": "Nombre de salles de classe",
        "groupes_pedagogiques": "Nombre de groupes pédagogiques",
        "maitres": "Nombre de maîtres chargés de cours",
        "eleves": "Nombre d'élèves",
        "aucune_ecole_ouverte": "Vrai si la province est absente de l'annuaire cette année-là (comptes mis à zéro)",
        "murs_dur": "Salles dont les murs sont en dur",
        "murs_semi_dur": "Salles dont les murs sont en semi-dur",
        "murs_paille_banco": "Salles dont les murs sont en paille, en banco ou autre",
        "murs_indetermine": "Salles dont la nature des murs est indéterminée",
        "murs_bon_etat": "Salles dont les murs sont en bon état ou en état acceptable",
        "murs_mauvais_etat": "Salles dont les murs sont en mauvais état",
        "murs_etat_indetermine": "Salles dont l'état des murs est indéterminé",
        "salles_tableau_murs": "Nombre de salles selon le tableau des murs (dénominateur des parts)",
        "eleves_par_maitre": "eleves / maitres",
        "eleves_par_salle": "eleves / salles",
        "eleves_par_groupe": "eleves / groupes_pedagogiques",
        "part_salles_precaires": "murs_paille_banco / salles_tableau_murs (entre 0 et 1)",
        "part_salles_mauvais_etat": "murs_mauvais_etat / salles_tableau_murs (entre 0 et 1)",
        "maitres_manquants": "Maîtres à ajouter pour atteindre la norme d'élèves par maître (0 si la norme est respectée)",
        "salles_manquantes": "Salles à ajouter pour atteindre la norme d'élèves par salle",
        "eleves_au_dela_norme_maitre": "Élèves en surnombre par rapport à la norme : eleves - norme × maitres, au minimum 0",
        "eleves_au_dela_norme_salle": "Élèves en surnombre par rapport à la norme : eleves - norme × salles, au minimum 0",
        "eleves_serie": "Élèves, public et privé, selon l'historique des annuaires (publication la plus récente)",
        "eleves_pic_historique": "Plus haut effectif de la province depuis 2004-2005 (public et privé)",
        "part_du_pic": "eleves_serie / eleves_pic_historique (entre 0 et 1)",
    }),
    "indicateurs-indice-besoin": ("Une ligne par province, année de référence, secteur cible.", {
        "score_surcharge": "Moyenne des rangs centiles des élèves par maître et par salle (0 = mieux dotée, 1 = plus chargée)",
        "score_bati": "Moyenne des rangs centiles des parts de salles en paille ou banco et en mauvais état",
        "indice_besoin": "Moyenne pondérée des deux dimensions (0 = mieux dotée, 1 = plus en difficulté)",
        "rang": "Rang de priorité (1 = province à servir d'abord)",
        "rang_p05": "Rang atteint ou dépassé dans 95 % des tirages de pondérations",
        "rang_median": "Rang médian sur les tirages",
        "rang_p95": "Rang non dépassé dans 95 % des tirages",
        "part_meme_tiers": "Part des tirages où la province reste dans le même tiers de priorité (rangs 1-15, 16-30, 31-45)",
        "rang_instable": "Vrai si la province change de tiers de priorité dans plus de 20 % des tirages",
    }),
    "previsions-effectifs-2030": ("Une ligne par scénario, année scolaire future et province. Public et privé.", {
        "scenario": "tendance (scénario central) ou reouverture (rattrapage d'une part de l'écart au maximum historique)",
        "groupe": "stable ou choc (effectif ayant chuté de plus de 10 % d'une année sur l'autre depuis 2015)",
        "horizon": "Nombre d'années après l'année de référence",
        "eleves_prevus": "Effectif prévu",
        "borne_basse": "Borne basse : 10e centile des rapports réalisé / prévu observés dans le test sur le passé",
        "borne_haute": "Borne haute : 90e centile",
        "methode": "Méthode retenue pour le groupe de la province",
    }),
    "fiabilite-prevision": ("Erreur des méthodes de prévision dans le test sur le passé.", {
        "methode": "naive (effectif inchangé), tendance_lineaire, croissance_amortie, demographique",
        "horizon": "Nombre d'années entre la date de prévision et l'année prévue",
        "wape": "Somme des écarts absolus / somme des effectifs réalisés (entre 0 et 1)",
        "cas": "Nombre de prévisions comparées au réalisé",
        "perimetre": "tous_les_cas, ou cas_communs (cas que toutes les méthodes ont pu prévoir)",
        "groupe": "ensemble, stable ou choc",
        "retenue": "Vrai pour la méthode retenue dans le groupe",
    }),
    "essai-apprentissage-automatique": ("Une ligne par méthode, horizon et période d'origine. Mêmes cas pour toutes les méthodes.", {
        "methode": "naive, tendance_lineaire, croissance_amortie (dcb.prevision) ; ml_ridge, ml_gradient_boosting (modèles globaux)",
        "horizon": "Nombre d'années entre la date de prévision et l'année prévue",
        "wape": "Somme des écarts absolus / somme des effectifs réalisés (entre 0 et 1)",
        "cas": "Nombre de prévisions comparées au réalisé",
        "periode": "toutes_origines, ou seulement les prévisions faites depuis 2018",
        "bat_la_reference": "Vrai si l'erreur moyenne sur les horizons est inférieure à celle de la référence naïve",
    }),
    "repartition-scenarios": ("Une ligne par scénario (demande, enseignants, salles) et par méthode de répartition.", {
        "type_scenario": "grille (enseignants et salles fixés), budget_seul (seul le budget contraint) ou sensibilite (une hypothèse modifiée)",
        "hypothese, valeur": "Pour les lignes de sensibilité : hypothèse modifiée et sa valeur",
        "budget_fcfa": "Budget des scénarios budget_seul ; un poste y est compté sur 5 ans",
        "demande": "Hypothèse sur les effectifs à l'horizon : tendance ou reouverture",
        "enseignants_disponibles": "Enseignants à répartir",
        "salles_disponibles": "Salles à construire",
        "methode": "sans_moyens_nouveaux, proportionnelle (au prorata des élèves attendus), besoins (au prorata des enseignants et salles manquants, mêmes règles que l'optimisation) ou optimisee",
        "enseignants_attribues": "Enseignants effectivement attribués (un enseignant doit disposer d'une salle)",
        "salles_attribuees": "Salles effectivement attribuées",
        "eleves_au_dela_norme_maitre": "Élèves en surnombre à l'horizon, par rapport à la norme d'élèves par maître",
        "eleves_au_dela_norme_salle": "Élèves en surnombre à l'horizon, par rapport à la norme d'élèves par salle",
        "provinces_au_dessus_norme_maitre": "Nombre de provinces au-dessus de la norme d'élèves par maître",
        "provinces_au_dessus_norme_salle": "Nombre de provinces au-dessus de la norme d'élèves par salle",
        "pire_ratio_eleves_maitre": "Ratio élèves par maître de la province la plus chargée",
        "pire_ratio_eleves_salle": "Ratio élèves par salle de la province la plus chargée",
        "ecart_type_ratio_maitre": "Dispersion des ratios élèves par maître entre provinces",
        "gini_ratio_maitre": "Indice de Gini des élèves par maître entre provinces, pondéré par les élèves (0 = égalité)",
        "rapport_p90_p10_ratio_maitre": "Élèves par maître : 9e décile / 1er décile des provinces",
        "part_eleves_province_conforme": "Part des élèves dans une province à la norme d'élèves par maître (entre 0 et 1)",
        "duree_s": "Temps de calcul de la répartition optimisée, en secondes",
        "statut_solveur": "Optimal si l'optimalité est prouvée par le solveur ; « Non prouvé optimal » si la limite de temps est atteinte",
    }),
    "diagnostic-post-primaire": ("Une ligne par année scolaire (2022-2023, 2023-2024) et par région, plus le total national. "
                                 "Source : tableaux de bord du post-primaire et du secondaire (DGESS).", {
        "niveau": "region ou national",
        "eleves_pp, garcons_pp, filles_pp": "Élèves du post-primaire, public et privé",
        "eleves_sec": "Élèves du secondaire, public et privé",
        "etablissements, salles": "Établissements et salles de classe, post-primaire et secondaire, public et privé",
        "etablissements_2019, salles_2019": "Mêmes grandeurs en 2019-2020, reconstituées : valeur 2023-2024 moins la variation publiée",
        "evolution_etablissements_2019": "Variation relative depuis 2019-2020 (−0,44 = perte de 44 %)",
        "eleves_par_classe_6e … eleves_par_classe_pp": "Élèves par classe, public, enseignement général, par niveau et pour le cycle",
        "eleves_eg_public, places_assises": "Élèves et places assises estimées, établissements publics d'enseignement général",
        "deficit_places, excedent_places": "Élèves sans place assise ; places inoccupées dans d'autres établissements",
        "part_eleves_sans_place": "deficit_places / eleves_eg_public",
        "enseignants": "Enseignants du post-primaire et du secondaire, cours du jour, hors vacataires",
        "eleves_par_enseignant_hors_vacataires": "Non comparable entre régions (vacataires exclus, nombreux dans le privé) : donné pour information",
        "pct_latrines, pct_eau_potable, pct_electricite": "Part des établissements équipés (%)",
        "signal_6e_au_dessus_norme": "Vrai si la 6ᵉ dépasse la norme nationale de 70 élèves par classe (dernière année)",
        "signal_places_manquantes": "Vrai si plus de 10 % des élèves du public général n'ont pas de place assise (seuil de travail)",
        "signal_perte_etablissements": "Vrai si la région a perdu plus de 20 % de ses établissements depuis 2019-2020 (seuil de travail)",
        "page_…": "Page du document source d'où vient chaque tableau",
    }),
    "referentiel-territorial (correspondance_decoupage_2025.csv)": ("Une ligne par province du découpage de 2025 (47 provinces, 17 régions).", {
        "province": "Province des annuaires à laquelle elle se rattache",
        "region": "Région des annuaires",
        "pcode_province_ancienne": "Code géographique de la province dans l'ancien découpage",
        "province_2025": "Nom de la province dans le découpage de 2025",
        "pcode_province_2025": "Code géographique de la province de 2025",
        "region_2025": "Nom de la région dans le découpage de 2025",
        "pcode_region_2025": "Code géographique de la région de 2025",
    }),
}


def _sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _csv(df: pd.DataFrame, chemin: Path) -> None:
    df.to_csv(chemin, index=False, sep=";", encoding="utf-8-sig", decimal=",")


def _lire(chemin: Path) -> pd.DataFrame:
    return pd.read_csv(chemin, sep=";", encoding="utf-8")


def inventaire_sources() -> pd.DataFrame:
    """Fichiers réellement lus par la chaîne : origine, usage, taille, empreinte."""
    sig = "04_Cartographie_SIG/COD-AB_limites_administratives"
    demo = CSV / "02_Demographie_INSD"
    lignes = []

    def ajouter(chemin: Path, origine: str, producteur: str, usage: str, base: Path, prefixe: str):
        lignes.append({"origine": origine, "fichier": prefixe + chemin.relative_to(base).as_posix(), "producteur": producteur,
                       "usage": usage, "taille_octets": chemin.stat().st_size, "sha256": _sha256(chemin),
                       "date_collecte": DATE_COLLECTE})

    for f in sorted((RACINE / "data" / "raw").glob("*.xlsx")):
        ajouter(f, "Espace challenge", "DGESS / MENA", "Contrôle des totaux régionaux et nationaux", f.parent, "")
    for annee, f in annuaires_primaire():
        ajouter(f, "Data Pack", "DGESS", f"Annuaire du primaire {annee} : dotation par province, murs, historique", DATAPACK, "")
    ajouter(demo / "RGPH2019_NADA" / "NADA276_RGPH2019_Projections_2020-2035.csv", "Data Pack", "INSD",
            "Population de 6 à 11 ans par province, 2020-2035", DATAPACK, "")
    ajouter(demo / "INSD_RGPH2019_Vol4_Projections_demographiques_2020-2035.csv", "Data Pack", "INSD",
            "Même document, seconde copie, pour recoupement", DATAPACK, "")
    ajouter(CSV / sig / "bfa_admin_boundaries__bfa_admin2.csv", "Data Pack", "OCHA (COD-AB)",
            "Correspondance entre provinces des annuaires et découpage de 2025", DATAPACK, "")
    ajouter(DATAPACK / sig / "bfa_admin_boundaries.geojson.zip", "Data Pack", "OCHA (COD-AB)", "Contours des provinces", DATAPACK, "")
    tdb = CSV / "01_Education_MENAPLN_DGESS" / "CNS_DGESS" / "Tableaux_de_bord"
    ajouter(tdb / "CNS565_Tableau_de_bord_statistique_de_lenseignement_Primaire_2023_2024.csv", "Data Pack", "DGESS",
            "Norme nationale de 50 élèves par enseignant (page 37)", DATAPACK, "")
    from dcb.post_primaire import FICHIERS as FICHIERS_PP

    for annee, f in FICHIERS_PP.items():
        ajouter(f, "Data Pack", "DGESS", f"Post-primaire et secondaire {annee} : diagnostic par région", DATAPACK, "")
    # carte scolaire à la commune, accès à l'école, coûts unitaires
    from dcb import carte_scolaire, implantation, population_communes
    for f, producteur, usage in ((population_communes.SOURCE, "INSD", "Population et enfants de 6 à 11 ans par commune (RGPH 2019)"),
                                 (carte_scolaire.PDI, "CONASUR", "Personnes déplacées internes par commune d'accueil, fin 2022"),
                                 (carte_scolaire.OSM, "HOT / OpenStreetMap", "Écoles géolocalisées (accès à l'école, sites proposés)")):
        if f.exists():
            ajouter(f, "Data Pack", producteur, usage, DATAPACK, "")
    externes = RACINE / "data" / "external"
    for f in sorted(implantation.WORLDPOP.glob("*.tif")):
        ajouter(f, "data.worldpop.org (CC BY 4.0)", "WorldPop", "Enfants de 5 à 14 ans en 2030 sur une grille de 100 m, recalés sur l'INSD", externes, "")
    for f in sorted((externes / "marches_publics").glob("*.pdf")):
        ajouter(f, "dgcmef.gov.bf", "DGCMEF", "Coût d'une salle de classe : 5 marchés communaux de 2025", externes, "")
    for f in sorted((externes / "documents_couts").glob("*.pdf")):
        ajouter(f, "Documents publics (voir SOURCES.md)", "MENAPLN, CN-EPT, Banque mondiale", "Coût annuel d'un poste d'enseignant et repères de coûts", externes, "")
    return pd.DataFrame(lignes)


def dictionnaire_md(e: str, v: int) -> str:
    lignes = ["# Dictionnaire des variables et schéma — Défi 3", "",
              "Tous les fichiers CSV déposés : séparateur point-virgule, encodage UTF-8, virgule décimale.",
              "Clés de jointure : `annee_scolaire`, `province` (45 provinces des annuaires), `statut`.", "",
              "## Schéma", "",
              "```",
              "annuaires (8 années) ──┐",
              "fichier principal ─────┼─> tables propres ─> table province × année ─┬─> indicateurs et indice de besoin",
              "projections INSD ──────┘                                             ├─> prévisions des effectifs",
              "limites COD-AB ──────────> correspondance des découpages             └─> répartition (scénarios) ─> tableau de bord",
              "```", ""]
    for nom, (description, colonnes) in DICTIONNAIRE.items():
        lignes += [f"## {nom}", "", description, "", "| Variable | Définition |", "|---|---|"]
        lignes += [f"| `{c}` | {d} |" for c, d in colonnes.items()]
        lignes.append("")
    return "\n".join(lignes)


def plan_xlsx(chemin: Path, cfg: dict) -> None:
    """Plan de répartition du scénario de référence, lisible par un décideur."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    a = _lire(TRAITE / "allocation.csv")
    b = _lire(TRAITE / "allocation_bilan.csv")
    corr = geo.correspondance().groupby("province").agg(provinces_2025=("province_2025", " + ".join),
                                                        region_2025=("region_2025", "first"))
    o = a[a["methode"] == "optimisee"].set_index("province")
    p = a[a["methode"] == "proportionnelle"].set_index("province")
    opt = cfg["optimisation"]
    plan = pd.DataFrame({
        "Région": o["region"].str.title(), "Province": o.index.str.title(),
        "Province(s) 2025": corr["provinces_2025"].reindex(o.index), "Région 2025": corr["region_2025"].reindex(o.index),
        f"Élèves attendus {cfg['annee_horizon']}": o["eleves_horizon"].astype(int),
        "Maîtres actuels": o["maitres"].astype(int), "Salles actuelles": o["salles"].astype(int),
        "Enseignants attribués": o["enseignants_attribues"], "Salles attribuées": o["salles_attribuees"],
        "Élèves par maître après": o["ratio_maitre_apres"].round(1), "Élèves par salle après": o["ratio_salle_apres"].round(1),
        "Coût des salles (millions FCFA)": (o["salles_attribuees"] * opt["cout_salle_fcfa"] / 1e6).round(0),
        "Pour comparaison — proportionnelle : enseignants": p["enseignants_attribues"],
        "Pour comparaison — proportionnelle : élèves par maître": p["ratio_maitre_apres"].round(1),
    }).sort_values(["Enseignants attribués", "Salles attribuées"], ascending=False)
    libelles = {"sans_moyens_nouveaux": "Sans moyens nouveaux", "proportionnelle": "Répartition proportionnelle",
                "optimisee": "Répartition optimisée"}
    bilan = b.assign(methode=b["methode"].map(libelles)).set_index("methode").T.round(1).reset_index().rename(columns={"index": "Indicateur"})
    hyp = pd.DataFrame([
        ("Année de référence", cfg["annee_reference"]), ("Horizon", cfg["annee_horizon"]),
        ("Secteur", cfg["statut_cible"]), ("Enseignants à répartir", opt["enseignants_a_repartir"]),
        ("Salles à construire", opt["salles_a_construire"]),
        ("Norme élèves par maître", cfg["normes"]["eleves_par_maitre"]), ("Norme élèves par salle", cfg["normes"]["eleves_par_salle"]),
        ("Coût d'une salle (FCFA, hypothèse)", opt["cout_salle_fcfa"]),
        ("Hypothèse sur les effectifs", opt["scenario_demande"]),
        ("Un enseignant nouveau doit disposer d'une salle", "oui" if opt["un_maitre_par_salle"] else "non"),
        ("Pas de construction si l'effectif est sous cette part du maximum historique", opt["seuil_acces_construction"]),
    ], columns=["Hypothèse", "Valeur"])
    with pd.ExcelWriter(chemin, engine="openpyxl") as w:
        plan.to_excel(w, sheet_name="Plan de répartition", index=False)
        bilan.to_excel(w, sheet_name="Bilan comparé", index=False)
        hyp.to_excel(w, sheet_name="Hypothèses", index=False)
        for ws in w.book.worksheets:
            for cell in ws[1]:
                cell.font = Font(bold=True)
            ws.freeze_panes = "A2"
            for i, col in enumerate(ws.columns, 1):
                largeur = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[get_column_letter(i)].width = min(46, max(10, largeur + 2))
        w.book.properties.creator = ""
        w.book.properties.lastModifiedBy = ""
        w.book.properties.title = "Plan de répartition"


def _zip(chemin: Path, fichiers: dict[str, Path]) -> None:
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, source in sorted(fichiers.items()):
            z.write(source, nom)


def construire() -> list[Path]:
    cfg = config()
    d = cfg["depot"]
    e, defi, v = d["code_equipe"], d["defi"], d["version"]

    def nom(etape: str, role: str, description: str, ext: str) -> Path:
        # rangé par étape (dossiers 01_collecte … 05_interpretation, consigne du mail de clôture)
        dossier = DEPOT / etape.replace("-", "_")
        dossier.mkdir(exist_ok=True)
        return dossier / f"{e}_{etape}_{defi}_{role}_{description}_v{v}.{ext}"

    if DEPOT.exists():
        shutil.rmtree(DEPOT)
    DEPOT.mkdir()
    produits: list[tuple[Path, str]] = []

    def noter(chemin: Path, description: str) -> Path:
        produits.append((chemin, description))
        return chemin

    # 01 — collecte
    _csv(inventaire_sources(), noter(nom("01-collecte", "engineer", "inventaire-sources", "csv"),
                                     "Fichiers sources utilisés : origine, usage, taille, empreinte SHA-256"))
    # 02 — nettoyage
    propres = {f"annuaires/{f.name}": f for f in sorted((INTERIM / "annuaires").glob("*.csv"))}
    propres |= {f"fichier_principal/{f.name}": f for f in sorted((INTERIM / "principal").glob("*.csv"))}
    propres |= {f"demographie/{f.name}": f for f in sorted((INTERIM / "demographie").glob("*.csv"))}
    _zip(noter(nom("02-nettoyage", "engineer", "tables-propres", "zip"),
               "Tables nettoyées (annuaires, fichier principal, démographie) et leurs fichiers d'écarts"), propres)
    shutil.copy(DOCS / "journal_nettoyage.md", noter(nom("02-nettoyage", "engineer", "journal-nettoyage", "md"),
                                                     "Journal de nettoyage : opérations, pièges traités, contrôles, décisions"))
    # 03 — transformation
    _csv(_lire(TRAITE / "province_annee.csv"), noter(nom("03-transformation", "architect", "table-province-annee", "csv"),
                                                     "Table d'analyse : une ligne par année, province et statut"))
    noter(nom("03-transformation", "architect", "dictionnaire-variables", "md"),
          "Dictionnaire des variables et schéma des tables").write_text(dictionnaire_md(e, v), encoding="utf-8")
    corr = RACINE / "outputs" / "controles" / "correspondance_decoupage_2025.csv"
    _csv(geo.correspondance(), corr)
    ref = {f"referentiel/{f.name}": f for f in sorted((RACINE / "referentiel").glob("*")) if f.suffix in (".csv", ".yaml")}
    _zip(noter(nom("03-transformation", "architect", "referentiel-territorial", "zip"),
               "Référentiel territorial versionné (351 communes, découpages 2017-2025 et 2025, variantes de noms), "
               "catalogue des données importables, passage des 45 provinces au découpage de 2025"),
         ref | {"correspondance_decoupage_2025.csv": corr})
    # 04 — analyse
    _csv(_lire(TRAITE / "indice_besoin.csv"), noter(nom("04-analyse", "analyst", "indicateurs-indice-besoin", "csv"),
                                                    "Indicateurs de l'année de référence, indice de besoin, robustesse du rang"))
    _zip(noter(nom("04-analyse", "analyst", "controles", "zip"),
               "Contrôles : rapprochement des annuaires avec le fichier principal ; post-primaire (totaux, cohérence, libellés)"),
         {"rapprochement_annuaires_principal.csv": RACINE / "outputs" / "controles" / "rapprochement_annuaires_principal.csv",
          "controles_post_primaire.csv": RACINE / "outputs" / "controles" / "post_primaire_controles.csv"})
    _csv(_lire(TRAITE / "prevision_effectifs.csv"), noter(nom("04-analyse", "scientist", "previsions-effectifs-2030", "csv"),
                                                          "Effectifs prévus par province jusqu'à l'horizon, avec marges"))
    _csv(_lire(TRAITE / "prevision_fiabilite.csv"), noter(nom("04-analyse", "scientist", "fiabilite-prevision", "csv"),
                                                          "Erreur des méthodes de prévision dans le test sur le passé"))
    _csv(_lire(TRAITE / "prevision_essai_ml.csv"), noter(nom("04-analyse", "scientist", "essai-apprentissage-automatique", "csv"),
                                                         "Essai d'apprentissage automatique : erreur comparée aux autres méthodes, mêmes cas"))
    _csv(pd.concat([_lire(TRAITE / "scenarios_bilan.csv").assign(type_scenario="grille"),
                    _lire(TRAITE / "scenarios_budget.csv").assign(type_scenario="budget_seul"),
                    _lire(TRAITE / "sensibilite.csv").assign(type_scenario="sensibilite"),
                    _lire(TRAITE / "retrospectif_bilan.csv").assign(type_scenario="test_retrospectif")], ignore_index=True),
         noter(nom("04-analyse", "scientist", "repartition-scenarios", "csv"),
               "Bilan des scénarios de répartition (grille, budget, sensibilité) et du test sur le passé (2019→2024, 2018→2023)"))
    _csv(_lire(TRAITE / "post_primaire_region.csv"), noter(nom("04-analyse", "analyst", "diagnostic-post-primaire", "csv"),
                                                           "Post-primaire par région, 2022-2023 et 2023-2024 : indicateurs et signaux"))
    cs = _lire(TRAITE / "carte_scolaire_commune.csv").merge(
        _lire(TRAITE / "acces_ecole_commune.csv").drop(columns=["commune", "province", "region", "enfants"]), on="pcode_commune", how="left")
    _csv(cs, noter(nom("04-analyse", "analyst", "carte-scolaire-commune", "csv"),
                   "Carte scolaire des 351 communes : enfants 2030, écoles repérées, déplacés, accès à l'école"))
    _csv(_lire(TRAITE / "sites_proposes.csv"), noter(nom("04-analyse", "scientist", "sites-proposes", "csv"),
                                                    "Sites où ouvrir une école, avec la recommandation construire ou rouvrir"))
    code = {f"src/dcb/{f.name}": f for f in sorted((RACINE / "src" / "dcb").glob("*")) if f.suffix in (".py", ".html")}
    code |= {f"tests/{f.name}": f for f in sorted((RACINE / "tests").glob("*.py"))}
    code |= {f"referentiel/{f.name}": f for f in sorted((RACINE / "referentiel").glob("*")) if f.suffix in (".csv", ".yaml")}
    code |= {f"deploiement/{f.name}": f for f in sorted((RACINE / "deploiement").glob("*"))}
    interface = RACINE / "interface"
    code |= {f"interface/{f.relative_to(interface).as_posix()}": f for f in sorted(interface.rglob("*"))
             if f.is_file() and not ({"node_modules", "dist"} & set(f.relative_to(interface).parts))
             and f.suffix in (".ts", ".tsx", ".js", ".css", ".html", ".json", ".svg", ".md", ".mp4", ".jpg") and f.name != "tsconfig.tsbuildinfo"}
    code |= {"config.yaml": RACINE / "config.yaml", "requirements.txt": RACINE / "requirements.txt",
             "README.md": DOCS / "README_code.md", "LICENSE": RACINE / "LICENSE", "NOTICE": RACINE / "NOTICE",
             "docs/guide_installation_exploitation.md": RACINE / "docs" / "guide_installation_exploitation.md",
             "data/external/SOURCES.md": RACINE / "data" / "external" / "SOURCES.md"}
    _zip(noter(nom("04-analyse", "scientist", "code-pipeline", "zip"),
               "Code complet, tests, paramètres et mode d'emploi pour reproduire les résultats"), code)
    # 05 — interprétation
    _zip(noter(nom("05-interpretation", "analyst", "tableau-de-bord", "zip"),
               "Tableau de bord : décompresser puis ouvrir le fichier .html, sans connexion"),
         {"tableau_de_bord.html": RACINE / "outputs" / "tableau_de_bord" / "tableau_de_bord.html"})
    plan_xlsx(noter(nom("05-interpretation", "analyst", "plan-repartition", "xlsx"),
                    "Plan de répartition du scénario de référence, par province"), cfg)
    doc = RACINE / "docs" / "documentation.pdf"
    if doc.exists():
        shutil.copy(doc, noter(nom("05-interpretation", "analyst", "documentation", "pdf"), "Documentation de la solution"))
    else:
        print("ATTENTION : docs/documentation.pdf absent, la documentation n'est pas dans le dépôt")

    # LISEZ-MOI
    adresse = cfg["service"].get("adresse_publique", "")
    lignes = ["# LISEZ-MOI — Défi 3 : répartition des enseignants et des salles de classe", "",
              "Solution : diagnostic par province, besoins à la rentrée 2030, répartition optimisée des moyens nouveaux,",
              "carte scolaire à la commune, test sur le passé ; diagnostic régional du post-primaire.", "",
              f"**Pour commencer : ouvrir l'application en ligne {adresse}** (sans installation ni compte ;",
              "une visite guidée se lance à la première ouverture).",
              "Sans connexion : décompresser l'archive du tableau de bord (étape 05) et ouvrir le fichier `.html`.",
              "Documentation : le PDF de l'étape 05 (15 pages).",
              "Pour reproduire ou installer : `README.md` et `docs/guide_installation_exploitation.md` de l'archive de code (étape 04)"
              + (f", aussi sur GitHub : {d['lien_github']}" if d.get("lien_github") else "") + ".",
              "Présentation vidéo (2 min 38) : elle se lance à la première ouverture de l'application, et reste sur sa page d'accueil.", "",
              "Les fichiers sont rangés par étape : `01_collecte`, `02_nettoyage`, `03_transformation`, `04_analyse`, `05_interpretation`.", "",
              "| Fichier | Contenu |", "|---|---|"]
    lignes += [f"| `{c.parent.name}/{c.name}` | {desc} |" for c, desc in sorted(produits)]
    lignes += ["", "Les fichiers CSV utilisent le point-virgule comme séparateur et la virgule décimale (encodage UTF-8).", ""]
    lisez = DEPOT / f"{e}_{defi}_LISEZ-MOI_v{v}.md"
    lisez.write_text("\n".join(lignes), encoding="utf-8")
    return [lisez, *[c for c, _ in produits]]


def _contenus(nom: str, donnees: bytes):
    """Parcourt un fichier et, s'il s'agit d'une archive ou d'un classeur, ce qu'il contient."""
    yield nom, donnees
    if donnees[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(donnees)) as z:
                for info in z.infolist():
                    yield from _contenus(f"{nom} > {info.filename}", z.read(info))
        except zipfile.BadZipFile:
            pass
    elif donnees[:4] == b"%PDF":
        try:
            from pypdf import PdfReader

            lecteur = PdfReader(io.BytesIO(donnees))
            texte = "\n".join((page.extract_text() or "") for page in lecteur.pages) + "\n" + str(dict(lecteur.metadata or {}))
            yield f"{nom} > texte et métadonnées", texte.encode("utf-8")
        except Exception as erreur:  # un PDF illisible doit être signalé, pas ignoré
            yield f"{nom} > ILLISIBLE ({erreur})", b""


def controler(fichiers: list[Path]) -> list[str]:
    """Liste des problèmes : termes interdits, noms non conformes, limites de la plateforme."""
    problemes = []
    if not TERMES.exists():
        return [f"fichier {TERMES.name} absent : le contrôle des termes interdits n'a pas pu être fait"]
    termes = [t.strip() for t in TERMES.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]
    for f in fichiers:
        if any(ord(c) > 127 or c == " " for c in f.name):
            problemes.append(f"{f.name} : nom avec espace ou accent")
        if f.stat().st_size > 50 * 1024 * 1024:
            problemes.append(f"{f.name} : plus de 50 Mo")
        for nom, donnees in _contenus(f.name, f.read_bytes()):
            if "ILLISIBLE" in nom:
                problemes.append(nom)
            if nom.split(" > ")[-1].split("/")[-1] in ("LICENSE", "NOTICE"):
                # seule exception voulue : le titulaire des droits, sur la ligne de copyright
                donnees = bytes([10]).join(l for l in donnees.splitlines() if not l.lstrip().startswith(b"Copyright"))
            bas = donnees.lower()
            for t in termes:
                for forme in (t.lower().encode("utf-8"), t.lower().encode("utf-16-le"), t.lower().encode("latin-1", "ignore")):
                    if forme and forme in bas:
                        problemes.append(f"{nom} : contient « {t} »")
                        break
            if nom != f.name and any(t.lower() in nom.lower() for t in termes):
                problemes.append(f"{nom} : nom interne contenant un terme interdit")
    if len(fichiers) > 20:
        problemes.append(f"{len(fichiers)} fichiers : la plateforme en accepte 20")
    if sum(f.stat().st_size for f in fichiers) > 500 * 1024 * 1024:
        problemes.append("plus de 500 Mo au total")
    return problemes


if __name__ == "__main__":
    fichiers = construire()
    print(f"{len(fichiers)} fichiers dans depot/ ({sum(f.stat().st_size for f in fichiers) / 1e6:.1f} Mo)")
    for f in sorted(fichiers):
        print(f"  {f.stat().st_size / 1024:>8.0f} ko  {f.relative_to(DEPOT).as_posix()}")
    if config()["depot"]["code_equipe"] == "EQUIPE":
        print("\nRAPPEL : code d'équipe non renseigné (config.yaml, rubrique depot)")
    problemes = controler(fichiers)
    if problemes:
        print(f"\nCONTROLE AVANT DEPOT : {len(problemes)} PROBLEME(S)")
        for p in problemes:
            print("  -", p)
        sys.exit(1)
    print("\nContrôle avant dépôt : aucun terme interdit, noms conformes, limites respectées")
