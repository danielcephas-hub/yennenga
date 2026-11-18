"""Diagnostic régional du post-primaire (2022-23 et 2023-24, point de départ 2019-20).

Source : tableaux de bord de l'enseignement post-primaire et secondaire de la DGESS
(CNS566 pour 2022-2023, CNS564 pour 2023-2024), seules publications récentes du Data Pack
sur ce cycle. La maille la plus fine est la région (13 régions) ; l'annuaire 2019-2020 ne descend
à la province que pour une partie d'entre elles, d'où le choix de la région.

Les tableaux sont repérés par le titre courant de la page et reconnus par leur nombre de colonnes,
jamais par numéro de page. Chaque tableau est contrôlé : somme des régions = total national, et
valeurs 2023-24 moins la variation annoncée = valeurs 2022-23.

Usage : PYTHONPATH=src python -m dcb.post_primaire
Produit data/processed/post_primaire_region.csv et outputs/controles/post_primaire_controles.csv
"""
from __future__ import annotations

import re

import pandas as pd

from dcb import geo
from dcb.indicateurs import SORTIE, config
from dcb.lecture import CSV, RACINE, cellules, lire_csv, nombre

DOSSIER = CSV / "01_Education_MENAPLN_DGESS" / "CNS_DGESS" / "Tableaux_de_bord"
FICHIERS = {
    "2022-2023": DOSSIER / "CNS566_Tableau_de_bord_statistique_de_lenseignement_post_primaire_et_secondaire_2023.csv",
    "2023-2024": DOSSIER / "CNS564_Tableau_de_bord_statistique_de_lenseignement_Post_Primaire_et_Secondaire_2024.csv",
}
NATIONAL = "BURKINA FASO"
_LIBELLES_NATIONAUX = {"BURKINAFASO", "TOTAL", "NATIONAL", "TOTALNATIONAL", "TOTALGENERAL"}
CONTROLES = RACINE / "outputs" / "controles"

# Tableaux extraits : titre courant de la page, puis noms des colonnes numériques par année
# (leur nombre sert à reconnaître la ligne d'une région).
TABLEAUX = {
    "effectifs_pp": ("EFFECTIFS DES ELEVES AU POST-PRIMAIRE", {
        a: ["garcons_pp", "filles_pp", "eleves_pp", "indice_parite_pp"] for a in FICHIERS}),
    "effectifs_sec": ("EFFECTIFS DES ELEVES DU SECONDAIRE", {
        a: ["garcons_sec", "filles_sec", "eleves_sec", "indice_parite_sec"] for a in FICHIERS}),
    "etablissements": ("NOMBRE D’ETABLISSEMENTS", {
        "2022-2023": ["etablissements", "var_etablissements_n1", "var_etablissements_n1_pct", "_var_ref", "_var_ref_pct"],
        "2023-2024": ["etablissements", "var_etablissements_n1", "var_etablissements_n1_pct",
                      "var_etablissements_2019", "var_etablissements_2019_pct"]}),
    "salles": ("NOMBRE DE SALLES DE CLASSE", {
        "2022-2023": ["salles", "var_salles_n1", "var_salles_n1_pct", "_var_ref", "_var_ref_pct"],
        "2023-2024": ["salles", "var_salles_n1", "var_salles_n1_pct", "var_salles_2019", "var_salles_2019_pct",
                      "pop_scolarisable_par_salle", "pop_scolarisable_par_salle_public"]}),
    "places": ("PLACES ASSISES", {
        "2022-2023": ["eleves_eg_public", "places_assises", "deficit_places", "excedent_places"],
        "2023-2024": ["eleves_eg_public", "places_assises", "deficit_places", "excedent_places",
                      "etablissements_eg_public", "etablissements_en_deficit"]}),
    "ratio_classe": ("CONDITIONS D’ACCUEIL", {
        a: ["eleves_par_classe_6e", "eleves_par_classe_5e", "eleves_par_classe_4e", "eleves_par_classe_3e",
            "eleves_par_classe_pp", "eleves_par_classe_2nde", "eleves_par_classe_1ere", "eleves_par_classe_tle",
            "eleves_par_classe_sec", "eleves_par_classe_total"] for a in FICHIERS}),
    "commodites": ("CONDITIONS D’ACCUEIL", {
        a: ["pct_latrines", "pct_eau_potable", "pct_electricite", "pct_rampes", "pct_bibliotheque"] for a in FICHIERS}),
    "enseignants": ("PERSONNEL ENSEIGNANT", {
        a: ["enseignants", "pct_enseignantes", "pct_qualifies", "enseignants_n1", "var_enseignants_n1_pct",
            "eleves_par_classe_esg_public", "eleves_par_classe_prive", "interventions"] for a in FICHIERS}),
}
# Mesures additives : la somme des régions doit redonner le total national.
ADDITIVES = ["garcons_pp", "filles_pp", "eleves_pp", "garcons_sec", "filles_sec", "eleves_sec", "etablissements",
             "var_etablissements_n1", "var_etablissements_2019", "salles", "var_salles_n1", "var_salles_2019",
             "eleves_eg_public", "places_assises", "deficit_places", "excedent_places", "etablissements_eg_public",
             "etablissements_en_deficit", "enseignants", "enseignants_n1", "interventions"]

