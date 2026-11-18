"""Répartition de N enseignants et M salles entre les provinces : programme linéaire en nombres entiers.

Variables : enseignants et salles attribués à chaque province (entiers).
Objectif  : réduire le nombre d'élèves au-delà des normes à l'horizon, avec une pénalité qui croît
            quand le dépassement s'aggrave (les provinces les plus surchargées passent d'abord).
Contraintes : N, M, budget éventuel, un maître par salle, zones où l'on ne construit pas, capacité d'absorption.
On ne construit pas : (1) là où l'effectif est tombé sous `seuil_acces_construction` de son maximum (accès trop
dégradé) ; (2) là où la province a perdu plus de `implantation.seuil_fermeture_rouvrir` de ses écoles ouvertes :
la réponse y est de rouvrir ou délocaliser les écoles fermées, comme le recommande la carte des sites.
Comparaisons, à moyens strictement égaux : répartition proportionnelle aux effectifs, et répartition au
prorata des besoins (enseignants et salles manquants), soumise aux mêmes règles que l'optimisation.

Usage : PYTHONPATH=src python -m dcb.optimisation   (après dcb.indicateurs et dcb.prevision)
Produit data/processed/allocation.csv et allocation_bilan.csv
"""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import pulp

from dcb.territoire import nom_officiel

from dcb.indicateurs import SORTIE, config


def donnees_probleme(table: pd.DataFrame, prevision: pd.DataFrame, cfg: dict, scenario: str | None = None,
                     recul_prive: float = 0.0) -> pd.DataFrame:
    """Une ligne par province : dotation actuelle du secteur cible et élèves attendus à l'horizon.

    `recul_prive` (entre 0 et 1) : part des élèves du privé qui passent dans le public d'ici l'horizon (fermetures,
    frais de scolarité). 0 = la part du privé de l'année de référence est supposée stable."""
    opt = cfg["optimisation"]
    scenario = scenario or opt["scenario_demande"]
    ref = table[table["annee_scolaire"] == cfg["annee_reference"]]
    cible = ref[ref["statut"] == cfg["statut_cible"]].set_index("province")
    total = ref[ref["statut"] == "total"].set_index("province")
    part_cible = (cible["eleves"] / total["eleves"]).fillna(1.0)  # part du secteur cible, supposée stable
    if recul_prive and cfg["statut_cible"] == "public":
        part_cible = part_cible + (1 - part_cible) * float(recul_prive)  # le privé perd cette part de ses élèves
    p = prevision[(prevision["scenario"] == scenario) & (prevision["annee_scolaire"] == cfg["annee_horizon"])]
    prevu = p.set_index("province")["eleves_prevus"]
    d = pd.DataFrame({
        "region": cible["region"],
        "eleves_actuels": cible["eleves"],
        "maitres": cible["maitres"],
        "salles": cible["salles"],
        "eleves_horizon": (prevu * part_cible).round(),
        "part_du_pic": cible["part_du_pic"],
    })
    # même règle que la carte des sites : au-delà du seuil d'écoles fermées, rouvrir d'abord plutôt que construire
    tot = table[table["statut"] == "total"]
    ouvertes = tot[tot["annee_scolaire"] == cfg["annee_reference"]].set_index("province")["ecoles"]
    d["part_ecoles_fermees"] = (1 - ouvertes / tot.groupby("province")["ecoles"].max()).reindex(d.index)
    d["acces_construction"] = d["part_du_pic"].fillna(0) >= opt["seuil_acces_construction"]
    d["rouvrir_d_abord"] = d["part_ecoles_fermees"].fillna(0) > cfg["implantation"]["seuil_fermeture_rouvrir"]
    d["construction_possible"] = d["acces_construction"] & ~d["rouvrir_d_abord"]
    # salles à rouvrir : salles du secteur cible perdues depuis le maximum 2017-2025 (écoles fermées). Là où l'on
    # rouvre d'abord et où l'accès le permet, elles accueillent les enseignants envoyés avec la réouverture.
    # Elles ne comptent pas dans le ratio élèves par salle (leur état n'est pas connu) et leur remise en état
    # n'est pas chiffrée (HYPOTHESE, voir la note).
    salles_max = table[table["statut"] == cfg["statut_cible"]].groupby("province")["salles"].max().reindex(d.index)
    recup = (salles_max - d["salles"]).clip(lower=0).fillna(0)
    rouvrables = d["rouvrir_d_abord"] & d["acces_construction"] & bool(opt.get("compter_salles_a_rouvrir", True))
    d["salles_a_rouvrir"] = recup.where(rouvrables, 0).astype(int)
    return d.reset_index()


