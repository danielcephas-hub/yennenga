"""Population de 6 à 11 ans projetée par province, 2020 à 2035 (INSD, projections issues du RGPH 2019).

Dans le document, chaque province occupe plusieurs pages ; chaque bloc donne trois années, avec pour chacune
Homme, Femme, Ensemble. On lit la ligne « 6-11 ans » et on garde la colonne Ensemble.

Usage : PYTHONPATH=src python -m dcb.demographie
Produit data/interim/demographie/population_6_11_province.csv
"""
from __future__ import annotations

import re

import pandas as pd

from dcb import geo
from dcb.lecture import CSV, RACINE, cellules, lire_csv, nombre

SOURCES = [
    CSV / "02_Demographie_INSD" / "RGPH2019_NADA" / "NADA276_RGPH2019_Projections_2020-2035.csv",
    CSV / "02_Demographie_INSD" / "INSD_RGPH2019_Vol4_Projections_demographiques_2020-2035.csv",
]
SORTIE = RACINE / "data" / "interim" / "demographie"
_TRANCHE = re.compile(r"^6\s*[-–à]\s*11\s*ans$", re.I)
_AN = re.compile(r"^(20[2-3]\d)$")


def extraire(chemin) -> tuple[pd.DataFrame, list[str]]:
    df = lire_csv(chemin)
    cs = cellules(df)
    lignes, inconnus = [], []
    entite, annees, page_entite = None, [], None
    for _, r in df.sort_values(["page", "ligne"]).iterrows():
        v = [x.strip() for x in r[cs] if x.strip()]
        if not v:
            continue
        if len(v) == 1 and r["ligne"] <= 2 and not _AN.match(v[0]):
            entite, page_entite = v[0], int(r["page"])  # titre de page : nom de la province, de la région ou du pays
            continue
        an = [x for x in v if _AN.match(x)]
        if an and len(an) >= len(v) - 1:
            annees = [int(a) for a in an]
            continue
        if _TRANCHE.match(v[0]):
            vals = [nombre(x) for x in v[1:]]
            if not annees or len(vals) != 3 * len(annees) or any(x is None for x in vals):
                inconnus.append(f"p.{r['page']} l.{r['ligne']} : {len(vals)} valeurs pour les années {annees}")
                continue
            if entite is None or page_entite is None or r["page"] - page_entite > 8:
                inconnus.append(f"p.{r['page']} l.{r['ligne']} : entité inconnue")
                continue
            prov, reg = geo.province(entite), geo.region(entite)
            niveau = "province" if prov else "region" if reg else "autre"
            for i, a in enumerate(annees):
                lignes.append({"niveau": niveau, "entite": prov or reg or entite, "annee": a,
                               "garcons": vals[3 * i], "filles": vals[3 * i + 1], "population_6_11": vals[3 * i + 2],
                               "source": chemin.name[:7], "page_pdf": int(r["page"])})
            annees = []  # un en-tête d'années ne sert qu'à un bloc
    return pd.DataFrame(lignes), inconnus


def population_6_11() -> pd.DataFrame:
    tout = []
    for f in SOURCES:
        t, inconnus = extraire(f)
        print(f"{f.name[:40]} : {len(t)} valeurs, {t[t['niveau'] == 'province']['entite'].nunique() if len(t) else 0} provinces, "
              f"{len(inconnus)} ligne(s) non lue(s)")
        for x in inconnus[:5]:
            print("   ", x)
        tout.append(t)
    t = pd.concat(tout, ignore_index=True)
    return t.drop_duplicates(["niveau", "entite", "annee"]).sort_values(["niveau", "entite", "annee"]).reset_index(drop=True)


if __name__ == "__main__":
    t = population_6_11()
    SORTIE.mkdir(parents=True, exist_ok=True)
    t.to_csv(SORTIE / "population_6_11_province.csv", index=False, sep=";", encoding="utf-8")
    p = t[t["niveau"] == "province"]
    couverture = p.groupby("entite")["annee"].nunique()
    print(f"\nProvinces : {couverture.size} sur {len(geo.PROVINCES)} ; complètes (16 années) : {(couverture == 16).sum()}")
    print("Manquantes :", sorted(set(geo.PROVINCES) - set(couverture.index)))
    print("Incomplètes :", couverture[couverture < 16].to_dict())
    print("Autres entités :", sorted(t[t['niveau'] != 'province']['entite'].unique())[:30])
    print("garçons + filles = ensemble :", int((p["garcons"] + p["filles"] == p["population_6_11"]).sum()), "sur", len(p))
