"""Accès à l'école et sites où construire : à quelle distance les enfants vivent-ils d'une école, et où en ouvrir ?

1. Où vivent les enfants : grille de 100 m de WorldPop (2030, R2025A, population « contrainte » aux zones bâties),
   tranches 5-9 et 10-14 ans ramenées à 6-11 ans (4/5 de la première, 2/5 de la seconde, âges supposés également
   répartis dans chaque tranche), puis CALÉE commune par commune sur la projection INSD (carte_scolaire) :
   WorldPop ne sert qu'à répartir les enfants à l'intérieur d'une commune, les totaux restent ceux de l'INSD.
2. Distance à l'école, encadrée par deux estimations, car OSM ne recense qu'une partie des écoles (environ un tiers) :
   - borne haute : distance au site scolaire OSM le plus proche (surestime l'éloignement : écoles non cartographiées) ;
   - borne basse : on ajoute, dans chaque province, autant d'« écoles présumées » qu'il manque d'écoles à OSM par
     rapport à l'annuaire (nombre officiel d'écoles de la province), placées là où elles rapprochent le plus
     d'enfants. Hypothèse favorable (les écoles existantes sont au meilleur endroit) : l'éloignement réel est
     au moins celui-là.
   L'éloignement réel se situe entre les deux. Les deux deviennent exacts quand la liste officielle des écoles
   géolocalisées est chargée.
3. Où construire : couverture maximale gloutonne, sur la borne basse (seuls les enfants éloignés même dans
   l'hypothèse favorable comptent : un site proposé l'est donc avec prudence). On choisit le site (maille de 1 km)
   qui rapproche le plus d'enfants encore éloignés à moins de `rayon_km`, puis on recommence, jusqu'au nombre de sites demandé ou jusqu'à
   ce qu'aucun site n'atteigne `seuil_enfants_site`. Les provinces où la construction n'est pas programmée
   (même règle que la répartition) sont exclues.
4. Construire ou rouvrir ? L'annuaire ne compte que les écoles ouvertes : une zone dont les écoles ont fermé pour
   raison de sécurité ressort comme « à construire ». Chaque site porte donc la part d'écoles fermées de sa province
   (baisse du nombre d'écoles ouvertes depuis son maximum 2017-2025, annuaires) ; au-delà de
   `seuil_fermeture_rouvrir`, la recommandation est de rouvrir ou délocaliser avant de construire. (Les rapports
   mensuels ESU donnent les fermetures par province, mais leurs tableaux, lus par reconnaissance de caractères,
   ne sont pas exploitables de façon fiable.) L'algorithme glouton garantit au moins 63 % (1 - 1/e) de la
   couverture optimale ; en pratique il en est très proche.

Usage : PYTHONPATH=src python -m dcb.implantation   (après dcb.carte_scolaire)
Produit data/processed/acces_ecole_commune.csv et data/processed/sites_proposes.csv
"""
from __future__ import annotations

import heapq

import numpy as np
import pandas as pd

from dcb import territoire
from dcb.indicateurs import SORTIE, config
from dcb.lecture import RACINE

WORLDPOP = RACINE / "data" / "external" / "worldpop"
KM_PAR_DEGRE = 111.32


def _xy_km(lon, lat, lat0: float = 12.3):
    """Coordonnées planes approchées en km (projection équirectangulaire, erreur < 1 % sur le pays)."""
    return np.column_stack([np.asarray(lon) * KM_PAR_DEGRE * np.cos(np.radians(lat0)), np.asarray(lat) * KM_PAR_DEGRE])


def enfants_grille(annee: int, carte: pd.DataFrame) -> pd.DataFrame:
    """Enfants de 6 à 11 ans par maille de 100 m habitée, calés sur la carte scolaire commune par commune."""
    import rasterio
    from rasterio import features

    from dcb.carte_scolaire import contours_communes

    f5 = WORLDPOP / f"bfa_t_05_{annee}_CN_100m_R2025A_v1.tif"
    f10 = WORLDPOP / f"bfa_t_10_{annee}_CN_100m_R2025A_v1.tif"
    with rasterio.open(f5) as r5, rasterio.open(f10) as r10:
        a5 = r5.read(1)
        a10 = r10.read(1)
        transform, shape = r5.transform, r5.shape
    a5[a5 < 0] = 0
    a10[a10 < 0] = 0
    v = 0.8 * a5 + 0.4 * a10
    del a5, a10
    g = contours_communes().reset_index(drop=True)
    ident = features.rasterize(((geom, i + 1) for i, geom in enumerate(g.geometry)), out_shape=shape,
                               transform=transform, fill=0, dtype="int32")
    lig, col = np.nonzero((v > 0) & (ident > 0))
    lon, lat = rasterio.transform.xy(transform, lig, col)
    d = pd.DataFrame({"lon": lon, "lat": lat, "brut": v[lig, col],
                      "pcode_commune": g["pcode_commune"].to_numpy()[ident[lig, col] - 1]})
    cible = carte.set_index("pcode_commune")[f"enfants_6_11_{annee}"]
    somme = d.groupby("pcode_commune")["brut"].transform("sum")
    d["enfants"] = d["brut"] * d["pcode_commune"].map(cible) / somme
    return d.drop(columns="brut")