def repartition_proportionnelle(poids: pd.Series, total: int) -> pd.Series:
    """Répartition entière proportionnelle aux poids (méthode du plus fort reste)."""
    brut = poids / poids.sum() * total
    base = np.floor(brut).astype(int)
    reste = int(total - base.sum())
    ordre = (brut - base).sort_values(ascending=False).index[:reste]
    base.loc[ordre] += 1
    return base


def paliers(opt: dict) -> list[tuple[float, float]]:
    """Paliers de la pénalité : liste explicite, ou grille régulière {debut, fin, pas, poids}.

    Une grille fine approche une pénalité quadratique de la surcharge : elle départage les provinces
    au lieu de laisser des solutions équivalentes, et sert d'abord les plus chargées."""
    p = opt["paliers"]
    if isinstance(p, dict):
        k = int(round((p["fin"] - p["debut"]) / p["pas"]))
        return [(round(p["debut"] + i * p["pas"], 6), float(p.get("poids", 1.0))) for i in range(k + 1)]
    return [(float(q["multiple_norme"]), float(q["poids"])) for q in p]


CLES_BORNES = ("min_enseignants", "max_enseignants", "min_salles", "max_salles")


def _poser_bornes(prob, d: pd.DataFrame, x: dict, y: dict, contraintes: dict | None) -> None:
    """Contraintes du décideur : planchers et plafonds par province ou par région.

    contraintes = {"provinces": {nom: {min_enseignants, max_enseignants, min_salles, max_salles}}, "regions": {...}}"""
    for niveau, colonne in (("provinces", "province"), ("regions", "region")):
        for nom, bornes in ((contraintes or {}).get(niveau) or {}).items():
            idx = list(d.index[d[colonne] == nom])
            if not idx:
                raise ValueError(f"{'Province' if colonne == 'province' else 'Région'} inconnue dans les exigences : "
                                 f"{nom_officiel(nom)}.")
            for cle, valeur in bornes.items():
                if cle not in CLES_BORNES:
                    raise ValueError(f"Exigence inconnue : {cle}.")
                if valeur is None:
                    continue
                if niveau == "provinces" and cle.startswith("min") and valeur > 0:
                    _verifier_plancher(d, idx[0], nom, cle, valeur)
                somme = pulp.lpSum((x if cle.endswith("enseignants") else y)[i] for i in idx)
                prob += (somme >= valeur) if cle.startswith("min") else (somme <= valeur)


def _verifier_plancher(d: pd.DataFrame, i, nom: str, cle: str, valeur: int) -> None:
    """Explique un plancher impossible au lieu d'un échec muet du solveur."""
    if "construction_possible" in d.columns and not d.loc[i, "construction_possible"]:
        if cle == "min_salles":
            raise ValueError(f"{nom_officiel(nom)} : aucune salle neuve n'y est programmée (accès trop dégradé, ou écoles "
                             f"fermées à rouvrir d'abord). Retirer le plancher de salles de cette province.")
        capacite = max(0, int(d.loc[i, "salles"] - d.loc[i, "maitres"])) + _rouvrables(d, i)
        if valeur > capacite:
            raise ValueError(f"{nom_officiel(nom)} : au plus {capacite} enseignants peuvent y être accueillis (salles libres "
                             f"et salles d'écoles fermées à rouvrir) ; {valeur} sont demandés. Abaisser ce plancher.")