# Places assises 2023-24 : dans le tableau imprimé, les quatre régions du Centre portent un libellé décalé.
# Preuves (vérifiées par `_controle_places`) : avec les libellés imprimés, les élèves du public général
# varient de 22 % à 51 % en valeur absolue en un an dans ces régions, contre 13,5 % au plus dans les neuf
# autres ; après correction, de 9 % au plus. Le commentaire du même document situe le plus fort déficit
# « au Centre Nord (14,0 %) », taux de la ligne imprimée « Centre Sud ».
CORRECTION_LIBELLES_PLACES = {
    "2023-2024": {"CENTRE-NORD": "CENTRE-EST", "CENTRE-SUD": "CENTRE-NORD",
                  "CENTRE-EST": "CENTRE-OUEST", "CENTRE-OUEST": "CENTRE-SUD"},
}


def _titre(page: pd.DataFrame, c1: str) -> str:
    return re.sub(r"\s+", " ", str(page.iloc[0][c1])).strip().upper()


def _valeurs(cells: list[str]) -> list[float] | None:
    """Nombres d'une ligne ; un « - » isolé suivi d'un nombre est un signe moins détaché."""
    out, signe = [], 1
    for c in cells:
        if c.strip() in ("-", "–"):
            signe = -1
            continue
        v = nombre(c)
        if v is None:
            return None
        out.append(signe * v)
        signe = 1
    return out


def _libelle(texte: str) -> str | None:
    cle = geo.cle(texte)
    if cle in _LIBELLES_NATIONAUX:
        return NATIONAL
    if cle in ("BOUCLEDU", "BOUCLE"):  # « Boucle du » / « Mouhoun » sur deux lignes
        return "BOUCLE DU MOUHOUN"
    return geo.region(texte)


def extraire_tableau(df: pd.DataFrame, titre: str, colonnes: list[str]) -> pd.DataFrame:
    """Lignes région → valeurs du premier tableau régional à `len(colonnes)` colonnes sous ce titre."""
    cs = cellules(df)
    n = len(colonnes)
    for page, g in df.groupby("page", sort=True):
        if not _titre(g, cs[0]).startswith(titre):
            continue
        lignes, en_attente = {}, None
        for _, r in g.iterrows():
            cells = [r[c] for c in cs if r[c].strip()]
            if not cells:
                continue
            lib = _libelle(cells[0])
            vals = _valeurs(cells[1:]) if lib else _valeurs(cells)
            if lib and vals == [] and lib == "BOUCLE DU MOUHOUN":
                en_attente = lib            # libellé seul, valeurs sur la ligne suivante
                continue
            if lib is None and en_attente and vals is not None and len(vals) == n:
                lib = en_attente
            if lib == NATIONAL and not lignes:
                continue                    # « Total » d'un autre tableau placé avant celui des régions
            if lib and vals is not None and len(vals) == n and lib not in lignes:
                lignes[lib] = vals
            en_attente = None if lib != "BOUCLE DU MOUHOUN" or vals else en_attente
        if len(lignes) == len(geo.REGIONS_PROVINCES) + 1:
            t = pd.DataFrame.from_dict(lignes, orient="index", columns=colonnes)
            t.index.name = "region"
            t["page_source"] = int(page)
            return t.reset_index()
    raise ValueError(f"tableau « {titre} » à {n} colonnes introuvable ou incomplet")


