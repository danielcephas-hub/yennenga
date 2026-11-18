"""Essai d'apprentissage automatique pour la prévision des effectifs (extension annoncée par la note d'intention).

La note prévoyait un modèle d'apprentissage automatique « si les séries le permettent » et seulement s'il bat la
prévision naïve. Ce module le teste dans le même protocole que les autres méthodes (dcb.prevision) :
- modèles globaux, entraînés sur toutes les provinces à la fois (une seule série serait trop courte) ;
- cible : variation du logarithme de l'effectif entre l'année d'origine et l'année prévue ;
- variables connues à l'origine : croissances récentes, écart au maximum historique, chute brutale depuis 2015,
  niveau relatif de la province ;
- à chaque origine, apprentissage sur les seuls couples (origine, horizon) dont l'année prévue est déjà connue :
  aucune information du futur n'est utilisée ;
- comparaison avec les méthodes de dcb.prevision sur exactement les mêmes cas.

Usage : PYTHONPATH=src python -m dcb.essai_ml   (après dcb.prevision)
Produit data/processed/prevision_essai_ml.csv
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge

from dcb.indicateurs import SORTIE, config
from dcb.prevision import matrice

MODELES = {
    "ml_ridge": lambda graine: Ridge(alpha=1.0),
    "ml_gradient_boosting": lambda graine: GradientBoostingRegressor(n_estimators=150, max_depth=2, learning_rate=0.05,
                                                                      subsample=0.8, random_state=graine),
}
COMPAREES = ["naive", "tendance_lineaire", "croissance_amortie"]


def jeu_de_donnees(m: pd.DataFrame, cfg: dict, horizon_max: int) -> pd.DataFrame:
    """Une ligne par (province, origine, horizon) : variables connues à l'origine, cible si l'année prévue est connue."""
    annees = list(m.columns)
    log = np.log1p(m)
    lignes = []
    for i in range(4, len(annees)):
        o = annees[i]
        for prov in m.index:
            y = m.loc[prov].to_numpy(dtype=float)
            l = log.loc[prov].to_numpy(dtype=float)
            if np.isnan(y[: i + 1]).any():
                continue
            recent = m.loc[prov, [c for c in annees if cfg["prevision"]["choc_depuis"] <= c <= o]]
            chute = recent.pct_change().min()
            x = [l[i] - l[i - 1], l[i] - l[i - 2], (l[i] - l[i - 4]) / 4, l[i] - np.log1p(np.nanmax(y[: i + 1])),
                 float(pd.notna(chute) and chute < -cfg["prevision"]["choc_seuil_baisse"]),
                 l[i] - np.nanmean(log.iloc[:, i])]
            for h in range(1, horizon_max + 1):
                connu = i + h < len(annees) and not np.isnan(y[i + h])
                lignes.append({"province": prov, "origine": o, "horizon": h, "effectif_origine": y[i],
                               "cible": l[i + h] - l[i] if connu else np.nan, "realise": y[i + h] if connu else np.nan,
                               **{f"x{k}": v for k, v in enumerate(x)}})
    return pd.DataFrame(lignes)


def essai(serie: pd.DataFrame, test: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    m = matrice(serie)
    horizon_max = int(test["horizon"].max())
    d = jeu_de_donnees(m, cfg, horizon_max)
    variables = [c for c in d.columns if c.startswith("x")]
    minimum = cfg["prevision"]["essai_ml"]["apprentissage_minimal"]
    graine = cfg["prevision"]["essai_ml"]["graine"]
    prevus = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for (o, h), cas in d[d["realise"].notna()].groupby(["origine", "horizon"]):
            appr = d[(d["horizon"] == h) & (d["origine"] + h <= o) & d["cible"].notna()]
            if len(appr) < minimum:
                continue
            for nom, fabrique in MODELES.items():
                modele = fabrique(graine).fit(appr[variables], appr["cible"])
                p = (cas["effectif_origine"] + 1) * np.exp(modele.predict(cas[variables])) - 1
                prevus.append(pd.DataFrame({"methode": nom, "province": cas["province"], "origine": o, "horizon": h,
                                            "prevu": np.maximum(0, p), "realise": cas["realise"]}))
    ml = pd.concat(prevus, ignore_index=True)
    # mêmes cas pour toutes les méthodes comparées
    ref = test[test["methode"].isin(COMPAREES)][["methode", "province", "origine", "horizon", "prevu", "realise"]]
    cle = ["province", "origine", "horizon"]
    communs = ml[cle].drop_duplicates().merge(ref[cle].drop_duplicates(), on=cle)
    tout = pd.concat([ref, ml], ignore_index=True).merge(communs, on=cle)
    lignes = []
    for periode, sel in (("toutes_origines", tout), (f"origines_{cfg['prevision']['choc_depuis'] + 3}_et_apres",
                                                      tout[tout["origine"] >= cfg["prevision"]["choc_depuis"] + 3])):
        g = sel.assign(ecart=(sel["prevu"] - sel["realise"]).abs()).groupby(["methode", "horizon"])
        w = (g["ecart"].sum() / g["realise"].sum()).rename("wape")
        lignes.append(pd.concat([w, g.size().rename("cas")], axis=1).reset_index().assign(periode=periode))
    res = pd.concat(lignes, ignore_index=True)
    # règle de la note : retenu seulement s'il fait mieux que la référence naïve, en moyenne sur les horizons
    moy = res[res["periode"] == "toutes_origines"].groupby("methode")["wape"].mean()
    res["bat_la_reference"] = res["methode"].map(moy < moy["naive"])
    return res


if __name__ == "__main__":
    cfg = config()
    serie = pd.read_csv(SORTIE / "serie_effectifs_province.csv", sep=";", encoding="utf-8")
    test = pd.read_csv(SORTIE / "prevision_test.csv", sep=";", encoding="utf-8")
    res = essai(serie, test, cfg)
    res.to_csv(SORTIE / "prevision_essai_ml.csv", index=False, sep=";", encoding="utf-8")
    for periode, g in res.groupby("periode"):
        print(f"\nErreur (WAPE, %) par horizon — {periode} ; {int(g[g['methode'] == 'naive']['cas'].sum())} cas par méthode")
        print((100 * g.pivot(index="methode", columns="horizon", values="wape")).round(1).to_string())
    print("\nBat la référence naïve :", res.drop_duplicates("methode").set_index("methode")["bat_la_reference"].to_dict())
