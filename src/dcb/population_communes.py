"""Population par commune (RGPH 2019), dont les enfants de 6 à 11 ans et de 12 à 14 ans.

Source : INSD, Fichier des localités du 5e RGPH (juin 2022), Data Pack, tableau « population résidente par sexe et
groupe d'âge selon la région, la province, la commune… ». Une ligne « COMMUNE : X » par commune, parfois scindée
en parties rurale et urbaine. Les communes marquées * (non recensées) et ** (partiellement recensées) ont des
effectifs estimés par l'INSD : elles sont signalées (colonne `estimation_insd`).

Sert à deux choses : répartir une valeur provinciale entre communes (poids), et mesurer la demande scolaire
à la commune.

Usage : PYTHONPATH=src python -m dcb.population_communes
Produit data/interim/demographie/population_commune_2019.csv
"""
from __future__ import annotations

import difflib
import re

import pandas as pd

from dcb import geo, territoire
from dcb.lecture import CSV, RACINE, lire_csv

SOURCE = CSV / "02_Demographie_INSD" / "RGPH2019_NADA" / "NADA270_RGPH2019_Fichier_des_localites.csv"
SORTIE = RACINE / "data" / "interim" / "demographie" / "population_commune_2019.csv"
# colonnes du tableau : nom, hommes, femmes, ensemble, âges 0 à 5 (un par colonne), 6-11, 12-14, …
COLS = {"c4": "population", "c11": "age_6_11", "c12": "age_12_14"}
# noms du fichier des localités -> nom de la commune dans le référentiel (même province), quand ils diffèrent trop
ALIAS: dict[str, str] = {"FADA": "Fada N'Gourma"}  # CONASUR abrège Fada N'Gourma
# les deux grandes villes sont détaillées par arrondissement, sans ligne « COMMUNE »
VILLES_A_ARRONDISSEMENTS = {"KADIOGO": "OUAGADOUGOU", "HOUET": "BOBO-DIOULASSO"}
SIMILARITE_MIN = 0.6  # rapprochement des noms écrits différemment (Sabsé / SABCE), contrôlé à la main ci-dessous


def _nombre(x) -> float:
    s = re.sub(r"[^\d]", "", str(x))
    return float(s) if s else float("nan")


def lire() -> pd.DataFrame:
    t = lire_csv(SOURCE)
    lignes, province, toutes = [], None, []
    for _, r in t.iterrows():
        c1 = str(r["c1"]).strip().strip('"').strip()
        if c1.startswith("PROVINCE") and ":" in c1 and "..." not in c1:
            province = geo.province(c1.split(":", 1)[1])
            continue
        if province in VILLES_A_ARRONDISSEMENTS and re.match(r"ARRONDISSEMENT\s+\d+$", c1) and r["nb_cellules"] == 20:
            lignes.append({"province": province, "commune_source": VILLES_A_ARRONDISSEMENTS[province], "etoiles": "",
                           "partie": "arrondissement", **{v: _nombre(r[k]) for k, v in COLS.items()}})
            continue
        if r["nb_cellules"] == 20:
            toutes.append({"province": province, "commune_source": c1.rstrip("*").strip(), "etoiles": "", "partie": "ligne",
                           **{v: _nombre(r[k]) for k, v in COLS.items()}})
        m = re.match(r"COMMUNE\s*:\s*(.+?)\s*(\*{0,2})\s*(?:-\s*(RURAL|URBAIN|Rural|Urbain))?\s*$", c1)
        if not m or r["nb_cellules"] != 20:
            continue
        lignes.append({"province": province, "commune_source": m.group(1).strip(), "etoiles": m.group(2),
                       "partie": (m.group(3) or "total").lower(),
                       **{v: _nombre(r[k]) for k, v in COLS.items()}})
    d = pd.DataFrame(lignes)
    # une commune : sa ligne totale si elle existe, sinon la somme de ses parties rurale et urbaine
    tot = d[d["partie"] == "total"]
    parts = d[d["partie"] != "total"]
    parts = parts[~parts.set_index(["province", "commune_source"]).index.isin(tot.set_index(["province", "commune_source"]).index)]
    parts = parts.groupby(["province", "commune_source"], as_index=False).agg(
        {"etoiles": "max", **{v: "sum" for v in COLS.values()}})
    d = pd.concat([tot.drop(columns="partie"), parts], ignore_index=True)
    d.attrs["toutes_lignes"] = pd.DataFrame(toutes)
    d["estimation_insd"] = d["etoiles"].map({"*": "non recensee", "**": "partiellement recensee"}).fillna("")
    return d.drop(columns="etoiles")


