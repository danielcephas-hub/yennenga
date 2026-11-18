"""Rapprochement entre les annuaires (Data Pack) et le fichier principal des organisateurs.

Usage : PYTHONPATH=src python -m dcb.controles   (après dcb.extraction et dcb.ingestion)
Produit outputs/controles/rapprochement_annuaires_principal.csv
"""
from __future__ import annotations

import pandas as pd

from dcb.lecture import RACINE

INTERIM = RACINE / "data" / "interim"
SORTIE = RACINE / "outputs" / "controles"


def _lire(chemin) -> pd.DataFrame:
    return pd.read_csv(chemin, sep=";", encoding="utf-8")


def rapprocher() -> pd.DataFrame:
    """Une ligne par (année, région ou national, mesure) : valeur des annuaires, valeur du fichier principal, écart."""
    syn = _lire(INTERIM / "annuaires" / "synthese.csv")
    prov = syn[syn["niveau"] == "province"]
    lignes = []
    for mesure, fichier, col_mod in (("eleves", "effectifs_region.csv", "sexe"), ("ecoles", "ecoles_region.csv", "statut")):
        princ = _lire(INTERIM / "principal" / fichier)
        princ = princ[princ[col_mod] == "total"]
        ann_reg = prov[prov["statut"] == "total"].groupby(["annee_scolaire", "region"])[mesure].sum()
        ann_nat = prov[prov["statut"] == "total"].groupby("annee_scolaire")[mesure].sum()
        for _, r in princ.iterrows():
            if r["niveau"] == "region":
                a = ann_reg.get((r["annee_scolaire"], r["region"]))
            else:
                a = ann_nat.get(r["annee_scolaire"])
            if a is None:
                continue  # année absente des annuaires (2015-16, 2016-17)
            lignes.append({"annee_scolaire": r["annee_scolaire"], "entite": r["region"] if r["niveau"] == "region" else "NATIONAL",
                           "mesure": mesure, "annuaires": a, "fichier_principal": r[mesure], "ecart": a - r[mesure]})
    return pd.DataFrame(lignes)


if __name__ == "__main__":
    t = rapprocher()
    SORTIE.mkdir(parents=True, exist_ok=True)
    t.to_csv(SORTIE / "rapprochement_annuaires_principal.csv", index=False, sep=";", encoding="utf-8")
    print(f"{len(t)} comparaisons, {(t['ecart'] != 0).sum()} écart(s) non nul(s)")
    bilan = t.assign(egal=t["ecart"] == 0).groupby(["mesure", "annee_scolaire"])["egal"].agg(["sum", "count"])
    print(bilan.rename(columns={"sum": "identiques", "count": "comparaisons"}).to_string())
    if (t["ecart"] != 0).any():
        print(t[t["ecart"] != 0].to_string(index=False))
