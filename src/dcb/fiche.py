"""Classeur Excel d'un plan de répartition : la fiche de décision, le plan par province, la comparaison, les hypothèses.

Produit par le service (`POST /api/repartir.xlsx`) à partir du même calcul que l'écran : un plan exporté est
identique au plan affiché, et il porte ses paramètres, pour être relu, transmis ou archivé.
"""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

VERT = "1F5C4A"
STATUTS = {"Optimal": "meilleur plan possible (vérifié par le calcul)",
           "Non prouvé optimal": "meilleur plan trouvé dans le temps de calcul"}
METHODES = {"sans_moyens_nouveaux": "Sans moyens nouveaux", "proportionnelle": "Partage selon le nombre d'élèves",
            "besoins": "Partage selon les manques", "optimisee": "Plan Yennenga"}
LIB_BORNES = {"min_enseignants": "au moins {} enseignants", "max_enseignants": "au plus {} enseignants",
              "min_salles": "au moins {} salles", "max_salles": "au plus {} salles"}


def _n(x: float, decimales: int = 0) -> str:
    """Nombre à la française : espace pour les milliers, virgule décimale."""
    return f"{x:,.{decimales}f}".replace(",", " ").replace(".", ",")


def _joli(nom: str | None) -> str:
    from dcb.territoire import nom_officiel
    return nom_officiel(str(nom or ""))


def _entete(ws, ligne: int, titres: list[str]) -> None:
    for j, t in enumerate(titres, 1):
        c = ws.cell(ligne, j, t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=VERT)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = ws.cell(ligne + 1, 1)


def _largeurs(ws, largeurs: list[int]) -> None:
    for j, l in enumerate(largeurs, 1):
        ws.column_dimensions[get_column_letter(j)].width = l


def contraintes_texte(demande: dict) -> list[str]:
    lignes = []
    for niveau, lib in (("provinces", "Province"), ("regions", "Région")):
        for nom, bornes in (demande.get(niveau) or {}).items():
            for cle, v in bornes.items():
                if v is not None:
                    lignes.append(f"{lib} {_joli(nom)} : {LIB_BORNES[cle].format(v)}")
    return lignes