def optimiser(d: pd.DataFrame, cfg: dict, n: int | None = None, m: int | None = None,
              budget: float | None = None, contraintes: dict | None = None,
              redeploiement: int = 0) -> tuple[pd.DataFrame, str]:
    """`redeploiement` : nombre maximal d'enseignants en poste que l'on peut déplacer. Ils ne quittent qu'une
    province qui reste à la norme ou en dessous à l'horizon (excédent = maîtres − élèves / norme), et doivent
    trouver une salle à l'arrivée, comme les recrues. Un déplacement n'a pas de coût de poste."""
    opt, normes = cfg["optimisation"], cfg["normes"]
    n = opt["enseignants_a_repartir"] if n is None else n
    m = opt["salles_a_construire"] if m is None else m
    budget = opt["budget_fcfa"] if budget is None else budget
    nm, ns = normes["eleves_par_maitre"], normes["eleves_par_salle"]
    prob = pulp.LpProblem("repartition", pulp.LpMinimize)
    idx = list(d.index)
    x = pulp.LpVariable.dicts("enseignants", idx, lowBound=0, cat="Integer")
    y = pulp.LpVariable.dicts("salles", idx, lowBound=0, cat="Integer")
    objectif = []
    nm0 = normes["eleves_par_maitre"]
    excedent = {i: max(0, int(d.loc[i, "maitres"] - math.ceil(d.loc[i, "eleves_horizon"] / nm0))) for i in idx}
    if redeploiement:
        r_in = pulp.LpVariable.dicts("redeployes_entrants", idx, lowBound=0, cat="Integer")
        r_out = {i: pulp.LpVariable(f"redeployes_sortants_{i}", lowBound=0, upBound=excedent[i], cat="Integer") for i in idx}
        prob += pulp.lpSum(r_in.values()) == pulp.lpSum(r_out.values())
        prob += pulp.lpSum(r_out.values()) <= int(redeploiement)
        # un déplacement inutile coûte un peu : on ne déplace que si cela soulage une province
        objectif += [1e-3 * r_out[i] for i in idx]
    else:
        r_in = r_out = {i: 0 for i in idx}
    for i in idx:
        e, t, s = d.loc[i, "eleves_horizon"], d.loc[i, "maitres"], d.loc[i, "salles"]
        for k, (mult, poids) in enumerate(paliers(opt)):
            dt = pulp.LpVariable(f"hors_norme_maitre_{i}_{k}", lowBound=0)
            ds = pulp.LpVariable(f"hors_norme_salle_{i}_{k}", lowBound=0)
            prob += dt >= e - nm * mult * (t + x[i] + r_in[i] - r_out[i])
            prob += ds >= e - ns * mult * (s + y[i])
            objectif += [poids * dt, poids * ds]
        if opt["un_maitre_par_salle"]:
            prob += x[i] + r_in[i] <= max(0, s - t) + y[i] + _rouvrables(d, i)
        if not d.loc[i, "construction_possible"]:
            prob += y[i] == 0
        if opt["absorption_max_part"] is not None:
            prob += x[i] <= math.ceil(opt["absorption_max_part"] * t)
    # Départage : à pénalité égale, le moyen va à la province la plus chargée avant répartition. Chaque moyen
    # coûte un peu (au plus `departage`, très en deçà d'un élève), d'autant moins que la province est chargée :
    # aucun moyen n'est attribué sans gain, et le plan devient unique (indépendant de l'ordre des provinces).
    eps = opt.get("departage", 0.0)
    departage = []
    if eps:
        r_t = (d["eleves_horizon"] / d["maitres"].where(d["maitres"] > 0)).fillna(0)
        r_s = (d["eleves_horizon"] / d["salles"].where(d["salles"] > 0)).fillna(0)
        r_t, r_s = r_t / max(r_t.max(), 1e-9), r_s / max(r_s.max(), 1e-9)
        departage = [(1.5 - r_t[i]) * x[i] + (1.5 - r_s[i]) * y[i] for i in idx]
    prob += pulp.lpSum(x.values()) <= n
    prob += pulp.lpSum(y.values()) <= m
    _poser_bornes(prob, d, x, y, contraintes)
    if budget is not None:
        # une salle se paie une fois, un poste chaque année : il est compté sur `annees_budget` années
        cout_poste = opt["cout_enseignant_fcfa"] * opt.get("annees_budget", 1)
        prob += cout_poste * pulp.lpSum(x.values()) + opt["cout_salle_fcfa"] * pulp.lpSum(y.values()) <= budget
    debut = time.perf_counter()
    limite = opt["temps_limite_s"]
    principal = pulp.lpSum(objectif)
    prob.setObjective(principal)
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=limite, gapRel=opt.get("ecart_relatif_tolere")))
    statut = _statut(prob)  # le statut est celui du critère principal ; le départage ne fait que choisir entre ex aequo
    variables = [*x.values(), *y.values()] + ([*r_in.values(), *r_out.values()] if redeploiement else [])
    premier = {v.name: v.value() for v in variables}
    departage_complet = None
    if departage and statut in ("Optimal", "Non prouvé optimal"):
        # deuxième temps : parmi les plans de même pénalité (à la tolérance près), le plus favorable aux provinces
        # les plus chargées. Le plan devient unique, quel que soit l'ordre des provinces ou la tolérance du solveur.
        # Temps borné ; sans solution dans ce temps, on garde le plan du premier temps (aussi bon sur le critère).
        v = pulp.value(principal)
        prob += principal <= v + max(abs(v) * (opt.get("ecart_relatif_tolere") or 0), 1e-6) + 1e-6
        prob.setObjective(pulp.lpSum(departage))
        prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=max(5, limite / 3), gapRel=opt.get("ecart_relatif_tolere")))
        departage_complet = _statut(prob) == "Optimal"
        if _statut(prob) not in ("Optimal", "Non prouvé optimal"):
            for var in variables:
                var.varValue = premier[var.name]
    duree = time.perf_counter() - debut
    res = d.copy()
    res["enseignants_attribues"] = [int(round(x[i].value() or 0)) for i in idx]
    res["salles_attribuees"] = [int(round(y[i].value() or 0)) for i in idx]
    if redeploiement:
        res["redeployes_entrants"] = [int(round(r_in[i].value() or 0)) for i in idx]
        res["redeployes_sortants"] = [int(round(r_out[i].value() or 0)) for i in idx]
    res["solde_redeploiement"] = res.get("redeployes_entrants", 0) - res.get("redeployes_sortants", 0)
    res["salles_rouvertes"] = _salles_rouvertes(res)
    res.attrs["departage_complet"] = departage_complet
    res.attrs.update(statut=statut, duree_s=round(duree, 2))
    return res, statut


