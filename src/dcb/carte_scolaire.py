"""Carte scolaire à la commune : demande d'école en 2030, écoles repérées, déplacés accueillis.

Pour chaque commune (code P du référentiel, découpage de 2025) :
- enfants de 6 à 11 ans en 2019 (recensement, fichier des localités) et projetés à la rentrée de l'horizon :
  part de la commune dans sa province en 2019 x projection INSD de la province (méthode des « poids relatifs »
  que l'INSD applique lui-même entre régions et provinces) ;
- sites scolaires repérés dans OpenStreetMap (bâtiments d'une même école regroupés), ce qui n'est PAS la liste
  officielle des écoles : la couverture d'OSM est partielle et inégale, l'indicateur sert à repérer, pas à conclure ;
- personnes déplacées internes accueillies (CONASUR, dernier relevé par commune publié).

Les données passent par l'entrepôt (population_commune, deplaces_commune) : une mise à jour par un technicien
est prise en compte sans toucher au code.

Usage : PYTHONPATH=src python -m dcb.carte_scolaire   (après dcb.entrepot amorcer)
Produit data/processed/carte_scolaire_commune.csv et data/interim/ecoles_osm_sites.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dcb import geo, territoire
from dcb.indicateurs import SORTIE, config
from dcb.lecture import CSV, DATAPACK, RACINE

OSM = DATAPACK / "04_Cartographie_SIG" / "Ecoles_OSM_HOTOSM" / "hotosm_bfa_education_facilities_osm_gpkg.zip"
LIMITES = DATAPACK / "04_Cartographie_SIG" / "COD-AB_limites_administratives" / "bfa_admin_boundaries.geojson.zip"
PDI = CSV / "03_Conditions_de_Vie_et_Emploi" / "PDI_CONASUR" / "situation-des-pdi-par-communes-accueil-du-31-decembre-2022-1__31122022.csv"
PROJECTIONS = RACINE / "data" / "interim" / "demographie" / "population_6_11_province.csv"
SITES = RACINE / "data" / "interim" / "ecoles_osm_sites.csv"
EXCLUS = {"university", "kindergarten", "drinking_water", "college"}  # hors primaire (le collège est post-primaire)
UTM = "EPSG:32630"  # projection métrique adaptée au Burkina Faso


def contours_communes():
    import geopandas as gpd
    g = gpd.read_file(f"zip://{LIMITES.as_posix()}!bfa_admin3.geojson")
    return g[["adm3_pcode", "geometry"]].rename(columns={"adm3_pcode": "pcode_commune"})


def sites_osm(rayon_m: float = 150) -> pd.DataFrame:
    """Sites scolaires OSM : les objets (bâtiments, enceintes, points) distants de moins de `rayon_m` sont une même école."""
    import geopandas as gpd
    g = gpd.read_file(f"zip://{OSM.as_posix()}!education_facilities.gpkg")
    g = g[~g["amenity"].isin(EXCLUS) & ~g["building"].isin({"university", "kindergarten"})]
    pts = g.geometry.representative_point()
    # regroupement en mètres (UTM 30 N) : union des disques de rayon/2 autour de chaque objet, une composante = un site
    pm = pts.to_crs(UTM)
    union = pm.buffer(rayon_m / 2).union_all()
    composantes = gpd.GeoSeries(list(union.geoms) if hasattr(union, "geoms") else [union], crs=UTM)
    idx = gpd.GeoDataFrame(geometry=pm, crs=UTM).sjoin(gpd.GeoDataFrame(geometry=composantes, crs=UTM), predicate="within")
    g = g.assign(site=idx["index_right"].reindex(g.index).values)
    nomme = g["name"].notna()
    s = g.assign(x=pts.x, y=pts.y, nomme=nomme).groupby("site").agg(
        lon=("x", "mean"), lat=("y", "mean"), objets=("x", "size"), nom=("name", "first"), nomme=("nomme", "any"))
    s = gpd.GeoDataFrame(s.reset_index(), geometry=gpd.points_from_xy(s["lon"], s["lat"]), crs=g.crs)
    s = s.sjoin(contours_communes(), predicate="within", how="left").drop(columns=["index_right"])
    return pd.DataFrame(s.drop(columns="geometry"))


def deplaces_conasur(ref: territoire.Referentiel | None = None) -> pd.DataFrame:
    """Déplacés par commune d'accueil (CONASUR, 31 décembre 2022), au format de l'entrepôt (code P de 2025)."""
    from dcb.lecture import lire_csv
    from dcb.population_communes import rattacher

    ref = ref or territoire.charger()
    t = lire_csv(PDI)
    entete = t.index[t["col1"].astype(str).str.strip() == "Country"][0]
    t = t.iloc[entete + 2:]
    t = t[t["col1"].astype(str).str.strip() == "Burkina Faso"]
    nombre = lambda c: pd.to_numeric(t[c].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce")
    d = pd.DataFrame({"province": t["col3"].map(geo.province), "commune_source": t["col4"].astype(str).str.strip(),
                      "pdi_total": nombre("col10"), "pdi_enfants": nombre("col9"), "pdi_enfants_plus_5": nombre("col8")})
    if d["province"].isna().any():
        raise ValueError(f"provinces non reconnues : {t.loc[d['province'].isna().values, 'col3'].unique()}")
    d = rattacher(d, ref)
    if d["pcode_commune"].isna().any():
        raise ValueError(f"communes non rattachées : {d.loc[d['pcode_commune'].isna(), ['province', 'commune_source']].values.tolist()}")
    d = d.groupby("pcode_commune", as_index=False)[["pdi_total", "pdi_enfants", "pdi_enfants_plus_5"]].sum()
    return d.rename(columns={"pcode_commune": "code_territoire"}).assign(annee_scolaire="2022-2023")


def projection_6_11(pop: pd.DataFrame, ref: territoire.Referentiel, annee: int) -> pd.Series:
    """Enfants de 6 à 11 ans d'une commune à une année : part dans sa province (2019) x projection INSD de la province."""
    p = pd.read_csv(PROJECTIONS, sep=";", encoding="utf-8")
    p = p[(p["niveau"] == "province") & (p["annee"] == annee)].set_index("entite")["population_6_11"]
    anc = ref.decoupage("annuaires_2017_2025").set_index("pcode_commune")["province"]
    prov = pop["code_territoire"].map(anc)
    part = pop["age_6_11"] / pop.groupby(prov)["age_6_11"].transform("sum")
    return (part * prov.map(p)).round()


