"""Données de l'application web : fichiers JSON légers lus par l'interface (outputs/web/).

Contours simplifiés (communes, provinces des annuaires, provinces et régions de 2025), indicateurs par province et
par commune, sites proposés, paramètres. Tout vient des sorties de la chaîne : l'interface n'a aucun calcul propre,
hormis la répartition à la demande, faite par le service avec le même code que la chaîne.

Usage : PYTHONPATH=src python -m dcb.export_web   (après dcb.implantation)
"""
from __future__ import annotations

import json
import math

import pandas as pd

from dcb import geo, territoire
from dcb.indicateurs import SORTIE as TRAITE
from dcb.indicateurs import config
from dcb.lecture import RACINE

INTERIM = RACINE / "data" / "interim"

WEB = RACINE / "outputs" / "web"


def _propre(x):
    if isinstance(x, float):
        return None if math.isnan(x) else round(x, 4)
    if hasattr(x, "item"):
        return _propre(x.item())
    return x


def _lignes(df: pd.DataFrame) -> list[dict]:
    return [{k: _propre(v) for k, v in r.items()} for r in df.to_dict(orient="records")]


def _ecrire(nom: str, objet) -> None:
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / nom).write_text(json.dumps(objet, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _geojson(g, tolerance: float, proprietes: list[str], decimales: int = 3) -> dict:
    """Contours allégés pour les connexions lentes : simplifiés, coordonnées arrondies (3 décimales ≈ 110 m)."""
    g = g.copy()
    g["geometry"] = g.geometry.buffer(0).simplify(tolerance, preserve_topology=True)
    feats = []
    for _, r in g.iterrows():
        geom = json.loads(json.dumps(r.geometry.__geo_interface__))

        def arrondi(c):
            return [arrondi(x) for x in c] if isinstance(c, (list, tuple)) and c and isinstance(c[0], (list, tuple)) \
                else [round(c[0], decimales), round(c[1], decimales)]
        geom["coordinates"] = arrondi(geom["coordinates"])
        feats.append({"type": "Feature", "properties": {p: _propre(r[p]) for p in proprietes}, "geometry": geom})
    return {"type": "FeatureCollection", "features": feats}


def contours() -> None:
    import geopandas as gpd

    from dcb.carte_scolaire import LIMITES

    ref = territoire.charger()
    c = gpd.read_file(f"zip://{LIMITES.as_posix()}!bfa_admin3.geojson")[["adm3_pcode", "geometry"]]
    c = c.rename(columns={"adm3_pcode": "pcode_commune"})
    r25 = ref.decoupage("reforme_2025")
    ran = ref.decoupage("annuaires_2017_2025")[["pcode_commune", "province", "region"]].rename(
        columns={"province": "province_ancienne", "region": "region_ancienne"})
    c = c.merge(ref.communes[["pcode_commune", "commune"]], on="pcode_commune").merge(r25, on="pcode_commune").merge(ran, on="pcode_commune")
    # seuls le code de la commune et sa province des annuaires servent à l'application (noms et chiffres : communes.json)
    _ecrire("geo_communes.json", _geojson(c, 0.004, ["pcode_commune", "province_ancienne"]))
    p25 = c.dissolve(by="code_province", as_index=False)[["code_province", "province", "region", "geometry"]]
    _ecrire("geo_provinces_2025.json", _geojson(p25, 0.006, ["code_province", "province", "region"]))
    r = c.dissolve(by="code_region", as_index=False)[["code_region", "region", "geometry"]]
    _ecrire("geo_regions_2025.json", _geojson(r, 0.008, ["code_region", "region"]))
    pa = c.dissolve(by="province_ancienne", as_index=False)[["province_ancienne", "region_ancienne", "geometry"]]
    pa = pa.rename(columns={"province_ancienne": "province", "region_ancienne": "region"})
    _ecrire("geo_provinces_annuaires.json", _geojson(pa, 0.006, ["province", "region"]))


def provinces(cfg: dict) -> list[dict]:
    t = pd.read_csv(TRAITE / "province_annee.csv", sep=";", encoding="utf-8")
    ref = t[(t["annee_scolaire"] == cfg["annee_reference"]) & (t["statut"] == cfg["statut_cible"])]
    cols = ["province", "region", "eleves", "maitres", "salles", "ecoles", "eleves_par_maitre", "eleves_par_salle",
            "part_salles_precaires", "part_salles_mauvais_etat", "maitres_manquants", "salles_manquantes", "part_du_pic"]
    p = ref[cols].set_index("province")
    tot = t[t["statut"] == "total"]
    p["part_ecoles_fermees"] = 1 - tot[tot["annee_scolaire"] == cfg["annee_reference"]].set_index("province")["ecoles"] \
        / tot.groupby("province")["ecoles"].max()
    ind = pd.read_csv(TRAITE / "indice_besoin.csv", sep=";", encoding="utf-8").set_index("province")
    p = p.join(ind[["indice_besoin", "rang", "rang_p05", "rang_p95", "rang_instable", "score_surcharge", "score_bati"]])
    al = pd.read_csv(TRAITE / "allocation.csv", sep=";", encoding="utf-8")
    o = al[al["methode"] == "optimisee"].set_index("province")
    p = p.join(o[["eleves_horizon", "construction_possible", "enseignants_attribues", "salles_attribuees", "salles_rouvertes",
                  "ratio_maitre_apres", "ratio_salle_apres"]])
    s = pd.read_csv(TRAITE / "serie_effectifs_province.csv", sep=";", encoding="utf-8")
    pv = pd.read_csv(TRAITE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    out = []
    for prov, r in p.iterrows():
        d = {"province": prov, **{k: _propre(v) for k, v in r.items()}}
        d["serie"] = [[int(a[:4]), int(e)] for a, e in s[s["province"] == prov].sort_values("annee_scolaire")[["annee_scolaire", "eleves"]].values]
        d["prevision"] = {sc: [[int(a[:4]), int(v), int(b), int(h)] for a, v, b, h in
                               g[["annee_scolaire", "eleves_prevus", "borne_basse", "borne_haute"]].values]
                          for sc, g in pv[pv["province"] == prov].sort_values("annee_scolaire").groupby("scenario")}
        out.append(d)
    return out


def _validation() -> dict:
    """Chiffres de contrôle affichés dans la vue Méthode, lus dans les sorties de la chaîne."""
    from dcb.lecture import RACINE as R
    v: dict = {}
    f = R / "outputs" / "controles" / "rapprochement_annuaires_principal.csv"
    if f.exists():
        r = pd.read_csv(f, sep=";", encoding="utf-8")
        v["rapprochement"] = {"identiques": int((r["ecart"] == 0).sum()), "total": len(r)}
    fi = TRAITE / "prevision_fiabilite.csv"
    if fi.exists():
        t = pd.read_csv(fi, sep=";", encoding="utf-8")
        t = t[(t["perimetre"] == "cas_communs") & (t["groupe"] == "stable")]
        ret = t[t["retenue"]]
        if len(ret):
            m = ret["methode"].iloc[0]
            g = t[t["methode"] == m].set_index("horizon")["wape"]
            ref = t[t["methode"] == "naive"].set_index("horizon")["wape"]
            h = int(g.index.max())
            v["prevision"] = {"erreur_1an": float(g.loc[1]), "erreur_max": float(g.loc[h]), "horizon_max": h,
                              "reference_max": float(ref.loc[h])}
    sb = TRAITE / "scenarios_bilan.csv"
    if sb.exists():
        b = pd.read_csv(sb, sep=";", encoding="utf-8")
        o = b[b["methode"] == "optimisee"]
        v["scenarios"] = {"optimaux": int((o["statut_solveur"] == "Optimal").sum()), "total": len(o)}
    from dcb.lecture import nombre_de_tests
    v["tests"] = nombre_de_tests()
    return v


def _plan_reference() -> dict:
    """Résultat central affiché à l'accueil : le plan de référence de la chaîne, comparé aux règles simples."""
    b = pd.read_csv(TRAITE / "allocation_bilan.csv", sep=";", encoding="utf-8").set_index("methode")
    o = b.loc["optimisee"]
    return {"enseignants": int(o["enseignants_attribues"]), "salles": int(o["salles_attribuees"]),
            "salles_rouvertes": int(o.get("salles_rouvertes", 0) or 0),
            "pire_avant": float(b.loc["sans_moyens_nouveaux", "pire_ratio_eleves_maitre"]),
            "pire_optimisee": float(o["pire_ratio_eleves_maitre"]),
            "pire_proportionnelle": float(b.loc["proportionnelle", "pire_ratio_eleves_maitre"]),
            "pire_besoins": float(b.loc["besoins", "pire_ratio_eleves_maitre"]),
            "surnombre_optimisee": int(o["eleves_au_dela_norme_maitre"]),
            "surnombre_proportionnelle": int(b.loc["proportionnelle", "eleves_au_dela_norme_maitre"]),
            "surnombre_besoins": int(b.loc["besoins", "eleves_au_dela_norme_maitre"]),
            "surnombre_avant": int(b.loc["sans_moyens_nouveaux", "eleves_au_dela_norme_maitre"]),
            # coût du plan de référence, même règle que l'onglet Répartition (salles + salaires comptés sur annees_budget ans)
            "cout_fcfa": _cout_reference(o),
            "gini_optimisee": float(o["gini_ratio_maitre"]), "gini_besoins": float(b.loc["besoins", "gini_ratio_maitre"]),
            "gini_proportionnelle": float(b.loc["proportionnelle", "gini_ratio_maitre"]),
            "retrospectif": _retrospectif(),
            **_plus_chargee(),
            "atouts": _atouts()}


def _atouts() -> dict:
    """Là où la règle simple « au prorata des besoins » ne suffit plus : moyens serrés (budget seul) et mutations.
    Budget : scénarios précalculés de la chaîne ; mutations : même calcul que l'application (1 000 recrues, 500 salles,
    jusqu'à 1 000 mutations, contre la règle des besoins avec les mêmes recrues et salles, qui ne sait pas muter)."""
    out: dict = {}
    sb = TRAITE / "scenarios_budget.csv"
    if sb.exists():
        b = pd.read_csv(sb, sep=";", encoding="utf-8")
        b = b[b["demande"] == b["demande"].iloc[0]]
        out["budget"] = [{"budget_md": float(m) / 1e9,
                          "pire_optimisee": float(g.loc[g["methode"] == "optimisee", "pire_ratio_eleves_maitre"].iloc[0]),
                          "pire_besoins": float(g.loc[g["methode"] == "besoins", "pire_ratio_eleves_maitre"].iloc[0])}
                         for m, g in b.groupby("budget_fcfa")]
    try:
        from dcb.optimisation import comparer, donnees_probleme
        cfg = config()
        t = pd.read_csv(TRAITE / "province_annee.csv", sep=";", encoding="utf-8")
        pv = pd.read_csv(TRAITE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
        _, bil, _ = comparer(donnees_probleme(t, pv, cfg), cfg, 1000, 500, None, None, 1000)
        bil = bil.set_index("methode")
        out["mutations"] = {"recrues": 1000, "salles": 500, "mutations_max": 1000,
                            "mutes": int(bil.loc["optimisee"].get("enseignants_redeployes", 0) or 0),
                            "trop_optimisee": int(bil.loc["optimisee", "eleves_au_dela_norme_maitre"]),
                            "trop_besoins": int(bil.loc["besoins", "eleves_au_dela_norme_maitre"]),
                            "pire_optimisee": float(bil.loc["optimisee", "pire_ratio_eleves_maitre"]),
                            "pire_besoins": float(bil.loc["besoins", "pire_ratio_eleves_maitre"])}
    except Exception as e:  # noqa: BLE001 - l'export ne doit pas échouer pour un encadré
        print("atouts : calcul des mutations impossible :", e)
    return out


def _plus_chargee() -> dict:
    """La province la plus chargée avant le plan, et ce qu'elle devient selon chaque façon de répartir ;
    plus la province la plus chargée après le plan (ce n'est pas la même : l'une est servie, l'autre manque de salles)."""
    a = pd.read_csv(TRAITE / "allocation.csv", sep=";", encoding="utf-8")
    o = a[a["methode"] == "optimisee"].assign(avant=lambda x: x["eleves_horizon"] / x["maitres"].where(x["maitres"] > 0))
    p0 = o.sort_values("avant").iloc[-1]["province"]
    apres = a[a["province"] == p0].set_index("methode")["ratio_maitre_apres"]
    p1 = o.sort_values("ratio_maitre_apres").iloc[-1]
    return {"province_pire_avant": p0, "province_pire_avant_apres": {k: float(v) for k, v in apres.items()},
            "province_pire_apres": p1["province"], "province_pire_apres_ratio": float(p1["ratio_maitre_apres"])}


def _cout_reference(o) -> float:
    opt = config()["optimisation"]
    return float(o["salles_attribuees"] * opt["cout_salle_fcfa"]
                 + o["enseignants_attribues"] * opt["cout_enseignant_fcfa"] * opt.get("annees_budget", 1))


def _filles() -> pd.DataFrame:
    """Filles et garçons inscrits (public et privé) par année et province, tableaux rétrospectifs des annuaires
    (la publication la plus récente fait foi, comme pour la série des effectifs). Pas encore dans l'entrepôt."""
    f = INTERIM / "annuaires" / "historique_effectifs.csv"
    if not f.exists():
        return pd.DataFrame(columns=["annee_scolaire", "province", "filles", "garcons"])
    h = pd.read_csv(f, sep=";", encoding="utf-8")
    h = h[(h["niveau"] == "province") & h["sexe"].isin(["filles", "garcons"])].dropna(subset=["eleves"])
    h = h.sort_values("annuaire").groupby(["annee_scolaire", "province", "sexe"], as_index=False).last()
    return h.pivot_table(index=["annee_scolaire", "province"], columns="sexe", values="eleves").reset_index()


def _retrospectif() -> list[dict]:
    f = TRAITE / "retrospectif_bilan.csv"
    if not f.exists():
        return []
    b = pd.read_csv(f, sep=";", encoding="utf-8")
    o = b[b["methode"] == "optimisee"].set_index("origine")
    r = b[b["methode"] == "reelle"].set_index("origine")
    return [{"origine": k, "fin": o.loc[k, "fin"], "enseignants": int(o.loc[k, "enseignants_disponibles"]),
             "salles": int(o.loc[k, "salles_disponibles"]),
             "surnombre_reel": int(r.loc[k, "eleves_au_dela_norme_maitre"]),
             "surnombre_outil": int(o.loc[k, "eleves_au_dela_norme_maitre"]),
             "ecart": float(o.loc[k, "ecart_vs_reelle"])} for k in o.index]


def _scenarios(cfg: dict) -> dict:
    """Effet des deux scénarios d'effectifs à l'horizon (public et privé), pour l'aide de l'onglet Répartition."""
    pv = pd.read_csv(TRAITE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    h = pv[pv["annee_scolaire"] == cfg["annee_horizon"]].pivot_table(index="province", columns="scenario", values="eleves_prevus")
    pr = cfg["prevision"]
    return {"eleves_tendance": int(h["tendance"].sum()), "eleves_reouverture": int(h["reouverture"].sum()),
            "provinces_choc": int(pv.loc[pv["groupe"] == "choc", "province"].nunique()),
            "rattrapage": pr["part_rattrapage_reouverture"], "choc_seuil": pr["choc_seuil_baisse"], "choc_depuis": pr["choc_depuis"]}


def ecoles() -> list:
    """Écoles repérées sur OpenStreetMap (sites regroupés à 150 m) : commune, nom, position, nombre d'objets.
    Liste partielle (environ un tiers des écoles de l'annuaire) ; sert aux extractions des fiches."""
    f = RACINE / "data" / "interim" / "ecoles_osm_sites.csv"
    if not f.exists():
        return []
    e = pd.read_csv(f, sep=";", encoding="utf-8")
    return [[r.pcode_commune if isinstance(r.pcode_commune, str) else None, r.nom if isinstance(r.nom, str) else None,
             round(float(r.lat), 5), round(float(r.lon), 5), int(r.objets)] for r in e.itertuples()]


def annees() -> dict:
    """Chiffres observés par année, province et statut (public, privé, total) : sélecteur d'année et comparaison
    public / privé de la carte. Valeurs brutes des annuaires, sans calcul de l'outil."""
    t = pd.read_csv(TRAITE / "province_annee.csv", sep=";", encoding="utf-8")
    cols = {"eleves": "e", "maitres": "m", "salles": "s", "ecoles": "ec", "part_salles_precaires": "prec"}
    out: dict = {}
    fg = _filles().set_index(["annee_scolaire", "province"])
    for (an, prov), g in t.groupby(["annee_scolaire", "province"]):
        d = {}
        for _, r in g.iterrows():
            d[{"public": "pu", "prive": "pr", "total": "t"}[r["statut"]]] = {
                c: (None if pd.isna(r[k]) else round(float(r[k]), 4) if k.startswith("part") else int(r[k])) for k, c in cols.items()}
        if (an, prov) in fg.index and "t" in d:
            d["t"]["f"], d["t"]["g"] = int(fg.loc[(an, prov), "filles"]), int(fg.loc[(an, prov), "garcons"])
        out.setdefault(an, {})[prov] = d
    return {"annees": sorted(out), "valeurs": out}


def _prive(annee: str) -> dict:
    """Part du privé dans les élèves du primaire, l'année de référence : les aides de l'interface la lisent ici."""
    t = pd.read_csv(TRAITE / "province_annee.csv", sep=";", encoding="utf-8")
    a = t[t["annee_scolaire"] == annee].pivot_table(index="province", columns="statut", values="eleves", aggfunc="sum")
    s = (a["prive"].fillna(0) / a["total"]).dropna()
    return {"part": round(float(a["prive"].sum() / a["total"].sum()), 4),
            "province_max": str(s.idxmax()), "part_max": round(float(s.max()), 4),
            "provinces_sans": sorted(str(p) for p in s[s <= 0].index)}


def generer() -> None:
    cfg = config()
    contours()
    _ecrire("provinces.json", provinces(cfg))
    _ecrire("provinces_annees.json", annees())
    _ecrire("ecoles.json", ecoles())
    cs = pd.read_csv(TRAITE / "carte_scolaire_commune.csv", sep=";", encoding="utf-8")
    f_acces, f_sites = TRAITE / "acces_ecole_commune.csv", TRAITE / "sites_proposes.csv"
    if f_acces.exists() and f_sites.exists():
        ac = pd.read_csv(f_acces, sep=";", encoding="utf-8")
        sp = pd.read_csv(f_sites, sep=";", encoding="utf-8")
    else:  # étape d'implantation sautée (grilles WorldPop absentes) : l'application s'ouvre sans l'accès à l'école
        print("accès à l'école et sites absents : l'application sera publiée sans ces couches")
        ac = pd.DataFrame(columns=["pcode_commune", "commune", "province", "region", "enfants", "eloignes_borne_haute",
                                   "eloignes_borne_basse", "part_eloignes_haute", "part_eloignes_basse"])
        sp = pd.DataFrame(columns=["rang", "lon", "lat", "pcode_commune", "enfants_rapproches", "commune", "province",
                                   "region", "part_ecoles_fermees_province", "recommandation"])
    cs = cs.merge(ac.drop(columns=["commune", "province", "region", "enfants"], errors="ignore"), on="pcode_commune", how="left")
    _ecrire("communes.json", _lignes(cs))
    _ecrire("sites.json", _lignes(sp))
    h = int(cfg["annee_horizon"][:4])
    _ecrire("meta.json", {
        "annee_reference": cfg["annee_reference"], "annee_horizon": cfg["annee_horizon"], "normes": cfg["normes"],
        "couts": {"salle": cfg["optimisation"]["cout_salle_fcfa"], "enseignant": cfg["optimisation"]["cout_enseignant_fcfa"],
                  "salle_complexe": cfg["optimisation"].get("cout_salle_complexe_fcfa"),
                  "annees_budget": cfg["optimisation"].get("annees_budget", 1)},
        "defauts": {"enseignants": cfg["optimisation"]["enseignants_a_repartir"], "salles": cfg["optimisation"]["salles_a_construire"]},
        "implantation": cfg["implantation"],
        "national": {"enfants_6_11_horizon": int(cs[f"enfants_6_11_{h}"].sum()), "communes": len(cs),
                     "eloignes_basse": int(ac["eloignes_borne_basse"].sum()), "eloignes_haute": int(ac["eloignes_borne_haute"].sum()),
                     "sites": len(sp), "sites_construire": int((sp["recommandation"] == "construire").sum()),
                     "pdi": int(cs["pdi_total"].sum()), "communes_pdi_relevees": int(cs["pdi_releve"].sum())},
        "plan_reference": _plan_reference(),
        "prive": _prive(cfg["annee_reference"]),
        "scenarios": _scenarios(cfg),
        "indice": {"ponderations": cfg["indice"]["ponderations"], "dimensions": cfg["indice"]["dimensions"],
                   "plage_surcharge": cfg["indice"]["robustesse"]["plage_poids_premiere_dimension"],
                   "seuil_changement_tiers": cfg["indice"]["robustesse"]["seuil_changement_tiers"],
                   "tirages": cfg["indice"]["tirages_robustesse"]},
        "noms": territoire.noms_officiels(),
        "validation": _validation(),
    })
    tailles = {f.name: f"{f.stat().st_size / 1024:.0f} ko" for f in sorted(WEB.glob("*.json"))}
    print("outputs/web :", tailles)


if __name__ == "__main__":
    generer()
