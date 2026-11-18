"""Indice de besoin par province et test de robustesse du classement.

Chaque indicateur est converti en rang centile (0 = la mieux dotée, 1 = la plus en difficulté). Les indicateurs
fortement corrélés sont regroupés en dimensions (moyenne de leurs rangs), comme annoncé dans la note d'intention :
sans ce regroupement, deux indicateurs qui disent la même chose compteraient double. Les dimensions sont ensuite
pondérées (config.yaml). Le classement est rejoué avec un poids de la première dimension tiré au hasard dans une
plage plausible, pour distinguer les provinces dont le rang est solide de celles dont il dépend du choix des poids.

Usage : PYTHONPATH=src python -m dcb.indice   (après dcb.indicateurs)
Produit data/processed/indice_besoin.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dcb.indicateurs import SORTIE, config


def _spearman(a: pd.Series, b: pd.Series) -> float:
    return float(a.rank().corr(b.rank()))


def indice_besoin(table: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    ci = cfg["indice"]
    dims: dict[str, list[str]] = ci["dimensions"]
    poids = ci["ponderations"]
    noms_dims = list(dims)
    indicateurs = [i for d in noms_dims for i in dims[d]]
    ref = table[(table["annee_scolaire"] == cfg["annee_reference"]) & (table["statut"] == cfg["statut_cible"])].copy()
    ref = ref[~ref["aucune_ecole_ouverte"]].reset_index(drop=True)
    rangs = ref[indicateurs].rank(pct=True, method="average").fillna(0.5)
    for d in noms_dims:
        ref[f"score_{d}"] = rangs[dims[d]].mean(axis=1)
    scores = ref[[f"score_{d}" for d in noms_dims]].to_numpy()
    w = np.array([poids[d] for d in noms_dims], dtype=float)
    w /= w.sum()
    ref["indice_besoin"] = scores @ w
    ref["rang"] = ref["indice_besoin"].rank(ascending=False, method="min").astype(int)

    # robustesse : poids de la première dimension tiré uniformément dans la plage de config.yaml
    if len(noms_dims) != 2:
        raise ValueError("le test de robustesse suppose deux dimensions")
    lo, hi = ci["robustesse"]["plage_poids_premiere_dimension"]
    gen = np.random.default_rng(ci["graine"])
    w1 = gen.uniform(lo, hi, ci["tirages_robustesse"])
    tirages = np.c_[w1, 1 - w1]
    sim = scores @ tirages.T                                       # provinces × tirages
    rangs_sim = (-sim).argsort(axis=0).argsort(axis=0) + 1
    n = len(ref)
    taille_tiers = int(np.ceil(n / 3))
    tiers_base = np.ceil(ref["rang"].to_numpy() / taille_tiers)
    tiers_sim = np.ceil(rangs_sim / taille_tiers)
    ref["rang_p95"] = np.percentile(rangs_sim, 95, axis=1).astype(int)
    ref["rang_p05"] = np.percentile(rangs_sim, 5, axis=1).astype(int)
    ref["rang_median"] = np.median(rangs_sim, axis=1)
    ref["part_meme_tiers"] = (tiers_sim == tiers_base[:, None]).mean(axis=1)
    ref["rang_instable"] = ref["part_meme_tiers"] < 1 - ci["robustesse"]["seuil_changement_tiers"]
    base = ref["rang"].to_numpy()
    rho = np.array([np.corrcoef(base, rangs_sim[:, k])[0, 1] for k in range(rangs_sim.shape[1])])
    top = set(ref.nsmallest(10, "rang")["province"])
    stabilite_top10 = np.mean([len(top & set(ref["province"][rangs_sim[:, k] <= 10])) / 10 for k in range(rangs_sim.shape[1])])
    bilan = {"spearman_median": float(np.median(rho)), "spearman_p05": float(np.percentile(rho, 5)),
             "part_top10_conservee": float(stabilite_top10), "provinces_instables": int(ref["rang_instable"].sum()),
             "taille_tiers": taille_tiers}
    # justification du regroupement : corrélation de rang entre les indicateurs d'une même dimension
    for d in noms_dims:
        if len(dims[d]) == 2:
            bilan[f"correlation_{d}"] = _spearman(ref[dims[d][0]], ref[dims[d][1]])
    cols = ["annee_scolaire", "region", "province", "statut", *indicateurs, *[f"score_{d}" for d in noms_dims],
            "indice_besoin", "rang", "rang_p05", "rang_median", "rang_p95", "part_meme_tiers", "rang_instable"]
    return ref[cols].sort_values("rang").reset_index(drop=True), bilan


if __name__ == "__main__":
    cfg = config()
    table = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    ind, bilan = indice_besoin(table, cfg)
    ind.to_csv(SORTIE / "indice_besoin.csv", index=False, sep=";", encoding="utf-8")
    print(ind[["province", "indice_besoin", "rang", "rang_p05", "rang_p95", "part_meme_tiers", "rang_instable"]].head(15)
          .round(3).to_string(index=False))
    print("\nRobustesse sur", cfg["indice"]["tirages_robustesse"], "tirages :", {k: round(v, 3) for k, v in bilan.items()})
    print("Rangs sensibles :", ind.loc[ind["rang_instable"], "province"].tolist())
