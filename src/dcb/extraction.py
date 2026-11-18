"""Extraction des tableaux des annuaires du primaire, par province et par année.

Chaque page d'un annuaire répète en tête le titre de sa section : on repère les pages par ce titre,
jamais par numéro de section ni par numéro de page (les deux changent d'une année à l'autre).

Usage (depuis la racine) : PYTHONPATH=src python -m dcb.extraction
Produit data/interim/annuaires/synthese.csv et affiche les contrôles de cohérence.
"""
from __future__ import annotations

import re

import pandas as pd

from dcb import geo
from dcb.audit_annuaires import annuaires_primaire
from dcb.lecture import RACINE, cellules, lire_csv, nombre

SORTIE = RACINE / "data" / "interim" / "annuaires"

TITRE_SYNTHESE = r"NOMBRE D'ECOLES, DE SALLES? DE CLASSE, D'ELEVES"
_STATUTS = {"PUBLIC": "public", "PRIVE": "prive", "TOTAL": "total"}
MESURES_SYNTHESE = ["ecoles", "salles", "groupes_pedagogiques", "maitres", "eleves", "ratio_eleves_maitre_publie"]


def pages_section(df: pd.DataFrame, motif: str) -> list[int]:
    """Pages dont l'en-tête (5 premières lignes, cellule unique) porte le titre recherché."""
    c1 = cellules(df)[0]
    tete = df[(df["ligne"] <= 5) & (df["nb_cellules"] == 1)]
    return sorted(tete.loc[tete[c1].str.contains(motif, case=False, regex=True), "page"].unique().tolist())


def _valeurs(ligne: pd.Series, cs: list[str]) -> list[str]:
    return [x.strip() for x in ligne[cs] if x.strip()]