def _statut(prob) -> str:
    """« Optimal » seulement si le solveur l'a prouvé : arrêté par la limite de temps, il renvoie une solution
    entière dont l'optimalité n'est pas démontrée (sol_status = 2)."""
    if prob.status == pulp.LpStatusOptimal and prob.sol_status == pulp.LpSolutionOptimal:
        return "Optimal"
    if prob.sol_status == pulp.LpSolutionIntegerFeasible:
        return "Non prouvé optimal"
    return pulp.LpStatus[prob.status]


def _rouvrables(d: pd.DataFrame, i) -> int:
    return int(d.loc[i, "salles_a_rouvrir"]) if "salles_a_rouvrir" in d.columns else 0


def _salles_rouvertes(res: pd.DataFrame) -> pd.Series:
    """Salles d'écoles fermées à rouvrir pour loger les enseignants attribués au-delà des salles libres et construites."""
    if "salles_a_rouvrir" not in res.columns:
        return pd.Series(0, index=res.index)
    libres = np.maximum(0, res["salles"] - res["maitres"]) + res["salles_attribuees"]
    arrivees = res["enseignants_attribues"] + (res["redeployes_entrants"] if "redeployes_entrants" in res else 0)
    return np.minimum(res["salles_a_rouvrir"], np.maximum(0, arrivees - libres)).astype(int)


