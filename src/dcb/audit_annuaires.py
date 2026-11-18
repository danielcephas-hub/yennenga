"""Audit des annuaires du primaire : quelles sections, pour quelles années.

Les annuaires n'ont pas de titres « Tableau N » : ils sont organisés en sections numérotées
(I.1, III.2.1, …) listées dans une table des matières. On s'appuie sur elle.

Usage (depuis la racine) : PYTHONPATH=src python -m dcb.audit_annuaires
Produit outputs/audit/annuaires_sections.csv (une section par ligne et par année).
"""
from __future__ import annotations

import re

import pandas as pd

from dcb.lecture import CSV, RACINE, cellules, lire_csv

DOSSIER = CSV / "01_Education_MENAPLN_DGESS" / "CNS_DGESS" / "Annuaires"
SORTIE = RACINE / "outputs" / "audit"

_NUMERO = re.compile(r"^\s*((?:[IVX]+)\s*[\.\-]?\s*(?:\d+(?:\s*\.\s*\d+)*)?)\s*\.?\s+(.*)$")
_PAGES = re.compile(r"^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$")


def annuaires_primaire() -> list[tuple[str, object]]:
    """(année scolaire, chemin) des annuaires du primaire, triés par année."""
    res = []
    for f in DOSSIER.glob("*.csv"):
        m = re.search(r"primaire_(\d{4})_(\d{4})", f.name, re.I)
        if m:
            res.append((f"{m.group(1)}-{m.group(2)}", f))
    return sorted(res)


def table_des_matieres(df: pd.DataFrame) -> pd.DataFrame:
    """Sections de la table des matières : numéro, intitulé, pages imprimées."""
    cs = cellules(df)
    debut = df.index[df[cs[0]].str.contains(r"TABLE DES MATI", case=False, na=False)]
    if len(debut) == 0:
        return pd.DataFrame(columns=["numero", "intitule", "page_debut", "page_fin"])
    p0 = int(df.loc[debut[0], "page"])
    bloc = df[(df["page"] >= p0) & (df["page"] <= p0 + 5)]
    lignes, parent = [], ""
    for _, r in bloc.iterrows():
        v = [x.strip() for x in r[cs] if x.strip()]
        if not v:
            continue
        pages = _PAGES.match(v[-1]) if len(v) >= 2 else None
        texte = " ".join(v[:-1] if pages else v)
        m = _NUMERO.match(texte)
        if not m:
            continue
        numero = re.sub(r"[\s\-]", "", m.group(1)).rstrip(".")
        intitule = m.group(2).strip()
        if not pages:
            parent = intitule  # titre de groupe sans page : sert de contexte aux sous-sections
            continue
        court = intitule.lower() in {"public", "privé", "prive", "public + privé", "public + prive", "public+ privé",
                                     "urbain", "rural", "urbain + rural", "urbain+ rural"}
        lignes.append({
            "numero": numero,
            "intitule": f"{parent} — {intitule}" if court and parent else intitule,
            "page_debut": int(pages.group(1)),
            "page_fin": int(pages.group(2) or pages.group(1)),
        })
    return pd.DataFrame(lignes)


def auditer() -> pd.DataFrame:
    tout = []
    for annee, f in annuaires_primaire():
        df = lire_csv(f)
        toc = table_des_matieres(df)
        toc.insert(0, "annee_scolaire", annee)
        toc.insert(1, "publication", f.name[:6])
        print(f"{f.name[:6]} {annee} : {len(df):>6} lignes, {int(df['page'].max())} pages PDF, {len(toc)} sections")
        tout.append(toc)
    return pd.concat(tout, ignore_index=True)


if __name__ == "__main__":
    tab = auditer()
    SORTIE.mkdir(parents=True, exist_ok=True)
    tab.to_csv(SORTIE / "annuaires_sections.csv", index=False, sep=";", encoding="utf-8")
    print(f"\n{len(tab)} sections recensées -> outputs/audit/annuaires_sections.csv")
    cles = {
        "I.1 écoles, salles, élèves, maîtres": r"coles, salles",
        "enseignants par catégorie": r"enseignants par cat",
        "écoles et salles publiques et privées": r"coles et salles de classe",
        "nature et état des murs": r"murs",
        "nature et état des toitures": r"toitures",
        "mobilier des élèves": r"Mobilier des",
        "distance parcourue": r"distance",
        "équipement des écoles": r"Equipement des",
        "historique par province": r"Historique des effectifs par province",
        "financement public": r"FINANCEMENT",
    }
    print("\nPrésence des sections utiles au défi 3 (pages imprimées de la 1re occurrence) :")
    lignes = {}
    for nom, rx in cles.items():
        s = tab[tab["intitule"].str.contains(rx, case=False, regex=True)]
        lignes[nom] = s.groupby("annee_scolaire").apply(lambda g: f"{g.iloc[0]['numero']} p.{g.iloc[0]['page_debut']}", include_groups=False)
    print(pd.DataFrame(lignes).T.fillna("—").to_string())