def distance_ecole(d: pd.DataFrame, sites: pd.DataFrame) -> np.ndarray:
    from scipy.spatial import cKDTree
    arbre = cKDTree(_xy_km(sites["lon"], sites["lat"]))
    dist, _ = arbre.query(_xy_km(d["lon"], d["lat"]))
    return dist


def sites_a_construire(d: pd.DataFrame, rayon_km: float, seuil: float, nombre_max: int,
                       communes_exclues: set[str], distance: str = "distance_km") -> pd.DataFrame:
    """Couverture maximale gloutonne (paresseuse) sur une maille de 1 km des enfants encore éloignés."""
    from scipy.spatial import cKDTree

    e = d[(d[distance] > rayon_km) & ~d["pcode_commune"].isin(communes_exclues)]
    e = e[["lon", "lat", "enfants", "pcode_commune"]].copy()
    xy = _xy_km(e["lon"], e["lat"])
    e["ix"], e["iy"] = np.floor(xy[:, 0]).astype(int), np.floor(xy[:, 1]).astype(int)
    m = e.groupby(["ix", "iy"]).agg(enfants=("enfants", "sum"), lon=("lon", "mean"), lat=("lat", "mean"),
                                    pcode_commune=("pcode_commune", lambda s: s.value_counts().index[0])).reset_index()
    if m.empty:
        return pd.DataFrame()
    pts = _xy_km(m["lon"], m["lat"])
    arbre = cKDTree(pts)
    voisins = arbre.query_ball_point(pts, r=rayon_km)
    reste = m["enfants"].to_numpy().copy()
    tas = [(-reste[v].sum(), i) for i, v in enumerate(map(np.asarray, voisins))]
    heapq.heapify(tas)
    choisis = []
    while tas and len(choisis) < nombre_max:
        moins_gain, i = heapq.heappop(tas)
        gain = reste[voisins[i]].sum()
        if gain < seuil:
            if -moins_gain < seuil:
                break
            continue
        if tas and gain < -tas[0][0] - 1e-9:  # gain périmé : on le remet à jour (glouton paresseux)
            heapq.heappush(tas, (-gain, i))
            continue
        choisis.append({"rang": len(choisis) + 1, "lon": round(m.at[i, "lon"], 5), "lat": round(m.at[i, "lat"], 5),
                        "pcode_commune": m.at[i, "pcode_commune"], "enfants_rapproches": round(gain)})
        reste[voisins[i]] = 0
    return pd.DataFrame(choisis)