def classeur(demande: dict, res: dict, cfg: dict) -> bytes:
    opt = cfg["optimisation"]
    bilan = {b["methode"]: b for b in res["bilan"]}
    o = bilan["optimisee"]
    wb = Workbook()

    # 1. fiche de décision
    ws = wb.active
    ws.title = "Fiche"
    ws["A1"] = "Plan de répartition des enseignants et des salles de classe — primaire public"
    ws["A1"].font = Font(bold=True, size=14, color=VERT)
    ws["A2"] = f"Calculé le {datetime.now():%d/%m/%Y à %H:%M} par l'outil Yennenga · {STATUTS.get(res['statut'], res['statut'])}"
    moyens = (f"budget de {_n(demande['budget_fcfa'] / 1e9, 1)} milliards de FCFA (l'outil choisit postes et salles)"
              if demande.get("budget_seul") else
              f"{demande.get('enseignants') or opt['enseignants_a_repartir']} enseignants et "
              f"{demande.get('salles') if demande.get('salles') is not None else opt['salles_a_construire']} salles au plus")
    lignes = [
        ("Paramètres", None),
        ("Horizon", res["horizon"]),
        ("Évolution des effectifs", {"tendance": "scénario central (tendance)", "reouverture": "réouverture des écoles fermées"}
         .get(res["scenario"], res["scenario"])),
        ("Élèves du privé passés dans le public", f"{_n(res.get('recul_prive') or 0)} % d'ici l'horizon"
         if res.get("recul_prive") else "aucun : part du privé de l'année de référence supposée stable"),
        ("Norme", f"{res['norme_eleves_par_maitre']} élèves par enseignant et par salle"),
        ("Moyens", moyens),
        ("Redéploiement accepté", f"jusqu'à {demande.get('redeploiement', 0)} enseignants en poste" if demande.get("redeploiement") else "aucun"),
        ("Coût d'un poste", f"{_n(opt['cout_enseignant_fcfa'])} FCFA par an, compté sur {opt.get('annees_budget', 1)} ans"),
        ("Coût d'une salle", f"{_n(res.get('cout_salle_fcfa', opt['cout_salle_fcfa']))} FCFA"
         + (" (complexe de 3 salles tout compris)" if demande.get("cout_salle") == "complexe" else " (salle seule)")),
        ("Exigences", " ; ".join(contraintes_texte(demande)) or "aucune"),
        ("", None),
        ("Résultat", None),
        ("Enseignants affectés", res["enseignants_utilises"]),
        ("Enseignants redéployés", res.get("enseignants_redeployes", 0)),
        ("Salles construites", res["salles_utilisees"]),
        ("Salles d'écoles fermées à rouvrir", o.get("salles_rouvertes", 0)),
        ("Investissement en salles (FCFA)", round(res.get("cout_salles_fcfa", 0))),
        ("Salaires des postes créés, par an (FCFA)", round(res.get("salaires_annuels_fcfa", 0))),
        (f"Coût du plan sur {res.get('annees_budget', 1)} ans (FCFA)", round(res["cout_fcfa"])),
        ("Province la plus chargée après le plan", f"{_n(o['pire_ratio_eleves_maitre'], 1)} élèves par enseignant "
         f"(sans moyens nouveaux : {_n(bilan['sans_moyens_nouveaux']['pire_ratio_eleves_maitre'], 1)} ; "
         f"en partageant selon le nombre d'élèves : {_n(bilan['proportionnelle']['pire_ratio_eleves_maitre'], 1)})"),
        ("Élèves en trop dans les classes surchargées", round(o["eleves_au_dela_norme_maitre"])),
        ("Provinces au-dessus de la norme", o["provinces_au_dessus_norme_maitre"]),
        ("", None),
        ("Visa", None),
        ("Préparé par", ""), ("Validé par", ""), ("Date et signature", ""),
    ]
    for i, (k, v) in enumerate(lignes, 4):
        ws.cell(i, 1, k)
        if v is None and k:
            ws.cell(i, 1).font = Font(bold=True, color=VERT, size=12)
        else:
            ws.cell(i, 1).font = Font(bold=True)
            ws.cell(i, 2, v)
            ws.cell(i, 2).alignment = Alignment(wrap_text=True, vertical="top")
            if isinstance(v, int):
                ws.cell(i, 2).number_format = "# ##0"
    _largeurs(ws, [38, 90])

    # 2. plan par province
    ws = wb.create_sheet("Plan par province")
    titres = ["Province", "Région", "Élèves attendus", "Enseignants en poste", "Enseignants affectés", "Solde des redéploiements",
              "Salles existantes", "Salles construites", "Salles d'écoles fermées à rouvrir", "Élèves par enseignant après",
              "Élèves par salle après", "Construction", "Pourquoi"]
    _entete(ws, 1, titres)
    plan = sorted(res["repartitions"]["optimisee"], key=lambda l: -(l["enseignants_attribues"] or 0))
    for i, l in enumerate(plan, 2):
        constr = ("programmée" if l["construction_possible"] else
                  "rouvrir d'abord" if l.get("rouvrir_d_abord") and l.get("acces_construction") else "accès dégradé")
        valeurs = [_joli(l["province"]), _joli(l["region"]), l["eleves_horizon"], l["maitres"], l["enseignants_attribues"],
                   l.get("solde_redeploiement") or 0, l["salles"], l["salles_attribuees"], l.get("salles_rouvertes") or 0,
                   l["ratio_maitre_apres"], l["ratio_salle_apres"], constr, l.get("motif") or ""]
        for j, v in enumerate(valeurs, 1):
            c = ws.cell(i, j, v)
            if j in (10, 11):
                c.number_format = "0.0"
            elif isinstance(v, (int, float)):
                c.number_format = "# ##0"
    n = len(plan) + 2
    ws.cell(n, 1, "Total").font = Font(bold=True)
    for j in (3, 4, 5, 6, 7, 8, 9):
        col = get_column_letter(j)
        c = ws.cell(n, j, f"=SUM({col}2:{col}{n - 1})")
        c.font, c.number_format = Font(bold=True), "# ##0"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(titres))}{n - 1}"
    _largeurs(ws, [18, 20, 12, 12, 12, 13, 11, 11, 14, 13, 11, 15, 60])
    ws.row_dimensions[1].height = 45

    # 3. comparaison à moyens égaux
    ws = wb.create_sheet("Comparaison")
    _entete(ws, 1, ["Répartition", "Province la plus chargée (élèves par enseignant)", "Écart entre provinces (Gini, 0 = égalité)",
                    "Élèves dans une province sans surcharge", "Provinces encore surchargées", "Élèves en trop dans les classes surchargées"])
    for i, k in enumerate(METHODES, 2):
        b = bilan.get(k)
        if not b:
            continue
        for j, v in enumerate([METHODES[k], b["pire_ratio_eleves_maitre"], b["gini_ratio_maitre"],
                               b["part_eleves_province_conforme"], b["provinces_au_dessus_norme_maitre"],
                               round(b["eleves_au_dela_norme_maitre"])], 1):
            c = ws.cell(i, j, v)
            c.number_format = {2: "0.0", 3: "0.000", 4: "0%", 6: "# ##0"}.get(j, "General")
            if k == "optimisee":
                c.font = Font(bold=True)
    ws.cell(7, 1, "Mêmes moyens pour toutes les répartitions ; les règles simples respectent les mêmes règles de salles. "
                  "Les exigences du décideur et les mutations ne s'appliquent qu'au plan Yennenga.")
    _largeurs(ws, [26, 22, 14, 16, 16, 16])
    ws.row_dimensions[1].height = 45

    # 3 bis. mouvements de redéploiement
    if res.get("mouvements"):
        ws = wb.create_sheet("Mouvements")
        _entete(ws, 1, ["De la province", "Vers la province", "Enseignants", "Distance entre centres (km)"])
        for i, mv in enumerate(res["mouvements"], 2):
            for j, v in enumerate([_joli(mv["de"]), _joli(mv["vers"]), mv["enseignants"], mv["distance_km"]], 1):
                ws.cell(i, j, v)
        n = len(res["mouvements"]) + 3
        ws.cell(n, 1, "Appariement proposé : les mouvements les plus courts d'abord. Le modèle fixe combien part de chaque "
                      "province et combien arrive ; le choix des personnes relève des services.")
        _largeurs(ws, [22, 22, 14, 24])

    # 4. hypothèses
    ws = wb.create_sheet("Hypothèses")
    _entete(ws, 1, ["Hypothèse", "Valeur retenue"])
    imp = cfg.get("implantation", {})
    hyp = [
        ("Effectifs à l'horizon", "prévision par province, méthode choisie sur son erreur mesurée sur le passé"),
        ("Un maître par salle", "un enseignant affecté doit disposer d'une salle libre, construite ou rouverte"),
        ("Zone peu accessible", f"pas de construction si l'effectif est tombé sous {opt['seuil_acces_construction']:.0%} de son maximum"),
        ("Rouvrir avant de construire", f"pas de salle neuve au-delà de {imp.get('seuil_fermeture_rouvrir', 0.2):.0%} d'écoles fermées ; "
                                        "les salles perdues depuis le maximum 2017-2025 accueillent les enseignants (remise en état non chiffrée)"),
        ("Redéploiement", "un enseignant ne quitte qu'une province qui reste à la norme ; il lui faut une salle à l'arrivée"),
        ("Critère", "réduire d'abord la surcharge des provinces les plus chargées (pénalité croissante avec la surcharge)"),
        ("Sources", "annuaires statistiques de l'éducation de base 2017-2018 à 2024-2025 ; projections INSD ; coûts : CN-EPT/BF 2023, "
                    "marchés communaux 2025, bilan 2024 de la gratuité"),
    ]
    for i, (k, v) in enumerate(hyp, 2):
        ws.cell(i, 1, k).font = Font(bold=True)
        ws.cell(i, 2, v).alignment = Alignment(wrap_text=True, vertical="top")
    _largeurs(ws, [30, 100])

    for feuille in wb.worksheets:
        feuille.page_setup.orientation = "landscape"
        feuille.page_setup.fitToWidth = 1
        feuille.sheet_properties.pageSetUpPr.fitToPage = True
        feuille.page_setup.fitToHeight = 0
    wb.properties.creator = "Yennenga"
    wb.properties.title = "Plan de répartition"
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()