def extraire_synthese(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Tableau « écoles, salles, groupes pédagogiques, maîtres, élèves par statut ».

    Renvoie (table longue, libellés non reconnus). Une ligne par entité (province, région, national)
    et par statut (public, prive, total).
    """
    cs = cellules(df)
    pages = pages_section(df, TITRE_SYNTHESE)
    bloc = df[df["page"].isin(pages)].sort_values(["page", "ligne"])
    lignes, inconnus = [], []
    region_courante: str | None = None
    entite: tuple[str, str | None] | None = None  # (niveau, province)
    for _, r in bloc.iterrows():
        v = _valeurs(r, cs)
        if not v:
            continue
        tete = geo.cle(v[0])
        if len(v) == 1:
            if geo.region(v[0]):
                region_courante = geo.region(v[0])
            continue
        if tete.startswith("TOTALNATIONAL"):
            entite, region_courante = ("national", None), None
            continue
        if tete in _STATUTS:
            statut, chiffres = _STATUTS[tete], v[1:]
        elif geo.cle(v[1]) in _STATUTS:
            statut, chiffres = _STATUTS[geo.cle(v[1])], v[2:]
            if tete.startswith("TOTALREGION"):
                entite = ("region", None)
            elif geo.province(v[0]):
                entite = ("province", geo.province(v[0]))
            else:
                inconnus.append(v[0])
                entite = None
        else:
            continue  # ligne d'en-tête ou numéro de page
        if entite is None:
            continue
        vals = [nombre(x) for x in chiffres]
        if len(vals) != len(MESURES_SYNTHESE) or any(x is None for x in vals):
            inconnus.append(f"ligne illisible p.{r['page']} l.{r['ligne']} : {v}")
            continue
        niveau, prov = entite
        lignes.append({
            "niveau": niveau,
            "region": geo.REGION_DE[prov] if prov else region_courante,
            "province": prov,
            "statut": statut,
            **dict(zip(MESURES_SYNTHESE, vals)),
            "page_pdf": int(r["page"]),
            "ligne_pdf": int(r["ligne"]),
        })
    return pd.DataFrame(lignes), inconnus


def synthese_toutes_annees() -> pd.DataFrame:
    tout = []
    for annee, f in annuaires_primaire():
        tab, inconnus = extraire_synthese(lire_csv(f))
        tab.insert(0, "annee_scolaire", annee)
        tab.insert(1, "source", re.sub(r"\.csv$", "", f.name))
        nb = tab[tab["niveau"] == "province"]["province"].nunique()
        print(f"{annee} : {len(tab):>4} lignes, {nb} provinces" + (f" — NON RECONNUS : {inconnus}" if inconnus else ""))
        tout.append(tab)
    return pd.concat(tout, ignore_index=True)


def controler_synthese(tab: pd.DataFrame) -> pd.DataFrame:
    """Écarts de cohérence interne. Table vide = tout concorde."""
    comptes = ["ecoles", "salles", "groupes_pedagogiques", "maitres", "eleves"]
    ecarts = []

    def noter(annee, controle, entite, mesure, attendu, obtenu):
        if attendu != obtenu:
            ecarts.append({"annee_scolaire": annee, "controle": controle, "entite": entite, "mesure": mesure,
                           "attendu": attendu, "obtenu": obtenu, "ecart": obtenu - attendu})

    for annee, g in tab.groupby("annee_scolaire"):
        prov = g[g["niveau"] == "province"]
        reg = g[g["niveau"] == "region"]
        nat = g[g["niveau"] == "national"]
        # 1. public + privé = total, pour chaque entité
        for (niv, r_, p_), e in g.groupby(["niveau", "region", "province"], dropna=False):
            s = e.set_index("statut")
            if {"public", "prive", "total"} <= set(s.index):
                for m in comptes:
                    noter(annee, "public + prive = total", p_ or r_ or "NATIONAL", m,
                          s.loc["total", m], s.loc["public", m] + s.loc["prive", m])
        # 2. somme des provinces = total de la région ; 3. somme des provinces = national
        for statut in ("public", "prive", "total"):
            sp = prov[prov["statut"] == statut].groupby("region")[comptes].sum()
            sr = reg[reg["statut"] == statut].set_index("region")[comptes]
            for r_ in sp.index:
                for m in comptes:
                    if r_ in sr.index:
                        noter(annee, f"somme provinces = region ({statut})", r_, m, sr.loc[r_, m], sp.loc[r_, m])
                    else:
                        noter(annee, f"total region absent ({statut})", r_, m, float("nan"), sp.loc[r_, m])
            n = nat[nat["statut"] == statut]
            if len(n) == 1:
                for m in comptes:
                    noter(annee, f"somme provinces = national ({statut})", "NATIONAL", m,
                          n.iloc[0][m], prov[prov["statut"] == statut][m].sum())
            else:
                noter(annee, f"total national absent ({statut})", "NATIONAL", "-", 1, len(n))
        # 4. 45 provinces × 3 statuts
        noter(annee, "nombre de lignes province", "-", "-", 45 * 3, len(prov))
    return pd.DataFrame(ecarts)


MESURES_MURS = ["murs_dur", "murs_semi_dur", "murs_paille_banco", "murs_indetermine",
                "murs_bon_etat", "murs_mauvais_etat", "murs_etat_indetermine", "salles"]
MESURES_TOITURES = ["toit_tole", "toit_tuiles_ciment", "toit_banco", "toit_paille", "toit_absent",
                    "toit_bon_etat", "toit_mauvais_etat", "toit_etat_indetermine", "salles"]
TABLEAUX_ETAT = {
    "murs": (r"NATURE ET ETAT DES MURS", MESURES_MURS),
    "toitures": (r"NATURE ET ETAT DES TOIT", MESURES_TOITURES),
}
# titre de la sous-section selon le statut : « VI.4.1.1 Public », « VI.4.1.2 Privé », « VI.4.1.3 Public+Privé »
SOUS_SECTION = {
    "public": r"\d\s+Public\s*$",
    "prive": r"\d\s+Priv[ée]\s*$",
    "total": r"Public\s*\+\s*Priv",
}


def pages_titres(df: pd.DataFrame, motifs: list[str]) -> list[int]:
    """Pages dont l'en-tête (6 premières lignes) contient tous les titres recherchés."""
    c1 = cellules(df)[0]
    tete = df[(df["ligne"] <= 6) & (df["nb_cellules"] == 1)]
    pages = None
    for motif in motifs:
        p = set(tete.loc[tete[c1].str.contains(motif, case=False, regex=True), "page"])
        pages = p if pages is None else pages & p
    return sorted(pages or [])


def extraire_lignes_province(df: pd.DataFrame, pages: list[int], mesures: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Tableau dont chaque province tient sur une ligne : « BANWA | 415 | 50 | … »."""
    cs = cellules(df)
    bloc = df[df["page"].isin(pages)].sort_values(["page", "ligne"])
    lignes, inconnus = [], []
    region_courante: str | None = None
    attend_national = False
    for _, r in bloc.iterrows():
        v = _valeurs(r, cs)
        if not v:
            continue
        if len(v) == 1:
            if geo.region(v[0]):
                region_courante = geo.region(v[0])
            continue
        k = geo.cle(v[0])
        if k.startswith("TOTALNATIONAL"):
            attend_national = True  # les chiffres suivent, après une répétition de l'en-tête
            continue
        vals = [nombre(x) for x in v]
        if attend_national and len(v) == len(mesures) and all(x is not None for x in vals):
            lignes.append({"niveau": "national", "region": None, "province": None, **dict(zip(mesures, vals)),
                           "page_pdf": int(r["page"])})
            attend_national = False
            continue
        if len(v) != len(mesures) + 1 or any(x is None for x in vals[1:]):
            continue
        if k.startswith("TOTALREGION"):
            niveau, prov, reg = "region", None, region_courante
        elif geo.province(v[0]):
            niveau, prov, reg = "province", geo.province(v[0]), geo.REGION_DE[geo.province(v[0])]
        elif k.startswith("SALLES") or "%" in v[0]:
            continue  # ligne de pourcentages
        else:
            inconnus.append(v[0])
            continue
        lignes.append({"niveau": niveau, "region": reg, "province": prov, **dict(zip(mesures, vals[1:])),
                       "page_pdf": int(r["page"])})
    return pd.DataFrame(lignes), inconnus


def etat_toutes_annees(nom: str) -> pd.DataFrame:
    titre, mesures = TABLEAUX_ETAT[nom]
    tout = []
    for annee, f in annuaires_primaire():
        df = lire_csv(f)
        bilan = []
        for statut, sous_titre in SOUS_SECTION.items():
            tab, inconnus = extraire_lignes_province(df, pages_titres(df, [titre, sous_titre]), mesures)
            tab.insert(0, "annee_scolaire", annee)
            tab.insert(1, "statut", statut)
            nb = tab[tab["niveau"] == "province"]["province"].nunique() if len(tab) else 0
            bilan.append(f"{statut} {nb}" + (f" (non reconnus : {inconnus})" if inconnus else ""))
            tout.append(tab)
        print(f"{nom} {annee} — provinces lues : " + ", ".join(bilan))
    return pd.concat(tout, ignore_index=True)


def controler_etat(tab: pd.DataFrame, mesures: list[str], synthese: pd.DataFrame) -> pd.DataFrame:
    """Somme des provinces = région = national ; nombre de salles = tableau de synthèse."""
    ecarts = []
    prov = tab[tab["niveau"] == "province"]
    sp = prov.groupby(["annee_scolaire", "statut", "region"])[mesures].sum()
    sr = tab[tab["niveau"] == "region"].set_index(["annee_scolaire", "statut", "region"])[mesures]
    for idx in sp.index:
        for m in mesures:
            att = sr.loc[idx, m] if idx in sr.index else float("nan")
            if att != sp.loc[idx, m]:
                ecarts.append({"controle": "somme provinces = region", "annee_scolaire": idx[0], "statut": idx[1],
                               "entite": idx[2], "mesure": m, "attendu": att, "obtenu": sp.loc[idx, m]})
    sn = prov.groupby(["annee_scolaire", "statut"])[mesures].sum()
    nat = tab[tab["niveau"] == "national"].set_index(["annee_scolaire", "statut"])[mesures]
    for idx in sn.index:
        for m in mesures:
            att = nat.loc[idx, m] if idx in nat.index else float("nan")
            if att != sn.loc[idx, m]:
                ecarts.append({"controle": "somme provinces = national", "annee_scolaire": idx[0], "statut": idx[1],
                               "entite": "NATIONAL", "mesure": m, "attendu": att, "obtenu": sn.loc[idx, m]})
    syn = synthese[synthese["niveau"] == "province"].set_index(["annee_scolaire", "statut", "province"])["salles"]
    for _, r in prov.iterrows():
        att = syn.get((r["annee_scolaire"], r["statut"], r["province"]))
        if att != r["salles"]:
            ecarts.append({"controle": "salles = synthese", "annee_scolaire": r["annee_scolaire"], "statut": r["statut"],
                           "entite": r["province"], "mesure": "salles", "attendu": att, "obtenu": r["salles"]})
    return pd.DataFrame(ecarts)


TITRE_HISTORIQUE = r"HISTORIQUE DES EFFECTIFS PAR PROVINCE"
_SEXES = {"GARCONS": "garcons", "FILLES": "filles", "TOTAL": "total"}
_NOM_ET_SEXE = re.compile(r"^(.*\S)\s+(Gar[cç]ons|Filles|Total)$", re.I)
_ANNEE = re.compile(r"^(\d{4})\s*/\s*(?:\d{2,4})?$")  # « 2015/ 2016 », ou « 2004/ » quand l'en-tête est sur deux lignes


def extraire_historique(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Tableau « historique des effectifs par province » : élèves par sexe sur une dizaine d'années.

    Chaque entité occupe trois lignes (Garçons, Filles, Total) ; son nom est écrit sur l'une d'elles.
    """
    cs = cellules(df)
    bloc = df[df["page"].isin(pages_section(df, TITRE_HISTORIQUE))].sort_values(["page", "ligne"])
    lignes, inconnus = [], []
    annees: list[str] = []
    region_courante: str | None = None
    etiquette: str | None = None
    triple: dict[str, list[float | None]] = {}
    for _, r in bloc.iterrows():
        v = _valeurs(r, cs)
        if not v:
            continue
        an = [m.group(1) for x in v if (m := _ANNEE.match(x))]
        if len(an) >= 5:
            annees = [f"{a}-{int(a) + 1}" for a in an]
            continue
        if len(v) == 1:
            if geo.region(v[0]):
                region_courante = geo.region(v[0])
            continue
        if geo.cle(v[0]) in _SEXES:
            sexe, chiffres = _SEXES[geo.cle(v[0])], v[1:]
        elif geo.cle(v[1]) in _SEXES:
            etiquette, sexe, chiffres = v[0], _SEXES[geo.cle(v[1])], v[2:]
        elif (m := _NOM_ET_SEXE.match(v[0])):  # « KOULPELOGO Filles » fusionnés dans une seule cellule
            etiquette, sexe, chiffres = m.group(1), _SEXES[geo.cle(m.group(2))], v[1:]
        else:
            continue
        triple[sexe] = [nombre(x) for x in chiffres]
        if sexe != "total":
            continue
        # fin du bloc de trois lignes : on identifie l'entité et on écrit
        k = geo.cle(etiquette or "")
        if geo.province(etiquette or ""):
            niveau, prov, reg = "province", geo.province(etiquette), geo.REGION_DE[geo.province(etiquette)]
        elif k.startswith("TOTALREGION") or geo.region(etiquette or ""):
            niveau, prov, reg = "region", None, geo.region(etiquette or "") or region_courante
        elif "NATIONAL" in k or "BURKINA" in k or k == "TOTAL":
            niveau, prov, reg = "national", None, None
        else:
            inconnus.append(f"p.{r['page']} l.{r['ligne']} : {etiquette!r}")
            niveau = None
        if niveau:
            for sx, vals in triple.items():
                if len(vals) != len(annees):
                    inconnus.append(f"p.{r['page']} l.{r['ligne']} : {len(vals)} valeurs pour {len(annees)} années ({etiquette}, {sx})")
                    continue
                for a, x in zip(annees, vals):
                    lignes.append({"annee_scolaire": a, "niveau": niveau, "region": reg, "province": prov,
                                   "sexe": sx, "eleves": x, "page_pdf": int(r["page"])})
        etiquette, triple = None, {}
    return pd.DataFrame(lignes), inconnus


def historique_toutes_annees() -> pd.DataFrame:
    tout = []
    for annee, f in annuaires_primaire():
        tab, inconnus = extraire_historique(lire_csv(f))
        tab.insert(0, "annuaire", annee)
        nb = tab[tab["niveau"] == "province"]["province"].nunique() if len(tab) else 0
        an = sorted(tab["annee_scolaire"].unique()) if len(tab) else []
        print(f"annuaire {annee} : {len(tab):>5} lignes, {nb} provinces, {an[0] if an else '?'} à {an[-1] if an else '?'}"
              + (f" — NON RECONNUS ({len(inconnus)}) : {inconnus[:6]}" if inconnus else ""))
        tout.append(tab)
    return pd.concat(tout, ignore_index=True)


def controler_historique(hist: pd.DataFrame, synthese: pd.DataFrame) -> pd.DataFrame:
    """Garçons + filles = total ; somme des provinces = national ; dernière année = tableau de synthèse."""
    ecarts = []
    p = hist[hist["niveau"] == "province"].pivot_table(
        index=["annuaire", "annee_scolaire", "province"], columns="sexe", values="eleves", aggfunc="first").reset_index()
    for _, r in p[p["garcons"] + p["filles"] != p["total"]].iterrows():
        ecarts.append({"controle": "garcons + filles = total", "annuaire": r["annuaire"], "annee_scolaire": r["annee_scolaire"],
                       "entite": r["province"], "attendu": r["total"], "obtenu": r["garcons"] + r["filles"]})
    nat = hist[(hist["niveau"] == "national") & (hist["sexe"] == "total")].set_index(["annuaire", "annee_scolaire"])["eleves"]
    for cle_, s in p.groupby(["annuaire", "annee_scolaire"])["total"].sum().items():
        if cle_ in nat.index and nat[cle_] != s:
            ecarts.append({"controle": "somme provinces = national", "annuaire": cle_[0], "annee_scolaire": cle_[1],
                           "entite": "NATIONAL", "attendu": nat[cle_], "obtenu": s})
    syn = synthese[(synthese["niveau"] == "province") & (synthese["statut"] == "total")].set_index(["annee_scolaire", "province"])["eleves"]
    courant = p[p["annuaire"] == p["annee_scolaire"]]
    for _, r in courant.iterrows():
        attendu = syn.get((r["annee_scolaire"], r["province"]))
        if attendu is None or attendu != r["total"]:
            ecarts.append({"controle": "historique (année courante) = synthèse", "annuaire": r["annuaire"],
                           "annee_scolaire": r["annee_scolaire"], "entite": r["province"], "attendu": attendu, "obtenu": r["total"]})
    return pd.DataFrame(ecarts)


def revisions_historique(hist: pd.DataFrame) -> pd.DataFrame:
    """Valeurs d'une même année qui diffèrent d'un annuaire à l'autre (révisions de la source)."""
    p = hist[(hist["niveau"] == "province") & (hist["sexe"] == "total")]
    g = p.groupby(["annee_scolaire", "province"])["eleves"].agg(["min", "max", "nunique", "count"]).reset_index()
    return g[g["nunique"] > 1]


if __name__ == "__main__":
    synthese = synthese_toutes_annees()
    SORTIE.mkdir(parents=True, exist_ok=True)
    synthese.to_csv(SORTIE / "synthese.csv", index=False, sep=";", encoding="utf-8")
    print(f"\n{len(synthese)} lignes -> data/interim/annuaires/synthese.csv")
    ecarts = controler_synthese(synthese)
    ecarts.to_csv(SORTIE / "synthese_ecarts.csv", index=False, sep=";", encoding="utf-8")
    print(f"\nContrôles : {len(ecarts)} écart(s)")
    if len(ecarts):
        print(ecarts.groupby(["annee_scolaire", "controle"]).size().to_string())
        print(ecarts.head(40).to_string())
    nat = synthese[(synthese["niveau"] == "national") & (synthese["statut"] == "total")]
    print("\nTotaux nationaux publiés :")
    print(nat[["annee_scolaire", "ecoles", "salles", "groupes_pedagogiques", "maitres", "eleves"]].to_string(index=False))

    for nom_tab, (_, mes) in TABLEAUX_ETAT.items():
        print(f"\n--- Nature et état des {nom_tab} ---")
        etat = etat_toutes_annees(nom_tab)
        etat.to_csv(SORTIE / f"{nom_tab}.csv", index=False, sep=";", encoding="utf-8")
        ec = controler_etat(etat, mes, synthese)
        ec.to_csv(SORTIE / f"{nom_tab}_ecarts.csv", index=False, sep=";", encoding="utf-8")
        print(f"Contrôles : {len(ec)} écart(s)")
        if len(ec):
            print(ec.groupby(["controle", "annee_scolaire", "statut"]).size().to_string())
            ec["ecart_relatif"] = (ec["obtenu"] - ec["attendu"]).abs() / ec["attendu"]
            print(f"écart relatif maximal : {ec['ecart_relatif'].max():.2%}")

    print("\n--- Historique des effectifs par province ---")
    hist = historique_toutes_annees()
    hist.to_csv(SORTIE / "historique_effectifs.csv", index=False, sep=";", encoding="utf-8")
    ecarts_h = controler_historique(hist, synthese)
    ecarts_h.to_csv(SORTIE / "historique_ecarts.csv", index=False, sep=";", encoding="utf-8")
    print(f"\nContrôles : {len(ecarts_h)} écart(s)")
    if len(ecarts_h):
        print(ecarts_h.groupby(["controle", "annuaire"]).size().to_string())
        print(ecarts_h.head(25).to_string())
    rev = revisions_historique(hist)
    print(f"\nRévisions entre annuaires : {len(rev)} couples (année, province) sur "
          f"{hist[hist['niveau'] == 'province'].groupby(['annee_scolaire', 'province']).ngroups}")
    if len(rev):
        print(rev.groupby("annee_scolaire").size().to_string())
