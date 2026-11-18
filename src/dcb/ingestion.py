"""Lecture du fichier principal des organisateurs (préscolaire et primaire, 13 régions, 2015/16 à 2024/25).

Parades aux pièges du classeur :
- l'année est extraite de l'en-tête par expression régulière (certains en-têtes portent un texte parasite) ;
- chaque tableau est borné : la lecture s'arrête à la première ligne sans chiffre (du texte parasite traîne plus bas) ;
- les étiquettes des cellules fusionnées sont propagées vers le bas ;
- les lignes de total national sont isolées, les libellés harmonisés par `geo`.

Usage : PYTHONPATH=src python -m dcb.ingestion
"""
from __future__ import annotations

import re

import openpyxl
import pandas as pd

from dcb import geo
from dcb.lecture import RACINE

BRUT = RACINE / "data" / "raw"
SORTIE = RACINE / "data" / "interim" / "principal"

_ANNEE = re.compile(r"(\d{4})\s*[-/]\s*\d{2,4}")
_NATIONAL = {"NATIONAL", "BURKINAFASO", "TOTALGENERAL", "TOTAL", "ENSEMBLE"}
_MODALITES = {"GARCONS": "garcons", "FILLES": "filles", "TOTAL": "total", "PUBLIC": "public", "PRIVE": "prive"}


def classeur() -> openpyxl.Workbook:
    fichiers = sorted(BRUT.glob("*.xlsx"))
    if len(fichiers) != 1:
        raise FileNotFoundError(f"un seul classeur attendu dans {BRUT}, trouvé : {len(fichiers)}")
    return openpyxl.load_workbook(fichiers[0], data_only=True)


def lire_tableau_region(ws, colonne_modalite: str, mesure: str, ligne_entete: int = 2) -> tuple[pd.DataFrame, list[str]]:
    """Tableau « REGION | modalité | année 1 | année 2 … » -> table longue.

    Renvoie (table, libellés non reconnus)."""
    entete = [c.value for c in ws[ligne_entete]]
    annees = {}
    for j, v in enumerate(entete):
        m = _ANNEE.search(str(v)) if v is not None else None
        if m and j >= 2:
            annees[j] = f"{m.group(1)}-{int(m.group(1)) + 1}"
    lignes, inconnus = [], []
    etiquette = None
    for row in ws.iter_rows(min_row=ligne_entete + 1, values_only=True):
        chiffres = {a: row[j] for j, a in annees.items() if j < len(row)}
        if not any(isinstance(x, (int, float)) for x in chiffres.values()):
            break  # fin du tableau
        if row[0] is not None and str(row[0]).strip():
            etiquette = str(row[0]).strip()
        modalite = _MODALITES.get(geo.cle(row[1] or ""))
        if modalite is None:
            inconnus.append(f"modalité {row[1]!r}")
            continue
        if geo.region(etiquette or ""):
            niveau, reg = "region", geo.region(etiquette)
        elif geo.cle(etiquette or "") in _NATIONAL:
            niveau, reg = "national", None
        else:
            inconnus.append(f"étiquette {etiquette!r}")
            continue
        for a, x in chiffres.items():
            lignes.append({"annee_scolaire": a, "niveau": niveau, "region": reg, colonne_modalite: modalite, mesure: x})
    return pd.DataFrame(lignes), inconnus


def effectifs_region() -> pd.DataFrame:
    """Élèves du primaire par région et par sexe (Tableau 1)."""
    tab, inconnus = lire_tableau_region(classeur()["Feuil1"], "sexe", "eleves")
    if inconnus:
        print("Feuil1 — non reconnus :", sorted(set(inconnus)))
    return tab


def ecoles_region() -> pd.DataFrame:
    """Écoles du primaire par région et par statut (Tableau 13)."""
    tab, inconnus = lire_tableau_region(classeur()["Feuil13"], "statut", "ecoles")
    if inconnus:
        print("Feuil13 — non reconnus :", sorted(set(inconnus)))
    return tab


if __name__ == "__main__":
    SORTIE.mkdir(parents=True, exist_ok=True)
    for nom, f in (("effectifs_region", effectifs_region), ("ecoles_region", ecoles_region)):
        t = f()
        t.to_csv(SORTIE / f"{nom}.csv", index=False, sep=";", encoding="utf-8")
        print(f"{nom} : {len(t)} lignes, {t['annee_scolaire'].nunique()} années, "
              f"{t.loc[t['niveau'] == 'region', 'region'].nunique()} régions, national : {(t['niveau'] == 'national').any()}")