def rattacher(d: pd.DataFrame, ref: territoire.Referentiel) -> pd.DataFrame:
    """Code P de chaque commune, par son nom dans sa province (ancien découpage)."""
    r = ref.decoupage("annuaires_2017_2025").merge(ref.communes, on="pcode_commune")
    r["k"] = r["commune_ancien"].map(geo.cle)
    r2 = r.assign(k=r["commune"].map(geo.cle))
    cles = pd.concat([r, r2]).drop_duplicates(["province", "k"])[["province", "k", "pcode_commune"]]
    d = d.assign(k=d["commune_source"].map(lambda x: geo.cle(ALIAS.get(x, x))))
    out = d.merge(cles, on=["province", "k"], how="left")
    # noms écrits autrement : meilleur rapprochement dans la même province, une commune ne servant qu'une fois
    out["rapprochement"] = ""
    for prov, g in out[out["pcode_commune"].isna()].groupby("province"):
        libres = r[(r["province"] == prov) & ~r["pcode_commune"].isin(out["pcode_commune"])]
        paires = sorted(((difflib.SequenceMatcher(None, a, b).ratio(), i, pc, nom)
                         for i, a in zip(g.index, g["k"]) for b, pc, nom in zip(libres["k"], libres["pcode_commune"], libres["commune"])),
                        reverse=True)
        pris_i, pris_c = set(), set()
        for score, i, pc, nom in paires:
            if score >= SIMILARITE_MIN and i not in pris_i and pc not in pris_c:
                out.loc[i, ["pcode_commune", "rapprochement"]] = [pc, f"{nom} ({score:.2f})"]
                pris_i.add(i)
                pris_c.add(pc)
    return out.drop(columns="k")


def construire() -> tuple[pd.DataFrame, pd.DataFrame]:
    ref = territoire.charger()
    brut = lire()
    d = rattacher(brut, ref)
    d.attrs["toutes_lignes"] = brut.attrs["toutes_lignes"]
    non_rattachees = d[d["pcode_commune"].isna()]
    # deux communes (Kindi, Gao) n'ont pas de ligne « COMMUNE : » : leur total est la plus grande ligne à leur nom
    toutes = d.attrs["toutes_lignes"]
    manquantes = ref.decoupage("annuaires_2017_2025").merge(ref.communes, on="pcode_commune")
    manquantes = manquantes[~manquantes["pcode_commune"].isin(d["pcode_commune"])]
    ajouts = []
    for _, c in manquantes.iterrows():
        cand = toutes[(toutes["province"] == c["province"]) & (toutes["commune_source"].map(geo.cle) == geo.cle(c["commune_ancien"]))]
        if len(cand):
            ajouts.append(cand.sort_values("population").iloc[-1].drop("partie").to_dict()
                          | {"pcode_commune": c["pcode_commune"], "estimation_insd": "", "rapprochement": "ligne sans libellé COMMUNE"})
    d = pd.concat([d, pd.DataFrame(ajouts)], ignore_index=True)
    ok = d[d["pcode_commune"].notna()].drop(columns="etoiles", errors="ignore")
    if ok["pcode_commune"].duplicated().any():
        raise ValueError("deux lignes du recensement rattachées à la même commune")
    return ok, non_rattachees


if __name__ == "__main__":
    ok, ko = construire()
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    ok.to_csv(SORTIE, index=False, sep=";", encoding="utf-8")
    r = ok[ok["rapprochement"] != ""]
    print(f"rapprochements par similarité ({len(r)}) :")
    print(r[["province", "commune_source", "rapprochement"]].to_string(index=False))
    ref = territoire.charger()
    manquantes = sorted(set(ref.communes["pcode_commune"]) - set(ok["pcode_commune"]))
    print(f"{len(ok)} communes rattachées, {len(ko)} lignes non rattachées, {len(manquantes)} communes du référentiel sans population")
    if len(ko):
        print(ko[["province", "commune_source", "population"]].to_string(index=False))
    if manquantes:
        print(ref.communes[ref.communes["pcode_commune"].isin(manquantes)].merge(
            ref.decoupage("annuaires_2017_2025"), on="pcode_commune")[["province", "commune", "commune_ancien"]].to_string(index=False))
    print("population totale :", int(ok["population"].sum()), " 6-11 ans :", int(ok["age_6_11"].sum()))
