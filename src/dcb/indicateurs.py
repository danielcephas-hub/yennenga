"""Table province × année × statut et indicateurs de dotation.

Les données viennent de l'entrepôt (dcb.entrepot) : celles extraites des annuaires et celles ajoutées ensuite par
les techniciens, relues dans le découpage d'analyse (config.yaml, decoupage_analyse).

Usage : PYTHONPATH=src python -m dcb.indicateurs   (après dcb.extraction et dcb.entrepot amorcer)
Produit data/processed/province_annee.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from dcb import geo
from dcb.lecture import RACINE

INTERIM = RACINE / "data" / "interim" / "annuaires"
SORTIE = RACINE / "data" / "processed"
COMPTES = ["ecoles", "salles", "groupes_pedagogiques", "maitres", "eleves"]
MURS = ["murs_dur", "murs_semi_dur", "murs_paille_banco", "murs_indetermine",
        "murs_bon_etat", "murs_mauvais_etat", "murs_etat_indetermine"]


def config() -> dict:
    return yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))


def _lire(nom: str) -> pd.DataFrame:
    return pd.read_csv(INTERIM / nom, sep=";", encoding="utf-8")


def _noms(cfg: dict) -> pd.DataFrame:
    from dcb import territoire
    p = territoire.charger().provinces(cfg["decoupage_analyse"])
    return p.rename(columns={"code_province": "code_territoire"})[["code_territoire", "province", "region"]]


def serie_effectifs() -> pd.DataFrame:
    """Élèves par province et par année (public + privé), 2004-05 à aujourd'hui (entrepôt, lot en vigueur par année)."""
    from dcb import entrepot
    cfg = config()
    h = entrepot.lire("serie_effectifs_province", decoupage=cfg["decoupage_analyse"]).merge(_noms(cfg), on="code_territoire")
    h["lot_source"] = "lot " + h["lot"].astype(str)
    return h[["annee_scolaire", "region", "province", "eleves", "lot_source"]].sort_values(["annee_scolaire", "region", "province"]).reset_index(drop=True)


def table_province_annee() -> pd.DataFrame:
    from dcb import entrepot
    cfg = config()
    noms = _noms(cfg)
    e = entrepot.lire("primaire_province", decoupage=cfg["decoupage_analyse"]).merge(noms, on="code_territoire")
    syn = e[["annee_scolaire", "province", "statut", *COMPTES]]
    # grille complète : une province absente d'un annuaire n'a aucune école ouverte cette année-là
    grille = pd.MultiIndex.from_product(
        [sorted(syn["annee_scolaire"].unique()), sorted(noms["province"]), ["public", "prive", "total"]],
        names=["annee_scolaire", "province", "statut"]).to_frame(index=False)
    t = grille.merge(syn, how="left", on=["annee_scolaire", "province", "statut"])
    t["aucune_ecole_ouverte"] = t["eleves"].isna()
    t[COMPTES] = t[COMPTES].fillna(0)
    t.insert(1, "region", t["province"].map(noms.set_index("province")["region"]))

    murs = e[["annee_scolaire", "province", "statut", *[m for m in [*MURS, "salles_tableau_murs"] if m in e.columns]]].copy()
    if "salles_tableau_murs" not in murs.columns:
        murs["salles_tableau_murs"] = np.nan
    # à défaut du total du tableau des matériaux, la somme des matériaux déclarés
    murs["salles_tableau_murs"] = murs["salles_tableau_murs"].fillna(murs[[m for m in MURS[:4] if m in murs.columns]].sum(axis=1, min_count=1))
    t = t.merge(murs, how="left", on=["annee_scolaire", "province", "statut"])

    def ratio(a, b):
        return (a / b).where(b > 0)

    t["eleves_par_maitre"] = ratio(t["eleves"], t["maitres"])
    t["eleves_par_salle"] = ratio(t["eleves"], t["salles"])
    t["eleves_par_groupe"] = ratio(t["eleves"], t["groupes_pedagogiques"])
    t["part_salles_precaires"] = ratio(t["murs_paille_banco"], t["salles_tableau_murs"])
    t["part_salles_mauvais_etat"] = ratio(t["murs_mauvais_etat"], t["salles_tableau_murs"])
    nm, ns = cfg["normes"]["eleves_par_maitre"], cfg["normes"]["eleves_par_salle"]
    t["maitres_manquants"] = np.maximum(0, np.ceil(t["eleves"] / nm) - t["maitres"])
    t["salles_manquantes"] = np.maximum(0, np.ceil(t["eleves"] / ns) - t["salles"])
    t["eleves_au_dela_norme_maitre"] = np.maximum(0, t["eleves"] - nm * t["maitres"])
    t["eleves_au_dela_norme_salle"] = np.maximum(0, t["eleves"] - ns * t["salles"])

    # choc d'activité : effectif rapporté au maximum historique de la province (public + privé)
    s = serie_effectifs()
    pic = s.groupby("province")["eleves"].max().rename("eleves_pic_historique")
    tot = s.rename(columns={"eleves": "eleves_serie"})[["annee_scolaire", "province", "eleves_serie"]]
    t = t.merge(tot, how="left", on=["annee_scolaire", "province"]).merge(pic, how="left", on="province")
    t["part_du_pic"] = t["eleves_serie"] / t["eleves_pic_historique"]
    return t.sort_values(["annee_scolaire", "region", "province", "statut"]).reset_index(drop=True)


if __name__ == "__main__":
    cfg = config()
    t = table_province_annee()
    SORTIE.mkdir(parents=True, exist_ok=True)
    t.to_csv(SORTIE / "province_annee.csv", index=False, sep=";", encoding="utf-8")
    serie_effectifs().to_csv(SORTIE / "serie_effectifs_province.csv", index=False, sep=";", encoding="utf-8")
    print(f"{len(t)} lignes -> data/processed/province_annee.csv")
    ref = t[(t["annee_scolaire"] == cfg["annee_reference"]) & (t["statut"] == cfg["statut_cible"])]
    print(f"\n{cfg['annee_reference']}, secteur {cfg['statut_cible']} — national : "
          f"{ref['eleves'].sum() / ref['maitres'].sum():.1f} élèves par maître, "
          f"{ref['eleves'].sum() / ref['salles'].sum():.1f} élèves par salle ; "
          f"maîtres manquants {ref['maitres_manquants'].sum():.0f}, salles manquantes {ref['salles_manquantes'].sum():.0f}, "
          f"salles en paille ou banco {ref['murs_paille_banco'].sum():.0f}")
    cols = ["region", "province", "eleves", "maitres", "salles", "eleves_par_maitre", "eleves_par_salle",
            "part_salles_precaires", "maitres_manquants", "salles_manquantes", "part_du_pic"]
    print(ref.sort_values("eleves_par_maitre", ascending=False)[cols].head(12).round(2).to_string(index=False))
    print("...")
    print(ref.sort_values("eleves_par_maitre")[cols].head(6).round(2).to_string(index=False))