def carte(cfg: dict | None = None) -> pd.DataFrame:
    from dcb import entrepot
    cfg = cfg or config()
    ref = territoire.charger()
    horizon = int(cfg["annee_horizon"][:4])
    pop = entrepot.lire("population_commune", ref=ref)
    pdi = entrepot.lire("deplaces_commune", ref=ref)
    sites = sites_osm()
    sites.to_csv(SITES, index=False, sep=";", encoding="utf-8")
    nb_sites = sites.groupby("pcode_commune").size()
    c = (ref.decoupage("reforme_2025").merge(ref.communes, on="pcode_commune")
         .merge(ref.decoupage("annuaires_2017_2025")[["pcode_commune", "province", "region"]], on="pcode_commune",
                suffixes=("", "_ancienne")))
    pop = pop.set_index("code_territoire")
    c["population_2019"] = c["pcode_commune"].map(pop["population"])
    c["enfants_6_11_2019"] = c["pcode_commune"].map(pop["age_6_11"])
    c[f"enfants_6_11_{horizon}"] = c["pcode_commune"].map(
        projection_6_11(pop.reset_index(), ref, horizon).set_axis(pop.index))
    c["sites_scolaires_osm"] = c["pcode_commune"].map(nb_sites).fillna(0).astype(int)
    c["enfants_par_site_osm"] = (c[f"enfants_6_11_{horizon}"] / c["sites_scolaires_osm"]).where(c["sites_scolaires_osm"] > 0)
    c["enfants_6_11_par_km2"] = c[f"enfants_6_11_{horizon}"] / c["superficie_km2"]
    p = pdi.set_index("code_territoire")
    # une commune absente du relevé du CONASUR est « non relevée » (valeur vide), pas « zéro déplacé »
    c["pdi_releve"] = c["pcode_commune"].isin(p.index)
    c["pdi_total"] = c["pcode_commune"].map(p["pdi_total"])
    c["pdi_enfants_plus_5"] = c["pcode_commune"].map(p["pdi_enfants_plus_5"])
    c["part_pdi_population"] = c["pdi_total"] / c["population_2019"]
    est = pd.read_csv(RACINE / "data" / "interim" / "demographie" / "population_commune_2019.csv", sep=";",
                      encoding="utf-8").set_index("pcode_commune")["estimation_insd"]
    c["population_estimee_insd"] = c["pcode_commune"].map(est).fillna("")
    cols = ["pcode_commune", "commune", "province", "region", "province_ancienne", "region_ancienne", "lat", "lon",
            "superficie_km2", "population_2019", "enfants_6_11_2019", f"enfants_6_11_{horizon}", "sites_scolaires_osm",
            "enfants_par_site_osm", "enfants_6_11_par_km2", "pdi_releve", "pdi_total", "pdi_enfants_plus_5", "part_pdi_population",
            "population_estimee_insd"]
    return c[cols].sort_values(["region", "province", "commune"]).reset_index(drop=True)


if __name__ == "__main__":
    cfg = config()
    h = int(cfg["annee_horizon"][:4])
    c = carte(cfg)
    c.to_csv(SORTIE / "carte_scolaire_commune.csv", index=False, sep=";", encoding="utf-8")
    print(f"{len(c)} communes -> data/processed/carte_scolaire_commune.csv")
    print(f"enfants de 6 à 11 ans : {c['enfants_6_11_2019'].sum():,.0f} en 2019, {c[f'enfants_6_11_{h}'].sum():,.0f} en {h}")
    print(f"sites scolaires OSM : {c['sites_scolaires_osm'].sum()} ; communes sans aucun site OSM : {(c['sites_scolaires_osm'] == 0).sum()}")
    print(f"déplacés accueillis : {c['pdi_total'].sum():,.0f} dans {int(c['pdi_releve'].sum())} communes relevées "
          f"({int((~c['pdi_releve']).sum())} non relevées) ; communes où ils dépassent 20 % de la population : "
          f"{(c['part_pdi_population'] > 0.2).sum()}")
    print(c.sort_values(f"enfants_6_11_{h}", ascending=False)[["commune", "province", f"enfants_6_11_{h}", "sites_scolaires_osm", "pdi_total"]].head(8).to_string(index=False))
    print(c.sort_values("part_pdi_population", ascending=False)[["commune", "province", "population_2019", "pdi_total", "part_pdi_population"]].head(8).round(2).to_string(index=False))