def effectif_apres(res: pd.DataFrame) -> pd.Series:
    """Maîtres à l'horizon : en poste + recrues affectées + solde des redéploiements."""
    solde = res["solde_redeploiement"].fillna(0) if "solde_redeploiement" in res else 0
    return res["maitres"] + res["enseignants_attribues"] + solde


def proportionnelle(d: pd.DataFrame, n: int, m: int) -> pd.DataFrame:
    """Référence : mêmes moyens, répartis au prorata des élèves attendus."""
    res = d.copy()
    res["enseignants_attribues"] = repartition_proportionnelle(d["eleves_horizon"], n)
    res["salles_attribuees"] = repartition_proportionnelle(d["eleves_horizon"], m)
    return res


def au_prorata_des_besoins(d: pd.DataFrame, cfg: dict, n: int, m: int) -> pd.DataFrame:
    """Référence « règle simple » : mêmes moyens, au prorata des enseignants et salles manquants à l'horizon,
    avec les mêmes règles que l'optimisation (pas de construction là où elle est exclue, un maître par salle).
    Les enseignants qu'une province ne peut pas accueillir faute de salle sont reportés sur les autres."""
    opt, normes = cfg["optimisation"], cfg["normes"]
    e, t, s = d["eleves_horizon"], d["maitres"], d["salles"]
    besoin_t = np.maximum(0, np.ceil(e / normes["eleves_par_maitre"]) - t)
    besoin_s = np.maximum(0, np.ceil(e / normes["eleves_par_salle"]) - s).where(d["construction_possible"], 0)
    y = repartition_proportionnelle(besoin_s, m) if besoin_s.sum() > 0 else pd.Series(0, index=d.index)
    rouvrables = d["salles_a_rouvrir"] if "salles_a_rouvrir" in d.columns else 0
    capacite = (np.maximum(0, s - t) + y + rouvrables) if opt["un_maitre_par_salle"] else pd.Series(np.inf, index=d.index)
    if opt["absorption_max_part"] is not None:
        capacite = np.minimum(capacite, np.ceil(opt["absorption_max_part"] * t))
    x = pd.Series(0, index=d.index, dtype=int)
    reste = int(n)
    while reste > 0:
        actives = (besoin_t > x) & (x < capacite)
        if not actives.any():
            break
        part = repartition_proportionnelle((besoin_t - x)[actives], reste)
        nouveau = np.minimum(x[actives] + part, capacite[actives]).astype(int)
        place = int((nouveau - x[actives]).sum())
        if place == 0:
            break
        x[actives] = nouveau
        reste -= place
    res = d.copy()
    res["enseignants_attribues"] = x.astype(int)
    res["salles_attribuees"] = y.astype(int)
    res["salles_rouvertes"] = _salles_rouvertes(res)
    return res


def _gini_pondere(x: pd.Series, w: pd.Series) -> float:
    """Indice de Gini de x, chaque province pesant son nombre d'élèves (0 = égalité parfaite)."""
    x, w = x.to_numpy(float), w.to_numpy(float)
    moyenne = np.average(x, weights=w)
    return float((w[:, None] * w[None, :] * np.abs(x[:, None] - x[None, :])).sum() / (2 * w.sum() ** 2 * moyenne))


