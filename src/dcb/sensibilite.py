"""Analyses de sensibilité de la répartition : le résultat tient-il si l'on change une hypothèse ?

On fait varier une hypothèse à la fois (config.yaml, rubrique sensibilite), les autres restant à leur valeur
de référence, et on compare la répartition optimisée aux deux règles simples, à moyens égaux.

Usage : PYTHONPATH=src python -m dcb.sensibilite   (après dcb.prevision)
Produit data/processed/sensibilite.csv
"""
from __future__ import annotations

import copy

import pandas as pd

from dcb.indicateurs import SORTIE, config
from dcb.optimisation import comparer, donnees_probleme


def variantes(cfg: dict) -> list[tuple[str, str, dict, dict]]:
    """(hypothèse, valeur affichée, cfg modifiée, arguments de comparer)."""
    s = cfg["sensibilite"]
    opt = cfg["optimisation"]
    base = {"n": opt["enseignants_a_repartir"], "m": opt["salles_a_construire"]}
    out = []
    for v in s["seuil_acces_construction"]:
        c = copy.deepcopy(cfg)
        c["optimisation"]["seuil_acces_construction"] = v
        out.append(("seuil_acces_construction", f"{round(100 * v)} %", c, base))
    for v in s["eleves_par_maitre"]:
        c = copy.deepcopy(cfg)
        c["normes"] = {"eleves_par_maitre": v, "eleves_par_salle": v}
        out.append(("norme_eleves_par_maitre", str(v), c, base))
    c = copy.deepcopy(cfg)
    c["optimisation"]["paliers"] = [{"multiple_norme": 1.0, "poids": 1.0}]
    out.append(("paliers", "un seul palier", c, base))
    out.append(("paliers", "paliers fins (référence)", copy.deepcopy(cfg), base))
    illimite = 10 ** 6
    for v in s["cout_enseignant_fcfa"]:
        c = copy.deepcopy(cfg)
        c["optimisation"]["cout_enseignant_fcfa"] = v
        out.append(("cout_enseignant_budget", f"{v / 1e6:.1f} M FCFA par an, budget {s['budget_fcfa'] / 1e9:.0f} Md",
                    c, {"n": illimite, "m": illimite, "budget": s["budget_fcfa"]}))
    return out


def sensibilite(cfg: dict) -> pd.DataFrame:
    table = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    prevision = pd.read_csv(SORTIE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    lignes = []
    for hyp, valeur, c, args in variantes(cfg):
        d = donnees_probleme(table, prevision, c)
        _, bilan, statut = comparer(d, c, **args)
        lignes.append(bilan.assign(hypothese=hyp, valeur=valeur, statut_solveur=statut))
    out = pd.concat(lignes, ignore_index=True)
    return out[["hypothese", "valeur", *[c for c in out.columns if c not in ("hypothese", "valeur")]]]


if __name__ == "__main__":
    cfg = config()
    res = sensibilite(cfg)
    res.to_csv(SORTIE / "sensibilite.csv", index=False, sep=";", encoding="utf-8")
    vue = res.pivot_table(index=["hypothese", "valeur"], columns="methode", sort=False,
                          values=["pire_ratio_eleves_maitre", "gini_ratio_maitre", "enseignants_attribues"])
    with pd.option_context("display.width", 220):
        print(vue.round(3).to_string())
    print("statuts :", res.loc[res["methode"] == "optimisee", "statut_solveur"].value_counts().to_dict())