def implantation(cfg: dict | None = None):
    from dcb.carte_scolaire import SITES

    cfg = cfg or config()
    p = cfg["implantation"]
    annee = int(cfg["annee_horizon"][:4])
    carte = pd.read_csv(SORTIE / "carte_scolaire_commune.csv", sep=";", encoding="utf-8")
    sites = pd.read_csv(SITES, sep=";", encoding="utf-8")
    d = enfants_grille(annee, carte)
    d["distance_km"] = distance_ecole(d, sites)
    r = p["rayon_km"]
    ref = territoire.charger()
    anc = ref.decoupage("annuaires_2017_2025").set_index("pcode_commune")["province"]
    table = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    # écoles présumées : écoles de l'annuaire absentes d'OSM, placées au mieux dans leur province
    off = table[(table["annee_scolaire"] == cfg["annee_reference"]) & (table["statut"] == "total")].set_index("province")["ecoles"]
    osm = sites["pcode_commune"].map(anc).value_counts()
    manque = (off - osm.reindex(off.index).fillna(0)).clip(lower=0).astype(int)
    d["province_ancienne"] = d["pcode_commune"].map(anc)
    presumees = []
    for prov, n in manque.items():
        if n > 0:
            sp = sites_a_construire(d[d["province_ancienne"] == prov], r, 1, n, set())
            if not sp.empty:
                presumees.append(sp.assign(province_ancienne=prov))
    presumees = pd.concat(presumees, ignore_index=True)
    d["distance_km_basse"] = distance_ecole(d, pd.concat([sites[["lon", "lat"]], presumees[["lon", "lat"]]]))
    w = d["enfants"]
    acces = pd.DataFrame({
        "enfants": w.groupby(d["pcode_commune"]).sum(),
        "eloignes_borne_haute": w.where(d["distance_km"] > r, 0).groupby(d["pcode_commune"]).sum(),
        "eloignes_borne_basse": w.where(d["distance_km_basse"] > r, 0).groupby(d["pcode_commune"]).sum(),
    }).reset_index()
    acces["part_eloignes_haute"] = acces["eloignes_borne_haute"] / acces["enfants"]
    acces["part_eloignes_basse"] = acces["eloignes_borne_basse"] / acces["enfants"]
    # exclusions : provinces où la construction n'est pas programmée (règle de la répartition)
    from dcb.optimisation import donnees_probleme
    prevision = pd.read_csv(SORTIE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    dp = donnees_probleme(table, prevision, cfg)
    # seul l'accès exclut un site : là où il faut rouvrir, le site est proposé avec la recommandation « rouvrir »
    exclues_prov = set(dp.loc[~dp["acces_construction"], "province"])
    communes_exclues = set(anc.index[anc.isin(exclues_prov)])
    s = sites_a_construire(d, r, p["seuil_enfants_site"], p["nombre_sites_max"], communes_exclues, "distance_km_basse")
    noms = carte.set_index("pcode_commune")[["commune", "province", "region"]]
    tot = table[table["statut"] == "total"]
    ferme = 1 - tot[tot["annee_scolaire"] == cfg["annee_reference"]].set_index("province")["ecoles"] / tot.groupby("province")["ecoles"].max()
    if not s.empty:
        s = s.join(noms, on="pcode_commune")
        s["part_ecoles_fermees_province"] = s["pcode_commune"].map(anc).map(ferme).round(3)
        s["recommandation"] = np.where(s["part_ecoles_fermees_province"] > p["seuil_fermeture_rouvrir"],
                                       "rouvrir ou délocaliser d'abord", "construire")
    acces = acces.join(noms, on="pcode_commune")
    acces["part_ecoles_fermees_province"] = acces["pcode_commune"].map(anc).map(ferme).round(3)
    acces["construction_programmee"] = ~acces["pcode_commune"].isin(communes_exclues)
    return d, acces, s, exclues_prov, presumees


if __name__ == "__main__":
    cfg = config()
    p = cfg["implantation"]
    annee = int(cfg["annee_horizon"][:4])
    if not (WORLDPOP / f"bfa_t_05_{annee}_CN_100m_R2025A_v1.tif").exists():
        raise SystemExit(f"grilles WorldPop {annee} absentes de {WORLDPOP} : étape sautée (voir data/external/SOURCES.md)")
    d, acces, s, exclues, presumees = implantation(cfg)
    presumees.to_csv(RACINE / "data" / "interim" / "ecoles_presumees.csv", index=False, sep=";", encoding="utf-8")
    acces.to_csv(SORTIE / "acces_ecole_commune.csv", index=False, sep=";", encoding="utf-8")
    s.to_csv(SORTIE / "sites_proposes.csv", index=False, sep=";", encoding="utf-8")
    tot = acces["enfants"].sum()
    h, b = acces["eloignes_borne_haute"].sum(), acces["eloignes_borne_basse"].sum()
    print(f"{len(d):,} mailles habitées ; enfants de 6-11 ans calés : {tot:,.0f} ; écoles présumées ajoutées : {len(presumees)}")
    print(f"enfants à plus de {p['rayon_km']} km d'une école : entre {b:,.0f} ({b / tot:.1%}) et {h:,.0f} ({h / tot:.1%})")
    print(f"provinces exclues de la construction : {sorted(exclues)}")
    if not s.empty:
        print(f"{len(s)} sites proposés (seuil {p['seuil_enfants_site']} enfants) ; enfants rapprochés : {s['enfants_rapproches'].sum():,.0f}")
        print(s["recommandation"].value_counts().to_string())
        print(s.head(12).to_string(index=False))