def evaluer(res: pd.DataFrame, cfg: dict) -> dict:
    """Indicateurs d'impact d'une répartition, à l'horizon."""
    nm, ns = cfg["normes"]["eleves_par_maitre"], cfg["normes"]["eleves_par_salle"]
    e = res["eleves_horizon"]
    t = effectif_apres(res)
    s = res["salles"] + res["salles_attribuees"]
    rm, rs = (e / t).where(t > 0), (e / s).where(s > 0)
    ok = rm.notna() & (e > 0)
    return {
        "enseignants_attribues": int(res["enseignants_attribues"].sum()),
        "salles_attribuees": int(res["salles_attribuees"].sum()),
        "salles_rouvertes": int(res["salles_rouvertes"].sum()) if "salles_rouvertes" in res else 0,
        "enseignants_redeployes": int(res["redeployes_sortants"].fillna(0).sum()) if "redeployes_sortants" in res else 0,
        "eleves_au_dela_norme_maitre": float(np.maximum(0, e - nm * t).sum()),
        "eleves_au_dela_norme_salle": float(np.maximum(0, e - ns * s).sum()),
        "provinces_au_dessus_norme_maitre": int((rm > nm).sum()),
        "provinces_au_dessus_norme_salle": int((rs > ns).sum()),
        "pire_ratio_eleves_maitre": float(rm.max()),
        "pire_ratio_eleves_salle": float(rs.max()),
        "ecart_type_ratio_maitre": float(rm.std()),
        "gini_ratio_maitre": _gini_pondere(rm[ok], e[ok]),
        "rapport_p90_p10_ratio_maitre": float(rm[ok].quantile(0.9) / rm[ok].quantile(0.1)),
        "part_eleves_province_conforme": float(e[ok & (rm <= nm)].sum() / e[ok].sum()),
    }


def _v(x: float, norme: float) -> str:
    """Ratio arrondi ; une décimale près de la norme, pour ne pas écrire « 50 » pour 49,9."""
    return (f"{x:.1f}" if abs(x - norme) < 1 else f"{x:.0f}").replace(".", ",")


def motifs(res: pd.DataFrame, cfg: dict, contraintes: dict | None = None) -> pd.Series:
    """Pourquoi chaque province reçoit ce qu'elle reçoit, en une phrase (plan optimisé)."""
    nm = cfg["normes"]["eleves_par_maitre"]
    e, t, s = res["eleves_horizon"], res["maitres"], res["salles"]
    avant = (e / t.where(t > 0))
    x = res["enseignants_attribues"] + (res["redeployes_entrants"] if "redeployes_entrants" in res else 0)
    sortants = res["redeployes_sortants"] if "redeployes_sortants" in res else pd.Series(0, index=res.index)
    libres = (s - t).clip(lower=0)
    rouvrables = res["salles_a_rouvrir"] if "salles_a_rouvrir" in res else pd.Series(0, index=res.index)
    capacite = libres + res["salles_attribuees"] + rouvrables
    apres = res["ratio_maitre_apres"] if "ratio_maitre_apres" in res else e / (t + x - sortants)
    servies = avant[x > 0]
    seuil = servies.min() if len(servies) else None
    imposees = {nom for nom, b in ((contraintes or {}).get("provinces") or {}).items() if b.get("min_enseignants")}
    regions_imposees = {nom for nom, b in ((contraintes or {}).get("regions") or {}).items() if b.get("min_enseignants")}
    out = []
    for i in res.index:
        nom = res.at[i, "province"]
        if sortants[i] > 0:
            out.append(f"cède {int(sortants[i])} enseignants mutés ailleurs : elle reste à la norme")
        elif x[i] == 0:
            if pd.isna(avant[i]):
                out.append("pas d'enseignant en poste")
            elif avant[i] <= nm:
                out.append(f"déjà à la norme ou en dessous ({_v(avant[i], nm)} élèves par enseignant)")
            elif capacite[i] <= 0:
                raison = ("accès trop dégradé" if not res.at[i, "acces_construction"] else "écoles fermées à rouvrir d'abord")                     if "acces_construction" in res and not res.at[i, "construction_possible"] else "pas de salle disponible"
                out.append(f"aucune salle pour accueillir un enseignant ({raison})")
            else:
                out.append(f"moins chargée que les provinces servies ({_v(avant[i], nm)} élèves par enseignant) : "
                           "les moyens vont d'abord aux plus chargées")
        elif nom in imposees:
            out.append("minimum exigé par le décideur")
        elif "region" in res and res.at[i, "region"] in regions_imposees and apres[i] < nm - 0.5:
            # passée sous la norme pour atteindre le minimum exigé pour sa région (les autres provinces manquent de salles)
            out.append(f"minimum exigé pour sa région : {_v(apres[i], nm)} élèves par enseignant, sous la norme, "
                       "faute de salles dans les autres provinces de la région")
        elif x[i] >= capacite[i] and apres[i] > nm + 0.5:
            parts = [f"{int(n_)} {lib}" for n_, lib in ((libres[i], "libres"), (res.at[i, "salles_attribuees"], "construites"),
                                                          (min(rouvrables[i], max(0, x[i] - libres[i] - res.at[i, "salles_attribuees"])), "à rouvrir")) if n_ > 0]
            out.append(f"limitée par les salles : {' + '.join(parts) or 'aucune'} ; un enseignant par salle")
        elif apres[i] <= nm + 0.5:
            out.append("ramenée à la norme")
        else:
            out.append(f"servie en priorité : de {_v(avant[i], nm)} à {_v(apres[i], nm)} élèves par enseignant")
    return pd.Series(out, index=res.index)