def extraire(annee: str) -> pd.DataFrame:
    df = lire_csv(FICHIERS[annee])
    tables = []
    for nom, (titre, colonnes) in TABLEAUX.items():
        t = extraire_tableau(df, titre, colonnes[annee])
        if nom == "places" and annee in CORRECTION_LIBELLES_PLACES:
            t["region"] = t["region"].replace(CORRECTION_LIBELLES_PLACES[annee])
        tables.append(t.drop(columns=[c for c in t.columns if c.startswith("_")])
                      .rename(columns={"page_source": f"page_{nom}"}).set_index("region"))
    out = pd.concat(tables, axis=1)
    out.insert(0, "annee_scolaire", annee)
    return out.reset_index()


def _controle_places(brut: dict[str, pd.DataFrame]) -> list[dict]:
    """Justifie la correction des libellés par l'évolution annuelle des élèves du public général.

    Référence : le plus grand écart annuel parmi les régions non touchées par la correction. Les régions
    corrigées doivent en sortir nettement avec les libellés imprimés (> 1,5 fois) et y rentrer après correction."""
    corr = CORRECTION_LIBELLES_PLACES["2023-2024"]
    avant = brut["2022-2023"].set_index("region")["eleves_eg_public"]
    corrige = brut["2023-2024"].set_index("region")["eleves_eg_public"]
    imprime = corrige.rename(index={v: k for k, v in corr.items()})
    ecart_c = (corrige / avant - 1).abs().drop(NATIONAL)
    ecart_i = (imprime / avant - 1).abs().drop(NATIONAL)
    touchees = list(corr)
    reference = ecart_c.drop(touchees).max()
    return [
        {"controle": "places assises : plus grand écart annuel des élèves EG public, régions non corrigées (référence)",
         "annee_scolaire": "2023-2024", "valeur": round(reference, 3), "attendu": "", "ok": None},
        {"controle": "places assises : plus petit écart annuel des 4 régions du Centre, libellés imprimés",
         "annee_scolaire": "2023-2024", "valeur": round(ecart_i[touchees].min(), 3),
         "attendu": "> 1,5 × référence", "ok": bool(ecart_i[touchees].min() > 1.5 * reference)},
        {"controle": "places assises : plus grand écart annuel des 4 régions du Centre, libellés corrigés",
         "annee_scolaire": "2023-2024", "valeur": round(ecart_c[touchees].max(), 3),
         "attendu": "<= référence", "ok": bool(ecart_c[touchees].max() <= reference)},
    ]


def controler(t: pd.DataFrame) -> pd.DataFrame:
    lignes = []
    for annee, g in t.groupby("annee_scolaire"):
        g = g.set_index("region")
        reg = g.drop(NATIONAL)
        for m in ADDITIVES:
            if m not in g or g[m].isna().all():
                continue
            ecart = reg[m].sum() - g.loc[NATIONAL, m]
            lignes.append({"controle": f"somme des régions = national : {m}", "annee_scolaire": annee,
                           "valeur": ecart, "attendu": 0, "ok": abs(ecart) <= 2})
        for a, b, c in (("garcons_pp", "filles_pp", "eleves_pp"), ("garcons_sec", "filles_sec", "eleves_sec")):
            ecart = (g[a] + g[b] - g[c]).abs().max()
            lignes.append({"controle": f"garçons + filles = total : {c}", "annee_scolaire": annee,
                           "valeur": ecart, "attendu": 0, "ok": ecart == 0})
    n1 = t[t["annee_scolaire"] == "2022-2023"].set_index("region")
    n = t[t["annee_scolaire"] == "2023-2024"].set_index("region")
    for m, var in (("etablissements", "var_etablissements_n1"), ("salles", "var_salles_n1")):
        ecart = (n[m] - n[var] - n1[m]).abs().max()
        lignes.append({"controle": f"2023-24 moins variation = 2022-23 : {m}", "annee_scolaire": "2023-2024",
                       "valeur": ecart, "attendu": 0, "ok": ecart == 0})
    ecart = (n["enseignants_n1"] - n1["enseignants"]).abs().max()
    lignes.append({"controle": "effectif 2022-23 repris en 2023-24 = effectif 2022-23 : enseignants",
                   "annee_scolaire": "2023-2024", "valeur": ecart, "attendu": 0, "ok": ecart == 0})
    return pd.DataFrame(lignes)


