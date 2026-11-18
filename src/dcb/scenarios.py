"""Grille de scénarios précalculés pour le simulateur du tableau de bord.

Pour chaque combinaison (enseignants à répartir, salles à construire, hypothèse de demande), on résout
la répartition optimisée et on la compare à la répartition proportionnelle à moyens égaux.

Usage : PYTHONPATH=src python -m dcb.scenarios   (après dcb.prevision)
Produit data/processed/scenarios_bilan.csv, scenarios_allocation.csv et scenarios_budget.csv
"""
from __future__ import annotations

import itertools

import pandas as pd

from dcb.indicateurs import SORTIE, config
from dcb.optimisation import comparer, donnees_probleme


def grille(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    g = cfg["scenarios"]
    table = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    prevision = pd.read_csv(SORTIE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    bilans, details = [], []
    for demande in g["demandes"]:
        d = donnees_probleme(table, prevision, cfg, scenario=demande)
        for n, m in itertools.product(g["enseignants"], g["salles"]):
            detail, bilan, statut = comparer(d, cfg, n=n, m=m)
            cles = {"demande": demande, "enseignants_disponibles": n, "salles_disponibles": m}
            bilans.append(bilan.assign(**cles, statut_solveur=statut))
            details.append(detail[detail["methode"] != "sans_moyens_nouveaux"].assign(**cles))
    cols = ["demande", "enseignants_disponibles", "salles_disponibles"]
    b = pd.concat(bilans, ignore_index=True)
    a = pd.concat(details, ignore_index=True)
    a = a[[*cols, "methode", "region", "province", "eleves_horizon", "maitres", "salles", "enseignants_attribues",
           "salles_attribuees", "ratio_maitre_apres", "ratio_salle_apres", "construction_possible", "rouvrir_d_abord", "salles_rouvertes"]]
    return b[[*cols, *[c for c in b.columns if c not in cols]]], a


def budgets(cfg: dict) -> pd.DataFrame:
    """Scénarios « budget seul » : nombre d'enseignants et de salles libres, seul le budget contraint.

    L'optimisation arbitre alors entre recruter (un poste, payé chaque année) et construire (une salle, payée une fois)."""
    table = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    prevision = pd.read_csv(SORTIE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    d = donnees_probleme(table, prevision, cfg, scenario=cfg["optimisation"]["scenario_demande"])
    illimite = 10 * int(d["eleves_horizon"].sum() / cfg["normes"]["eleves_par_maitre"])
    lignes = []
    for b in cfg["optimisation"]["budgets_scenarios_fcfa"]:
        _, bilan, statut = comparer(d, cfg, n=illimite, m=illimite, budget=b)
        lignes.append(bilan.assign(budget_fcfa=b, demande=cfg["optimisation"]["scenario_demande"], statut_solveur=statut))
    out = pd.concat(lignes, ignore_index=True)
    return out[["budget_fcfa", "demande", *[c for c in out.columns if c not in ("budget_fcfa", "demande")]]]


if __name__ == "__main__":
    cfg = config()
    bilan, alloc = grille(cfg)
    bilan.to_csv(SORTIE / "scenarios_bilan.csv", index=False, sep=";", encoding="utf-8")
    alloc.to_csv(SORTIE / "scenarios_allocation.csv", index=False, sep=";", encoding="utf-8")
    bud = budgets(cfg)
    bud.to_csv(SORTIE / "scenarios_budget.csv", index=False, sep=";", encoding="utf-8")
    print(bud[bud["methode"] == "optimisee"][["budget_fcfa", "enseignants_attribues", "salles_attribuees",
                                              "pire_ratio_eleves_maitre", "statut_solveur", "duree_s"]].to_string(index=False))
    print(f"{bilan.groupby(['demande', 'enseignants_disponibles', 'salles_disponibles']).ngroups} scénarios résolus ; "
          f"statuts : {bilan.loc[bilan['methode'] == 'optimisee', 'statut_solveur'].value_counts().to_dict()} ; "
          f"{bilan['duree_s'].max():.2f} s au plus par résolution")
    p = bilan[bilan["demande"] == cfg["optimisation"]["scenario_demande"]].pivot_table(
        index=["enseignants_disponibles", "salles_disponibles"], columns="methode", values="eleves_au_dela_norme_maitre")
    p["gain_optimisation"] = 1 - p["optimisee"] / p["proportionnelle"]
    print(p.round(3).to_string())