def mouvements(res: pd.DataFrame, centres: dict[str, tuple[float, float]]) -> list[dict]:
    """Redéploiements en couples origine → destination : les plus proches d'abord (distance entre les centres
    de population des provinces). Le modèle décide combien part et combien arrive ; cet appariement propose
    le mouvement le plus court, à affiner par les services."""
    import math as _m
    solde = res.set_index("province")["solde_redeploiement"].fillna(0)
    departs = {p: int(-v) for p, v in solde.items() if v < 0}
    arrivees = {p: int(v) for p, v in solde.items() if v > 0}

    def dist(a: str, b: str) -> float:
        if a not in centres or b not in centres:
            return 1e9
        (la1, lo1), (la2, lo2) = centres[a], centres[b]
        x = _m.radians(lo2 - lo1) * _m.cos(_m.radians((la1 + la2) / 2))
        return 6371 * _m.hypot(x, _m.radians(la2 - la1))

    couples = sorted(((dist(a, b), a, b) for a in departs for b in arrivees), key=lambda t: t[0])
    out = []
    for dkm, a, b in couples:
        k = min(departs[a], arrivees[b])
        if k > 0:
            out.append({"de": a, "vers": b, "enseignants": k, "distance_km": round(dkm)})
            departs[a] -= k
            arrivees[b] -= k
    return out


def _libelle_contrainte(niveau: str, nom: str, cle: str, valeur) -> str:
    quoi = {"min_enseignants": "au moins {} enseignants", "max_enseignants": "au plus {} enseignants",
            "min_salles": "au moins {} salles", "max_salles": "au plus {} salles"}[cle].format(valeur)
    return f"{'province' if niveau == 'provinces' else 'région'} {nom_officiel(nom)} : {quoi}"


def _diagnostic(d: pd.DataFrame, cfg: dict, n, m, budget, contraintes: dict | None) -> str:
    """Message d'un plan impossible : quelle contrainte bloque, à elle seule ou avec les autres."""
    import copy
    simples = [(niv, nom, cle, v) for niv in ("provinces", "regions") for nom, b in ((contraintes or {}).get(niv) or {}).items()
               for cle, v in b.items() if v is not None]
    opt = cfg["optimisation"]
    n_ = opt["enseignants_a_repartir"] if n is None else n
    m_ = opt["salles_a_construire"] if m is None else m
    total = {"enseignants": n_, "salles": m_}
    for quoi in ("enseignants", "salles"):
        planchers = sum(v for niv, _, cle, v in simples if cle == f"min_{quoi}" and niv == "provinces")
        if budget is None and planchers > total[quoi]:
            return (f"Les planchers par province demandent {planchers} {quoi}, plus que les {total[quoi]} disponibles. "
                    "Augmenter les moyens ou abaisser des planchers.")
    rapide = copy.deepcopy(cfg)
    rapide["optimisation"].update(departage=0, temps_limite_s=5)
    for niv, nom, cle, v in simples:
        _, st = optimiser(d, rapide, n, m, budget, {niv: {nom: {cle: v}}})
        if st not in ("Optimal", "Non prouvé optimal"):
            return (f"Exigence impossible à tenir : {_libelle_contrainte(niv, nom, cle, v)}. Avec les moyens "
                    "disponibles, et un enseignant par salle, elle ne peut pas être respectée : la réduire.")
    return ("Les exigences demandées sont possibles une à une, mais pas toutes ensemble avec ces moyens : "
            + " ; ".join(_libelle_contrainte(*c) for c in simples[:6]) + ". En retirer une, ou augmenter les moyens.")


