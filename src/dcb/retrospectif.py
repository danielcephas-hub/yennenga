"""Test rétrospectif : l'outil aurait-il mieux réparti les moyens réellement ajoutés ces dernières années ?

On se place en début de période (origine o), avec la seule information disponible à cette date : effectifs,
maîtres et salles de o ; part du pic et écoles fermées calculées sur les années ≤ o ; demande prévue = effectif de o
(prévision naïve, la seule qui ne suppose rien du futur). Les recrutements ne sont pas publiés et le solde national
est négatif (fermetures) : les moyens à répartir sont les hausses nettes réellement observées par province entre o et
la fin f (Σ max(0, Δmaîtres) et Σ max(0, Δsalles), secteur public). Les baisses sont neutralisées de la même façon
dans toutes les répartitions.

Quatre répartitions de ces moyens, à partir du même état initial, sont évaluées sur les élèves réellement présents
en f : réelle (hausses observées), au prorata des élèves, au prorata des besoins, optimisée.

Usage : PYTHONPATH=src python -m dcb.retrospectif   (après dcb.indicateurs)
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from dcb.indicateurs import SORTIE, config
from dcb.optimisation import au_prorata_des_besoins, donnees_probleme, evaluer, optimiser, proportionnelle

LIBELLES = {"reelle": "Répartition réelle", "proportionnelle": "Au prorata des élèves",
            "besoins": "Au prorata des besoins", "optimisee": "Optimisée (outil)"}


def _sans_fuite(table: pd.DataFrame, origine: str) -> pd.DataFrame:
    """Table réduite aux années ≤ origine, part du pic recalculée sur ces seules années."""
    t = table[table["annee_scolaire"] <= origine].copy()
    pic = t.groupby(["province", "statut"])["eleves"].transform("max")
    t["part_du_pic"] = (t["eleves"] / pic.where(pic > 0)).fillna(0)
    return t


def periode(table: pd.DataFrame, cfg0: dict, origine: str, fin: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = copy.deepcopy(cfg0)
    cfg["annee_reference"], cfg["annee_horizon"] = origine, fin
    cfg["optimisation"]["budget_fcfa"] = None
    passe = _sans_fuite(table, origine)
    tot_o = passe[(passe["annee_scolaire"] == origine) & (passe["statut"] == "total")]
    prevision = pd.DataFrame({"province": tot_o["province"], "scenario": "naive", "annee_scolaire": fin,
                              "eleves_prevus": tot_o["eleves"]})
    d = donnees_probleme(passe, prevision, cfg, "naive")

    cible = table[table["statut"] == cfg["statut_cible"]]
    o = cible[cible["annee_scolaire"] == origine].set_index("province")
    f = cible[cible["annee_scolaire"] == fin].set_index("province")
    hausse_t = (f["maitres"] - o["maitres"]).clip(lower=0).reindex(d["province"]).fillna(0).astype(int).values
    hausse_s = (f["salles"] - o["salles"]).clip(lower=0).reindex(d["province"]).fillna(0).astype(int).values
    n, m = int(hausse_t.sum()), int(hausse_s.sum())

    reel = d.assign(enseignants_attribues=hausse_t, salles_attribuees=hausse_s)
    opt, statut = optimiser(d, cfg, n, m)
    repartitions = {"reelle": reel, "proportionnelle": proportionnelle(d, n, m),
                    "besoins": au_prorata_des_besoins(d, cfg, n, m), "optimisee": opt}
    eleves_fin = f["eleves"].reindex(d["province"]).fillna(0).values
    bilan, detail = [], []
    for nom, r in repartitions.items():
        r = r.copy()
        r["eleves_horizon"] = eleves_fin  # évaluation sur les élèves réellement présents en fin de période
        bilan.append({"origine": origine, "fin": fin, "methode": nom, "enseignants_disponibles": n,
                      "salles_disponibles": m, **evaluer(r, cfg), "statut_solveur": statut if nom == "optimisee" else ""})
        detail.append(r.assign(origine=origine, fin=fin, methode=nom)[
            ["origine", "fin", "methode", "province", "region", "maitres", "salles", "eleves_horizon",
             "enseignants_attribues", "salles_attribuees"]])
    return pd.DataFrame(bilan), pd.concat(detail, ignore_index=True)


def executer() -> pd.DataFrame:
    cfg = config()
    table = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    bilans, details = [], []
    for o, f in cfg.get("retrospectif", {}).get("periodes", [["2019-2020", "2024-2025"], ["2018-2019", "2023-2024"]]):
        b, d = periode(table, cfg, o, f)
        bilans.append(b)
        details.append(d)
    bilan = pd.concat(bilans, ignore_index=True)
    reel = bilan[bilan["methode"] == "reelle"].set_index("origine")["eleves_au_dela_norme_maitre"]
    bilan["ecart_vs_reelle"] = bilan["eleves_au_dela_norme_maitre"] / bilan["origine"].map(reel) - 1
    bilan.to_csv(SORTIE / "retrospectif_bilan.csv", sep=";", index=False, encoding="utf-8")
    pd.concat(details, ignore_index=True).to_csv(SORTIE / "retrospectif_detail.csv", sep=";", index=False, encoding="utf-8")
    return bilan


if __name__ == "__main__":
    b = executer()
    pd.set_option("display.width", 200)
    print(b[["origine", "fin", "methode", "enseignants_disponibles", "salles_disponibles", "eleves_au_dela_norme_maitre",
             "pire_ratio_eleves_maitre", "gini_ratio_maitre", "ecart_vs_reelle"]].round(3).to_string(index=False))
    o = b[b["methode"] == "optimisee"]
    for _, r in o.iterrows():
        print(f"{r['origine']} → {r['fin']} : {abs(r['ecart_vs_reelle']):.0%} d'élèves en surnombre "
              f"{'de moins' if r['ecart_vs_reelle'] < 0 else 'de plus'} que la répartition réelle")
