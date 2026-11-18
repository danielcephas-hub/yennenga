"""Prévision des effectifs par province jusqu'à l'horizon, avec test sur le passé.

Principe : plusieurs méthodes simples sont mises en concurrence sur le passé (on se place à une année
ancienne, on prévoit les suivantes, on compare au réalisé). Une méthode n'est retenue que si elle fait
mieux que la référence naïve « l'effectif ne bouge pas ». Les marges d'incertitude viennent des erreurs
observées dans ce test, par horizon.

Méthodes :
- naive               : l'effectif reste celui de la dernière année ;
- tendance_lineaire   : prolongement de la pente des dernières années ;
- croissance_amortie  : taux de croissance récent, réduit de moitié chaque année ;
- demographique       : l'effectif suit la population de 6 à 11 ans projetée par l'INSD (taux de scolarisation constant).

La méthode démographique ne peut être testée que depuis 2019-2020 (les projections commencent en 2020) :
la comparaison qui sert au choix est donc faite sur les cas communs à toutes les méthodes.

Usage : PYTHONPATH=src python -m dcb.prevision   (après dcb.indicateurs et dcb.demographie)
Produit data/processed/prevision_effectifs.csv, prevision_fiabilite.csv, prevision_test.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dcb.indicateurs import SORTIE, config
from dcb.lecture import RACINE

INTERIM_DEMO = RACINE / "data" / "interim" / "demographie"
HISTORIQUE_MINIMAL = 8  # années d'historique exigées avant de prévoir, dans le test sur le passé
DEMOGRAPHIQUE = "demographique"


def _naive(y: np.ndarray, h: int, k: int) -> float:
    return float(y[-1])


def _tendance_lineaire(y: np.ndarray, h: int, k: int) -> float:
    z = y[-k:]
    pente = np.polyfit(np.arange(len(z)), z, 1)[0]
    return float(max(0.0, y[-1] + pente * h))


def _croissance_amortie(y: np.ndarray, h: int, k: int) -> float:
    """Taux de croissance moyen des k dernières années, amorti de moitié à chaque année supplémentaire."""
    z = y[-k:]
    if z[0] <= 0 or z[-1] <= 0:
        return float(y[-1])
    g = (z[-1] / z[0]) ** (1 / (len(z) - 1)) - 1
    g = float(np.clip(g, -0.15, 0.15))
    facteur = np.prod([1 + g * 0.5 ** i for i in range(h)])
    return float(y[-1] * facteur)


METHODES = {"naive": _naive, "tendance_lineaire": _tendance_lineaire, "croissance_amortie": _croissance_amortie}


def population_scolarisable() -> dict[str, dict[int, float]]:
    """Population de 6 à 11 ans par province et par année civile (projections INSD), si elle a été extraite."""
    f = INTERIM_DEMO / "population_6_11_province.csv"
    if not f.exists():
        return {}
    t = pd.read_csv(f, sep=";", encoding="utf-8")
    t = t[t["niveau"] == "province"]
    return {p: dict(zip(g["annee"], g["population_6_11"])) for p, g in t.groupby("entite")}


def _demographique(dernier_effectif: float, debut: int, h: int, pop: dict[int, float]) -> float | None:
    """Taux de scolarisation constant : l'effectif suit la population de 6 à 11 ans.

    L'année scolaire qui commence en `debut` est rapportée à la population de l'année civile `debut + 1`."""
    a, b = pop.get(debut + 1), pop.get(debut + 1 + h)
    if not a or not b:
        return None
    return float(dernier_effectif * b / a)


def prevoir_un(methode: str, hist: np.ndarray, debut: int, h: int, k: int, pop: dict[int, float]) -> float | None:
    if methode == DEMOGRAPHIQUE:
        return _demographique(float(hist[-1]), debut, h, pop)
    return METHODES[methode](hist, h, k)


def _annee(debut: int) -> str:
    return f"{debut}-{debut + 1}"


def matrice(serie: pd.DataFrame) -> pd.DataFrame:
    """Provinces en lignes, année de début en colonnes."""
    s = serie.assign(debut=serie["annee_scolaire"].str[:4].astype(int))
    return s.pivot(index="province", columns="debut", values="eleves").sort_index(axis=1)


def test_sur_le_passe(m: pd.DataFrame, k: int, horizon_max: int, pops: dict) -> pd.DataFrame:
    """Une ligne par (méthode, province, année d'origine, horizon) : prévu et réalisé."""
    annees = list(m.columns)
    noms = [*METHODES, DEMOGRAPHIQUE]
    lignes = []
    for i in range(HISTORIQUE_MINIMAL - 1, len(annees) - 1):
        for prov, y in m.iterrows():
            hist = y.iloc[: i + 1].to_numpy(dtype=float)
            if np.isnan(hist).any():
                continue
            for h in range(1, horizon_max + 1):
                if i + h >= len(annees) or np.isnan(y.iloc[i + h]):
                    continue
                for nom in noms:
                    p = prevoir_un(nom, hist, annees[i], h, k, pops.get(prov, {}))
                    if p is not None:
                        lignes.append({"methode": nom, "province": prov, "origine": annees[i], "horizon": h,
                                       "prevu": p, "realise": float(y.iloc[i + h])})
    return pd.DataFrame(lignes)


def fiabilite(test: pd.DataFrame) -> pd.DataFrame:
    """Erreur pondérée (WAPE) par méthode et par horizon : somme des écarts absolus / somme des réalisés."""
    t = test.assign(ecart=(test["prevu"] - test["realise"]).abs())
    g = t.groupby(["methode", "horizon"]).agg(ecart=("ecart", "sum"), realise=("realise", "sum"), cas=("ecart", "size"))
    g["wape"] = g["ecart"] / g["realise"]
    return g.reset_index()[["methode", "horizon", "wape", "cas"]]


def cas_communs(test: pd.DataFrame) -> pd.DataFrame:
    """Restreint le test aux cas (province, origine, horizon) que toutes les méthodes ont pu prévoir."""
    cle = ["province", "origine", "horizon"]
    nb = test.groupby(cle)["methode"].nunique()
    complets = nb[nb == test["methode"].nunique()].index
    return test.set_index(cle).loc[complets].reset_index()


def groupes(m: pd.DataFrame, cfg: dict) -> pd.Series:
    """Classe chaque province : « choc » si son effectif a chuté brutalement d'une année sur l'autre, sinon « stable ».

    Les provinces touchées par des fermetures d'écoles ne se prévoient pas comme les autres : on les évalue à part."""
    p = cfg["prevision"]
    recent = m.loc[:, m.columns >= p["choc_depuis"]]
    chute = recent.pct_change(axis=1).min(axis=1) < -p["choc_seuil_baisse"]
    return chute.map({True: "choc", False: "stable"}).rename("groupe")


def prevoir(serie: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    m = matrice(serie)
    pops = population_scolarisable()
    k = cfg["prevision"]["fenetre_tendance"]
    dernier = int(cfg["annee_reference"][:4])
    horizon = int(cfg["annee_horizon"][:4]) - dernier
    grp = groupes(m, cfg)
    test = test_sur_le_passe(m, k, horizon, pops)
    test["groupe"] = test["province"].map(grp)
    commun = cas_communs(test)
    morceaux = [fiabilite(test).assign(perimetre="tous_les_cas", groupe="ensemble"),
                fiabilite(commun).assign(perimetre="cas_communs", groupe="ensemble")]
    for g in ("stable", "choc"):
        morceaux.append(fiabilite(test[test["groupe"] == g]).assign(perimetre="tous_les_cas", groupe=g))
        morceaux.append(fiabilite(commun[commun["groupe"] == g]).assign(perimetre="cas_communs", groupe=g))
    fiab = pd.concat(morceaux, ignore_index=True)

    # choix par groupe : plus faible erreur moyenne sur les cas communs à toutes les méthodes ;
    # la référence naïve l'emporte si rien ne fait mieux qu'elle
    retenue, fiab["retenue"] = {}, False
    for g in ("stable", "choc"):
        f = fiab[(fiab["perimetre"] == "cas_communs") & (fiab["groupe"] == g)]
        retenue[g] = f.groupby("methode")["wape"].mean().idxmin()
        fiab.loc[(fiab["groupe"] == g) & (fiab["methode"] == retenue[g]), "retenue"] = True

    # marges : quantiles du rapport réalisé / prévu, par groupe et par horizon, pour la méthode retenue
    marges = {}
    for g in ("stable", "choc"):
        tr = test[(test["groupe"] == g) & (test["methode"] == retenue[g]) & (test["prevu"] > 0)]
        rapport = (tr["realise"] / tr["prevu"]).groupby(tr["horizon"])
        marges[g] = (rapport.quantile(0.10), rapport.quantile(0.90))

    lignes = []
    part_rattrapage = cfg["prevision"].get("part_rattrapage_reouverture", 0.5)
    pic = m.max(axis=1)
    for prov, y in m.iterrows():
        g = grp[prov]
        bas, haut = marges[g]
        h_connu = int(bas.index.max())  # au-delà du plus long horizon testé, on garde la marge de celui-ci
        hist = y.loc[:dernier].to_numpy(dtype=float)
        hist = hist[~np.isnan(hist)]
        for h in range(1, horizon + 1):
            central = prevoir_un(retenue[g], hist, dernier, h, k, pops.get(prov, {}))
            if central is None:
                central = float(hist[-1])
            # scénario de réouverture : la province rattrape progressivement une part de l'écart à son maximum historique
            ecart_pic = max(0.0, pic[prov] - central)
            reouverture = central + part_rattrapage * ecart_pic * h / horizon
            hq = min(h, h_connu)
            for scenario, valeur in (("tendance", central), ("reouverture", reouverture)):
                lignes.append({"scenario": scenario, "annee_scolaire": _annee(dernier + h), "province": prov, "groupe": g,
                               "horizon": h, "eleves_prevus": round(valeur), "borne_basse": round(valeur * bas[hq]),
                               "borne_haute": round(valeur * haut[hq]), "methode": retenue[g]})
    return pd.DataFrame(lignes), fiab, test, retenue


if __name__ == "__main__":
    cfg = config()
    serie = pd.read_csv(SORTIE / "serie_effectifs_province.csv", sep=";", encoding="utf-8")
    prev, fiab, test, retenue = prevoir(serie, cfg)
    prev.to_csv(SORTIE / "prevision_effectifs.csv", index=False, sep=";", encoding="utf-8")
    fiab.to_csv(SORTIE / "prevision_fiabilite.csv", index=False, sep=";", encoding="utf-8")
    test.round(1).to_csv(SORTIE / "prevision_test.csv", index=False, sep=";", encoding="utf-8")
    for perimetre, g in (("tous_les_cas", "ensemble"), ("cas_communs", "stable"), ("cas_communs", "choc")):
        f = fiab[(fiab["perimetre"] == perimetre) & (fiab["groupe"] == g)]
        print(f"\nErreur (WAPE) par méthode et horizon — {perimetre}, provinces : {g}")
        print(f.pivot(index="methode", columns="horizon", values="wape").round(3).to_string())
        print("nombre de cas :", f.groupby("methode")["cas"].sum().to_dict())
    print(f"\nMéthodes retenues : {retenue} ; provinces : {prev.drop_duplicates('province')['groupe'].value_counts().to_dict()}")
    nat = prev.groupby(["scenario", "annee_scolaire"])["eleves_prevus"].sum().unstack(0)
    print(nat.to_string())