def comparer(d: pd.DataFrame, cfg: dict, n: int | None = None, m: int | None = None,
             budget: float | None = None, contraintes: dict | None = None,
             redeploiement: int = 0) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Répartitions (sans moyens nouveaux, proportionnelle, au prorata des besoins, optimisée) et leur bilan.

    Les contraintes du décideur et le redéploiement ne s'appliquent qu'à la répartition optimisée ; les règles
    simples servent de repère."""
    res_opt, statut = optimiser(d, cfg, n, m, budget, contraintes, redeploiement)
    if statut not in ("Optimal", "Non prouvé optimal"):
        raise ValueError(_diagnostic(d, cfg, n, m, budget, contraintes))
    n_eff, m_eff = int(res_opt["enseignants_attribues"].sum()), int(res_opt["salles_attribuees"].sum())
    res_opt["ratio_maitre_apres"] = res_opt["eleves_horizon"] / effectif_apres(res_opt).replace(0, np.nan)
    res_opt["motif"] = motifs(res_opt, cfg, contraintes)
    rien = d.assign(enseignants_attribues=0, salles_attribuees=0)
    res_prop = proportionnelle(d, n_eff, m_eff)  # mêmes moyens que la solution optimisée
    res_bes = au_prorata_des_besoins(d, cfg, n_eff, m_eff)
    detail, bilan = [], []
    for nom, r in (("sans_moyens_nouveaux", rien), ("proportionnelle", res_prop), ("besoins", res_bes),
                   ("optimisee", res_opt)):
        r = r.assign(methode=nom)
        r["ratio_maitre_apres"] = r["eleves_horizon"] / effectif_apres(r).replace(0, np.nan)
        r["ratio_salle_apres"] = r["eleves_horizon"] / (r["salles"] + r["salles_attribuees"]).replace(0, np.nan)
        detail.append(r)
        bilan.append({"methode": nom, **evaluer(r, cfg),
                      "duree_s": res_opt.attrs["duree_s"] if nom == "optimisee" else None})
    return pd.concat(detail, ignore_index=True), pd.DataFrame(bilan), statut


if __name__ == "__main__":
    cfg = config()
    table = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    prevision = pd.read_csv(SORTIE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    d = donnees_probleme(table, prevision, cfg)
    detail, bilan, statut = comparer(d, cfg)
    detail.to_csv(SORTIE / "allocation.csv", index=False, sep=";", encoding="utf-8")
    bilan.to_csv(SORTIE / "allocation_bilan.csv", index=False, sep=";", encoding="utf-8")
    print(f"Solveur : {statut}, {bilan.set_index('methode').loc['optimisee', 'duree_s']} s")
    print(bilan.set_index("methode").T.round(1).to_string())
    o = detail[detail["methode"] == "optimisee"].sort_values("enseignants_attribues", ascending=False)
    print(o[["province", "eleves_horizon", "maitres", "salles", "enseignants_attribues", "salles_attribuees",
             "ratio_maitre_apres", "ratio_salle_apres", "construction_possible"]].head(14).round(1).to_string(index=False))