def indicateurs(t: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    p = cfg["post_primaire"]
    t = t.copy()
    t["eleves_pp_sec"] = t["eleves_pp"] + t["eleves_sec"]
    # Non comparable entre régions : les enseignants comptés excluent les vacataires, nombreux dans le privé.
    t["eleves_par_enseignant_hors_vacataires"] = t["eleves_pp_sec"] / t["enseignants"]
    t["eleves_par_salle"] = t["eleves_pp_sec"] / t["salles"]
    t["part_eleves_sans_place"] = t["deficit_places"] / t["eleves_eg_public"]
    t["excedent_net_places"] = t["places_assises"] - t["eleves_eg_public"]
    t["etablissements_2019"] = t["etablissements"] - t["var_etablissements_2019"]
    t["salles_2019"] = t["salles"] - t["var_salles_2019"]
    t["evolution_etablissements_2019"] = t["var_etablissements_2019"] / t["etablissements_2019"]
    t["evolution_salles_2019"] = t["var_salles_2019"] / t["salles_2019"]
    norme = p["norme_eleves_par_classe"]
    t["ecart_norme_6e"] = t["eleves_par_classe_6e"] - norme
    t["signal_6e_au_dessus_norme"] = t["eleves_par_classe_6e"] > norme
    t["signal_places_manquantes"] = t["part_eleves_sans_place"] > p["seuil_part_sans_place"]
    t["signal_perte_etablissements"] = t["evolution_etablissements_2019"] < -p["seuil_perte_etablissements"]
    signaux = [c for c in t.columns if c.startswith("signal_")]
    recent = t["annee_scolaire"] == max(FICHIERS)
    t.loc[recent, "nombre_signaux"] = t.loc[recent, signaux].sum(axis=1)
    for c in signaux:
        t[c] = t[c].astype("boolean")
        t.loc[~recent, c] = pd.NA  # seuils évalués sur la dernière année seulement
    return t


def produire() -> pd.DataFrame:
    cfg = config()
    brut = {a: extraire(a) for a in FICHIERS}
    t = pd.concat(brut.values(), ignore_index=True)
    ctrl = pd.concat([controler(t), pd.DataFrame(_controle_places(brut))], ignore_index=True)
    CONTROLES.mkdir(parents=True, exist_ok=True)
    ctrl.to_csv(CONTROLES / "post_primaire_controles.csv", sep=";", index=False, encoding="utf-8")
    echecs = ctrl[ctrl["ok"] == False]  # noqa: E712 (None = contrôle informatif)
    if not echecs.empty:
        raise ValueError("contrôles du post-primaire en échec :\n" + echecs.to_string(index=False))
    t = indicateurs(t, cfg)
    t["niveau"] = (t["region"] == NATIONAL).map({True: "national", False: "region"})
    cols = ["annee_scolaire", "niveau", "region"] + [c for c in t.columns if c not in ("annee_scolaire", "niveau", "region")
                                                       and not c.startswith("page_")]
    t = t[cols + [c for c in t.columns if c.startswith("page_")]]
    SORTIE.mkdir(parents=True, exist_ok=True)
    t.to_csv(SORTIE / "post_primaire_region.csv", sep=";", index=False, encoding="utf-8")
    return t, ctrl


if __name__ == "__main__":
    t, ctrl = produire()
    print(f"{len(ctrl)} contrôles, {int((ctrl['ok'] == True).sum())} réussis, "  # noqa: E712
          f"{int(ctrl['ok'].isna().sum())} informatifs")
    print(ctrl[ctrl["ok"].isna()][["controle", "valeur"]].to_string(index=False))
    r = t[t["annee_scolaire"] == max(FICHIERS)].set_index("region")
    vues = ["eleves_pp", "etablissements", "evolution_etablissements_2019", "salles", "eleves_par_classe_6e",
            "eleves_par_classe_pp", "part_eleves_sans_place", "pct_eau_potable", "pct_latrines", "nombre_signaux"]
    with pd.option_context("display.width", 200, "display.float_format", "{:.2f}".format):
        print(r[vues].sort_values("nombre_signaux", ascending=False).to_string())
