"""Génère le tableau de bord : un seul fichier HTML, sans connexion ni installation.

Toutes les données sont incorporées dans le fichier ; aucune ressource distante n'est appelée.

Usage : PYTHONPATH=src python -m dcb.tableau_de_bord   (après dcb.scenarios)
Produit outputs/tableau_de_bord/tableau_de_bord.html
"""
from __future__ import annotations

import json
import math

import pandas as pd

from dcb import geo
from dcb.indicateurs import SORTIE as TRAITE
from dcb.indicateurs import config
from dcb.lecture import RACINE

GABARIT = RACINE / "src" / "dcb" / "gabarit_tableau_de_bord.html"
SORTIE = RACINE / "outputs" / "tableau_de_bord"
LARGEUR = 760  # largeur de la carte en unités SVG


def _lire(nom: str) -> pd.DataFrame:
    return pd.read_csv(TRAITE / nom, sep=";", encoding="utf-8")


def _arrondi(x, n=1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


def tracer_provinces() -> tuple[list[dict], list[dict], int]:
    """Contours des provinces et des régions convertis en tracés SVG (projection plane simple, suffisante à cette latitude)."""
    g = geo.contours_provinces()
    minx, miny, maxx, maxy = g.total_bounds
    cos = math.cos(math.radians((miny + maxy) / 2))
    k = LARGEUR / ((maxx - minx) * cos)
    hauteur = int((maxy - miny) * k) + 1
    corr = geo.correspondance()

    def anneau(coords) -> str:
        pts = [f"{(x - minx) * cos * k:.1f},{(maxy - y) * k:.1f}" for x, y in coords]
        return "M" + "L".join(pts) + "Z"

    def trace(geom) -> str:
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        return "".join(anneau(p.exterior.coords) for p in polys)

    provinces = []
    for _, r in g.iterrows():
        c = r.geometry.representative_point()
        c25 = corr[corr["province"] == r["province"]]
        provinces.append({
            "nom": r["province"], "region": r["region"], "d": trace(r.geometry),
            "cx": round((c.x - minx) * cos * k, 1), "cy": round((maxy - c.y) * k, 1),
            "prov2025": sorted(c25["province_2025"]), "reg2025": sorted(c25["region_2025"].unique()),
        })
    reg = g.dissolve(by="region").reset_index()
    reg["geometry"] = reg.geometry.buffer(0).simplify(0.005, preserve_topology=True)
    regions = [{"nom": r["region"], "d": trace(r.geometry)} for _, r in reg.iterrows()]
    return provinces, regions, hauteur


POST_PRIMAIRE = ["eleves_pp", "garcons_pp", "filles_pp", "etablissements", "etablissements_2019",
                 "evolution_etablissements_2019", "salles", "salles_2019", "evolution_salles_2019", "eleves_pp_sec",
                 "eleves_par_salle", "eleves_par_classe_6e", "eleves_par_classe_pp", "eleves_par_classe_sec",
                 "eleves_eg_public", "places_assises", "deficit_places", "excedent_places", "part_eleves_sans_place",
                 "etablissements_en_deficit", "etablissements_eg_public", "enseignants", "pct_qualifies",
                 "pct_enseignantes", "pct_latrines", "pct_eau_potable", "pct_electricite", "nombre_signaux",
                 "signal_6e_au_dessus_norme", "signal_places_manquantes", "signal_perte_etablissements"]


def donnees_post_primaire() -> dict:
    t = _lire("post_primaire_region.csv")
    out = {}
    for annee, g in t.groupby("annee_scolaire"):
        out[annee] = {r["region"]: {c: (None if pd.isna(r[c]) else bool(r[c]) if c.startswith("signal_")
                                        else _arrondi(r[c], 4)) for c in POST_PRIMAIRE}
                      for _, r in g.iterrows()}
    return out


def donnees() -> dict:
    cfg = config()
    cible = cfg["statut_cible"]
    t = _lire("province_annee.csv")
    t = t[t["statut"] == cible]
    indic = {}
    for annee, g in t.groupby("annee_scolaire"):
        indic[annee] = {r["province"]: [int(r["eleves"]), int(r["maitres"]), int(r["salles"]),
                                        _arrondi(r["eleves_par_maitre"]), _arrondi(r["eleves_par_salle"]),
                                        _arrondi(r["part_salles_precaires"] * 100), _arrondi(r["part_salles_mauvais_etat"] * 100),
                                        _arrondi(r["part_du_pic"] * 100, 0)]
                         for _, r in g.iterrows()}
    ind = _lire("indice_besoin.csv")
    indice = {r["province"]: [_arrondi(r["indice_besoin"], 3), int(r["rang"]), int(r["rang_p05"]), int(r["rang_p95"]),
                              bool(r["rang_instable"])] for _, r in ind.iterrows()}
    s = _lire("serie_effectifs_province.csv")
    serie = {p: [[int(a[:4]), int(e)] for a, e in zip(g["annee_scolaire"], g["eleves"])]
             for p, g in s.sort_values("annee_scolaire").groupby("province")}
    pv = _lire("prevision_effectifs.csv")
    prev = {sc: {p: [[int(a[:4]), int(v), int(b), int(h)] for a, v, b, h in
                     zip(g2["annee_scolaire"], g2["eleves_prevus"], g2["borne_basse"], g2["borne_haute"])]
                 for p, g2 in g.sort_values("annee_scolaire").groupby("province")}
            for sc, g in pv.groupby("scenario")}
    fiab = _lire("prevision_fiabilite.csv")
    fiab = fiab[(fiab["perimetre"] == "cas_communs") & (fiab["groupe"] != "ensemble")]
    fiabilite = {grp: {m: [_arrondi(w * 100) for w in g2.sort_values("horizon")["wape"]] for m, g2 in g.groupby("methode")}
                 for grp, g in fiab.groupby("groupe")}
    methode_retenue = {grp: g.loc[g["retenue"], "methode"].iloc[0] for grp, g in fiab.groupby("groupe")}
    groupes = pv.drop_duplicates("province").set_index("province")["groupe"].to_dict()

    bil, al = _lire("scenarios_bilan.csv"), _lire("scenarios_allocation.csv")
    mesures = ["enseignants_attribues", "salles_attribuees", "eleves_au_dela_norme_maitre", "eleves_au_dela_norme_salle",
               "provinces_au_dessus_norme_maitre", "provinces_au_dessus_norme_salle", "pire_ratio_eleves_maitre",
               "ecart_type_ratio_maitre", "gini_ratio_maitre", "part_eleves_province_conforme"]
    scen, horizon = {}, {}
    cles = ["demande", "enseignants_disponibles", "salles_disponibles"]
    for (dem, n, m), g in bil.groupby(cles):
        scen[f"{dem}|{n}|{m}"] = {"bilan": {r["methode"]: [_arrondi(r[x], 4) for x in mesures] for _, r in g.iterrows()}, "alloc": {}}
    for (dem, n, m), g in al.groupby(cles):
        o = g[g["methode"] == "optimisee"].set_index("province")
        p = g[g["methode"] == "proportionnelle"].set_index("province")
        scen[f"{dem}|{n}|{m}"]["alloc"] = {prov: [int(o.loc[prov, "enseignants_attribues"]), int(o.loc[prov, "salles_attribuees"]),
                                                   int(p.loc[prov, "enseignants_attribues"]), int(p.loc[prov, "salles_attribuees"])]
                                            for prov in o.index}
        horizon.setdefault(dem, {prov: int(o.loc[prov, "eleves_horizon"]) for prov in o.index})
    construction = {prov: bool(v) for prov, v in al.drop_duplicates("province").set_index("province")["construction_possible"].items()}
    provinces, regions, hauteur = tracer_provinces()
    return {
        "meta": {"annee_reference": cfg["annee_reference"], "annee_horizon": cfg["annee_horizon"], "statut_cible": cible,
                 "normes": cfg["normes"], "methode_prevision": methode_retenue, "carte": [LARGEUR, hauteur],
                 "couts": {"salle": cfg["optimisation"]["cout_salle_fcfa"], "enseignant": cfg["optimisation"]["cout_enseignant_fcfa"]},
                 "seuil_acces": cfg["optimisation"]["seuil_acces_construction"],
                 "tirages": cfg["indice"]["tirages_robustesse"], "ponderations": cfg["indice"]["ponderations"], "indice": cfg["indice"],
                 "post_primaire": cfg["post_primaire"]},
        "provinces": provinces, "annees": sorted(indic), "indic": indic, "indice": indice, "serie": serie, "prev": prev,
        "fiabilite": fiabilite, "groupes": groupes, "scen": scen, "horizon": horizon, "construction": construction,
        "grille": cfg["scenarios"], "mesures_bilan": mesures,
        "regions": regions, "pp": donnees_post_primaire(),
    }


def generer() -> None:
    d = donnees()
    charge = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = GABARIT.read_text(encoding="utf-8").replace("/*__DONNEES__*/null", charge)
    SORTIE.mkdir(parents=True, exist_ok=True)
    cible = SORTIE / "tableau_de_bord.html"
    cible.write_text(html, encoding="utf-8")
    print(f"{cible.relative_to(RACINE)} : {cible.stat().st_size / 1024:.0f} ko, {len(d['provinces'])} provinces, {len(d['scen'])} scénarios")


if __name__ == "__main__":
    generer()
