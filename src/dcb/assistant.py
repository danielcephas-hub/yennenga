"""Assistant Yennenga : répond aux questions d'un décideur en langage simple, à partir des seuls chiffres publiés par
l'outil (outputs/web) et de ses calculs (même fonction que l'onglet Répartition).

Positionnement : il explique et calcule, il ne décide pas ; chaque plan proposé s'ouvre dans l'onglet Répartition.

Sans IA générative, sans service extérieur : le moteur reconnaît les lieux, les nombres et l'intention de la question,
et répond par des phrases préparées remplies avec les chiffres de l'outil. Gratuit, immédiat, aucune donnée ne quitte
le serveur, aucun chiffre inventé. Interrupteur : `assistant.actif` dans config.yaml.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from dcb.indicateurs import config
from dcb.territoire import nom_officiel

RACINE = Path(__file__).resolve().parents[2]
WEB = RACINE / "outputs" / "web"


class AssistantIndisponible(Exception):
    """Assistant désactivé : message lisible pour l'utilisateur."""


# --- données publiées -------------------------------------------------------------------------------------------

def _cle(s: str) -> str:
    """Nom comparable : sans accents, majuscules, tirets et apostrophes en espaces (« Séno » = « SENO »)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").replace("'", " ").split())


@lru_cache(maxsize=1)
def _donnees() -> dict:
    lire = lambda n: json.loads((WEB / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
    d = {"meta": lire("meta"), "provinces": lire("provinces"), "communes": lire("communes"), "sites": lire("sites")}
    try:
        d["annees"] = lire("provinces_annees")
    except FileNotFoundError:
        d["annees"] = None
    return d


def _arrondi(v, n=1):
    return round(v, n) if isinstance(v, float) else v


def fiche_province(province: str) -> dict:
    d = _donnees()
    p = next((x for x in d["provinces"] if _cle(x["province"]) == _cle(province)), None)
    if p is None:
        noms = ", ".join(sorted(nom_officiel(x["province"]) for x in d["provinces"]))
        raise ValueError(f"Province inconnue : {province}. Les 45 provinces des annuaires sont : {noms}.")
    ref = d["meta"]["annee_reference"]
    out = {
        "province": nom_officiel(p["province"]), "region_annuaires": nom_officiel(p["region"]),
        f"observe_{ref}_ecoles_publiques": {
            "eleves": p["eleves"], "enseignants": p["maitres"], "salles": p["salles"], "ecoles": p["ecoles"],
            "eleves_par_enseignant": _arrondi(p["eleves_par_maitre"]), "eleves_par_salle": _arrondi(p["eleves_par_salle"]),
            "part_salles_paille_ou_banco": _arrondi(p["part_salles_precaires"], 3),
            "source": f"annuaire statistique du primaire {ref} (DGESS)"},
        "calculs_outil": {
            "indice_de_besoin_0_a_1": _arrondi(p["indice_besoin"], 2), "rang_priorite_sur_45": p["rang"],
            "rang_selon_poids_de_la_surcharge": [p["rang_p05"], p["rang_p95"]], "classement_a_confirmer": p["rang_instable"],
            "note_surcharge_0_a_1": _arrondi(p["score_surcharge"], 2), "note_bati_0_a_1": _arrondi(p["score_bati"], 2),
            "part_ecoles_fermees_depuis_le_plus_haut": _arrondi(p["part_ecoles_fermees"], 3),
            "construction_possible": p["construction_possible"]},
        f"eleves_publics_attendus_{d['meta']['annee_horizon'][:4]}": p["eleves_horizon"],
        "plan_type": {"moyens": f"{d['meta']['defauts']['enseignants']} enseignants et {d['meta']['defauts']['salles']} salles pour tout le pays",
                      "enseignants_recus": p["enseignants_attribues"], "salles_recues": p["salles_attribuees"],
                      "salles_ecoles_fermees_a_rouvrir": p.get("salles_rouvertes"),
                      "eleves_par_enseignant_apres": _arrondi(p["ratio_maitre_apres"])},
        "eleves_inscrits_public_et_prive_par_annee": {str(a): e for a, e in p["serie"][-8:]},
    }
    if d["annees"]:
        o = d["annees"]["valeurs"].get(ref, {}).get(p["province"], {})
        if o.get("t", {}).get("e"):
            out["public_prive_" + ref] = {"eleves_public": o.get("pu", {}).get("e"), "eleves_prive": o.get("pr", {}).get("e"),
                                          "enseignants_prive": o.get("pr", {}).get("m"),
                                          "part_du_prive": round((o.get("pr", {}).get("e") or 0) / o["t"]["e"], 3)}
    return out


def fiche_commune(commune: str) -> dict:
    d = _donnees()
    trouvees = [c for c in d["communes"] if _cle(c["commune"]) == _cle(commune)]
    if not trouvees:
        proches = sorted({c["commune"] for c in d["communes"] if _cle(commune)[:4] in _cle(c["commune"])})[:8]
        raise ValueError(f"Commune inconnue : {commune}." + (f" Noms proches : {', '.join(proches)}." if proches else ""))
    h = d["meta"]["annee_horizon"][:4]
    out = []
    for c in trouvees:
        sites = [s for s in d["sites"] if s["pcode_commune"] == c["pcode_commune"]]
        out.append({
            "commune": c["commune"], "province_2025": c["province"], "region_2025": c["region"],
            "province_des_annuaires": nom_officiel(c["province_ancienne"]),
            "habitants_2019_RGPH": c["population_2019"], "enfants_6_11_ans_2019": c["enfants_6_11_2019"],
            f"enfants_6_11_ans_{h}_projection_outil": c[f"enfants_6_11_{h}"],
            "enfants_a_plus_de_3_km_d_une_ecole": {"au_minimum": round(c["eloignes_borne_basse"] or 0),
                                                   "au_maximum": round(c["eloignes_borne_haute"] or 0)},
            "deplaces_fin_2022_CONASUR": c["pdi_total"] if c.get("pdi_releve") else "commune non relevée",
            "part_ecoles_fermees_dans_la_province": c["part_ecoles_fermees_province"],
            "sites_proposes": [{"rang_national": s["rang"], "enfants_rapproches": s["enfants_rapproches"],
                                "recommandation": s["recommandation"]} for s in sites],
            "a_savoir": "Les annuaires ne publient ni enseignants ni salles par commune : les moyens se répartissent par province.",
        })
    return out[0] if len(out) == 1 else {"communes_homonymes": out}


INDICATEURS = {
    "eleves_par_enseignant": ("eleves_par_maitre", "élèves par enseignant, écoles publiques"),
    "eleves_par_salle": ("eleves_par_salle", "élèves par salle, écoles publiques"),
    "indice_de_besoin": ("indice_besoin", "indice de besoin de l'outil (0 à 1)"),
    "ecoles_fermees": ("part_ecoles_fermees", "part des écoles fermées depuis le plus haut 2017-2025"),
    "salles_paille_ou_banco": ("part_salles_precaires", "part des salles en paille ou banco, public"),
    "enseignants_recus_plan_type": ("enseignants_attribues", "enseignants reçus dans le plan type"),
    "filles_pour_100_garcons": ("filles_pour_100", "filles pour 100 garçons inscrits, public et privé"),
}


def _filles(annee: str | None = None) -> dict:
    """Filles pour 100 garçons inscrits par province (public et privé), année de référence par défaut."""
    d = _donnees()
    if not d["annees"]:
        return {}
    v = d["annees"]["valeurs"].get(annee or d["meta"]["annee_reference"], {})
    return {p: 100 * x["t"]["f"] / x["t"]["g"] for p, x in v.items() if x.get("t", {}).get("f") is not None and x["t"].get("g")}


def classement(indicateur: str, nombre: int = 10, ordre: str = "decroissant") -> dict:
    if indicateur not in INDICATEURS:
        raise ValueError(f"Indicateur inconnu : {indicateur}. Choix : {', '.join(INDICATEURS)}.")
    col, lib = INDICATEURS[indicateur]
    d = _donnees()
    if col == "filles_pour_100":
        lignes = list(_filles().items())
    else:
        lignes = [(x["province"], x[col]) for x in d["provinces"] if x.get(col) is not None]
    lignes.sort(key=lambda t: t[1], reverse=(ordre != "croissant"))
    n = max(1, min(45, int(nombre)))
    return {"indicateur": lib, "annee": d["meta"]["annee_reference"],
            "provinces": [{"rang": i + 1, "province": nom_officiel(p), "valeur": _arrondi(v, 3)} for i, (p, v) in enumerate(lignes[:n])]}


def calculer_plan(entree: dict) -> dict:
    """Même calcul que l'onglet Répartition ; renvoie un résumé et la demande, pour ouvrir le plan dans l'onglet."""
    from dcb.service import Demande, repartir
    e = {k: v for k, v in entree.items() if v is not None}
    dem = {"scenario": e.get("scenario", "tendance")}
    if "budget_milliards_fcfa" in e:
        dem.update(budget_seul=True, budget_fcfa=float(e["budget_milliards_fcfa"]) * 1e9)
    else:
        if "enseignants" in e:
            dem["enseignants"] = int(e["enseignants"])
        if "salles" in e:
            dem["salles"] = int(e["salles"])
    for k_in, k_out in (("norme", "eleves_par_maitre"), ("mutations_max", "redeploiement"), ("recul_prive_pourcent", "recul_prive")):
        if k_in in e:
            dem[k_out] = e[k_in]
    for x in e.get("exigences", []) or []:
        niv = "regions" if x.get("niveau") == "region" else "provinces"
        d = _donnees()
        noms = {_cle(p["province"]): p["province"] for p in d["provinces"]} if niv == "provinces" else \
            {_cle(p["region"]): p["region"] for p in d["provinces"]}
        nom = noms.get(_cle(x.get("nom", "")))
        if not nom:
            raise ValueError(f"{'Région' if niv == 'regions' else 'Province'} inconnue : {x.get('nom')}.")
        dem.setdefault(niv, {}).setdefault(nom, {})[x["type"]] = int(x["valeur"])
    demande = Demande(**dem)
    from dcb.service import _CALCULS
    if not _CALCULS.acquire(timeout=15):
        raise ValueError("Serveur occupé par d'autres calculs : réessayez dans quelques secondes.")
    try:
        r = repartir(demande)
    finally:
        _CALCULS.release()
    b = {x["methode"]: x for x in r["bilan"]}
    o = b["optimisee"]
    lignes = sorted(r["repartitions"]["optimisee"], key=lambda l: -l["enseignants_attribues"])
    return {
        "statut": "meilleur plan possible" if r["statut"] == "Optimal" else r["statut"],
        "pour_la_rentree": r["horizon"][:4],
        "enseignants_affectes": r["enseignants_utilises"], "salles_construites": r["salles_utilisees"],
        "enseignants_mutes": r.get("enseignants_redeployes", 0),
        "cout_total_milliards_fcfa": round(r["cout_fcfa"] / 1e9, 1),
        "cout_detail": f"{_nb(r['cout_salles_fcfa'] / 1e9, 1)} milliards pour les salles, une fois, et {_nb(r['salaires_annuels_fcfa'] / 1e9, 1)} milliards de salaires par an, comptés sur {r['annees_budget']} ans",
        "province_la_plus_chargee_eleves_par_enseignant": {
            "plan_yennenga": _arrondi(o["pire_ratio_eleves_maitre"]),
            "partage_selon_le_nombre_d_eleves": _arrondi(b["proportionnelle"]["pire_ratio_eleves_maitre"]),
            "sans_moyens_nouveaux": _arrondi(b["sans_moyens_nouveaux"]["pire_ratio_eleves_maitre"])},
        "eleves_en_trop_dans_les_classes_surchargees": {
            "plan_yennenga": round(o["eleves_au_dela_norme_maitre"]),
            "partage_selon_le_nombre_d_eleves": round(b["proportionnelle"]["eleves_au_dela_norme_maitre"]),
            "partage_selon_les_manques": round(b["besoins"]["eleves_au_dela_norme_maitre"]),
            "sans_moyens_nouveaux": round(b["sans_moyens_nouveaux"]["eleves_au_dela_norme_maitre"])},
        "provinces_les_plus_servies": [{"province": nom_officiel(l["province"]), "enseignants": l["enseignants_attribues"],
                                        "salles": l["salles_attribuees"], "eleves_par_enseignant_apres": _arrondi(l["ratio_maitre_apres"]),
                                        "pourquoi": l.get("motif")} for l in lignes[:10]],
        "_lignes": {l["province"]: l for l in lignes},
        "_demande": demande.model_dump(exclude_none=True),
    }


def reglages() -> dict:
    return config().get("assistant", {}) or {}


def disponible() -> bool:
    return bool(reglages().get("actif"))


# --- compréhension des questions (sans IA générative) ------------------------------------------------------------
# Le moteur repère dans la question des lieux (provinces, régions, communes), des nombres avec leur unité et une
# intention (définir un terme, calculer un plan, classer, expliquer une province). Les réponses sont des phrases
# préparées, remplies avec les chiffres de l'outil : rien n'est inventé, la même question donne la même réponse.

def _q(texte: str) -> str:
    """Question normalisée : majuscules sans accents, ponctuation en espaces (le % et les chiffres restent)."""
    s = _cle(texte).replace(" ", " ").replace("\xa0", " ")
    return " " + " ".join(re.sub(r"[^A-Z0-9%,. ]", " ", s).split()) + " "


def _a(q: str, *mots: str) -> bool:
    """Un des mots (début de mot) est-il dans la question ?"""
    return any(re.search(r"\b" + m, q) for m in mots)


def _nb(x, n=0) -> str:
    if x is None:
        return "—"
    v = round(float(x), n)
    s = f"{v:,.{n}f}".replace(",", " ").replace(".", ",")
    return s


def _combien(n, chose: str, choses: str) -> str:
    """« aucune salle », « 1 salle », « 15 salles »."""
    n = int(round(n or 0))
    masculin = chose.split()[0] in ("enseignant", "site", "élève", "poste") or chose.endswith(("ant", "eur", "ève", "on"))
    return (("aucun " if masculin else "aucune ") + chose) if n == 0 else f"{_nb(n)} {chose if n == 1 else choses}"


def _motif_simple(motif: str | None) -> str:
    """Le « pourquoi » du calcul, en phrase simple."""
    if not motif:
        return ""
    if motif.startswith("limitée par les salles"):
        dispo = motif.split(":", 1)[1].split(";")[0].strip().replace("libres", "salles libres").replace("construites", "salles construites")
        return f"Chaque enseignant a besoin d'une salle : la province n'en a que {dispo}, elle ne peut donc pas recevoir plus d'enseignants."
    if motif.startswith("servie en priorité"):
        return "C'est l'une des provinces les plus chargées : elle est servie en priorité, " + motif.split(":", 1)[1].strip() + "."
    if motif.startswith("moins chargée"):
        return "Elle est moins chargée que d'autres : les moyens vont d'abord aux provinces les plus surchargées."
    if motif.startswith("déjà à la norme"):
        return "Elle est déjà à la norme ou en dessous : elle n'a pas besoin d'enseignants en plus."
    return motif[0].upper() + motif[1:] + "."


def _pc(x, n=0) -> str:
    return "—" if x is None else f"{_nb(100 * float(x), n)} %"


@lru_cache(maxsize=1)
def _lieux() -> dict:
    d = _donnees()
    prov = {}
    for p in d["provinces"]:
        for nom in (p["province"], nom_officiel(p["province"])):
            prov[_cle(nom)] = p["province"]
    reg = {}
    for p in d["provinces"]:
        for nom in (p["region"], nom_officiel(p["region"])):
            reg[_cle(nom)] = p["region"]
    com = {}
    for c in d["communes"]:
        com.setdefault(_cle(c["commune"]), c["commune"])
    # noms courts usuels des grandes villes : la commune correspondante
    for court, nom in (("OUAGA", "OUAGADOUGOU"), ("BOBO", "BOBO DIOULASSO"), ("FADA", "FADA NGOURMA")):
        if nom in com:
            com.setdefault(court, com[nom])
    return {"provinces": prov, "regions": reg, "communes": com}


# régions dont le nom est aussi un mot courant (« c'est », « le centre de santé ») : il faut un article ou « région »
_REGIONS_MOTS = {"EST", "NORD", "CENTRE", "OUEST", "SUD"}


def _regions(q: str, table: dict) -> list[str]:
    out = []
    for r in _trouver(q, table):
        cle = _cle(r)
        if cle in _REGIONS_MOTS and not re.search(rf"\b(REGION( DU| DE L| DE LA)?|DU|AU|LE|LA|L|DANS|POUR)\s+{cle}\b", q):
            continue
        out.append(r)
    return out


def _trouver(q: str, table: dict) -> list[str]:
    """Noms de la table présents dans la question (mots entiers, les plus longs d'abord, sans chevauchement)."""
    trouves, reste = [], q
    for cle in sorted(table, key=len, reverse=True):
        if f" {cle} " in reste:
            trouves.append(table[cle])
            reste = reste.replace(f" {cle} ", " | ")
    return list(dict.fromkeys(trouves))


def _approche(q: str, table: dict) -> str | None:
    """Faute de frappe sur un nom en un mot (« Kadiogoo », « Sanmatega ») : nom le plus proche, s'il est très proche."""
    import difflib
    simples = {k: v for k, v in table.items() if " " not in k}
    for mot in q.split():
        if len(mot) >= 5 and not mot.isdigit():
            m = difflib.get_close_matches(mot, list(simples), n=1, cutoff=0.85)
            if m:
                return simples[m[0]]
    return None


_UNITE = r"(ENSEIGNANTS?|MAITRES?|INSTITUTEURS?|PROFESSEURS?|PROFS?|POSTES?|RECRUES?|SALLES?|CLASSES?|MILLIARDS?|MDS?|MD|%|POUR ?CENT)"


_UNITES_LETTRES = {"DEUX": 2, "TROIS": 3, "QUATRE": 4, "CINQ": 5, "SIX": 6, "SEPT": 7, "HUIT": 8, "NEUF": 9,
                   "DIX": 10, "QUINZE": 15, "VINGT": 20, "TRENTE": 30, "QUARANTE": 40, "CINQUANTE": 50, "CENT": 100}


def _chiffres(q: str) -> str:
    """« deux mille » → 2000, « cinq cents » → 500, « vingt milliards » → 20 milliards ; « 2,000 » → 2 000 ;
    les années (« en 2030 », « rentrée 2030 ») sont retirées pour ne pas être lues comme des quantités."""
    mots = "|".join(_UNITES_LETTRES)
    q = re.sub(rf"\b({mots})\s+MILLE\b", lambda m: f" {_UNITES_LETTRES[m.group(1)] * 1000} ", q)
    q = re.sub(r"\bMILLE\b", " 1000 ", q)
    q = re.sub(rf"\b({mots})\s+CENTS?\b", lambda m: f" {_UNITES_LETTRES[m.group(1)] * 100} ", q)
    q = re.sub(rf"\b({mots})\b(?=\s+(MILLIARDS?|POUR ?CENT|%|ENSEIGNANTS?|SALLES?))", lambda m: f" {_UNITES_LETTRES[m.group(1)]} ", q)
    q = re.sub(r"\b(\d{1,3}),(\d{3})\b", r"\1 \2", q)
    q = re.sub(r"\b(EN|RENTREE|D ICI|HORIZON|ANNEE)\s+20\d\d\b", " ", q)
    return " " + " ".join(q.split()) + " "


def _nombres(q: str) -> dict:
    """« 2 000 enseignants », « 800 salles », « 20 milliards », « 20 % » → valeurs par unité."""
    out: dict = {}
    q = _chiffres(q)
    for brut, unite in re.findall(r"\b(\d{1,3}(?:[ .]\d{3})+|\d+(?:,\d+)?)\s*(?:DE\s+|D\s+)?"
                                  r"(?:NOUVEAUX?\s+|NOUVELLES?\s+|AUTRES?\s+|SUPPLEMENTAIRES?\s+)?" + _UNITE, q):
        v = float(re.sub(r"[ .]", "", brut).replace(",", "."))
        u = ("enseignants" if unite[:3] in ("ENS", "MAI", "INS", "PRO", "POS", "REC") else "salles" if unite[:3] in ("SAL", "CLA")
             else "milliards" if unite.startswith(("MILL", "MD")) else "pourcent")
        out.setdefault(u, v)
    return out


GLOSSAIRE = [
    (("LYCEE", "COLLEGE", "SECONDAIRE", "UNIVERSIT", "POST PRIMAIRE", "MATERNELLE", "PRESCOLAIRE"),
     "L'outil porte sur le primaire : répartition des enseignants et des salles entre les 45 provinces. Pour le post-primaire, il donne "
     "seulement un diagnostic par région (élèves par classe, places assises, établissements fermés), les données publiées ne descendant "
     "pas plus bas. Le secondaire et le préscolaire ne sont pas traités."),
    (("INVENT", " IA ", "INTELLIGENCE ARTIFICIELLE", "CHATGPT", "ROBOT"),
     "Non. Cet assistant n'utilise pas d'intelligence artificielle générative : il reconnaît la question par des règles et répond "
     "avec les chiffres publiés par l'outil (annuaires DGESS, INSD, CONASUR) et ses calculs, sur le serveur. Il ne peut pas "
     "inventer un chiffre ; s'il ne comprend pas, il le dit."),
    (("PROPORTIONNEL", "FAIT MIEUX", "POURQUOI YENNENGA", "MEILLEUR QUE", "APPORT DE L OPTIMISATION", "A QUOI SERT L OPTIMISATION"),
     "Avec les mêmes moyens, partager selon le nombre d'élèves donne aussi des enseignants à des provinces déjà proches de la norme. "
     "Cibler les provinces en manque fait mieux : c'est ce que font le plan Yennenga et la règle « selon les manques », qui retirent "
     "autant d'élèves des classes surchargées. Ce que Yennenga ajoute : il sert d'abord les provinces les plus chargées (écart "
     "entre provinces plus faible), respecte les exigences du décideur et choisit entre recruter et construire quand on donne un budget."),
    (("FIABL", "SE FIER", "FIER A", "CONFIANCE", "TESTE SUR LE PASSE", "TEST SUR LE PASSE", "RETROSPECT", "CREDIBL"),
     "On peut vérifier l'outil sur le passé : placé en {r_o}, avec les seuls chiffres connus alors et les moyens réellement ajoutés "
     "jusqu'en {r_f}, il aurait laissé {r_so} élèves en surnombre, contre {r_sr} avec la répartition réelle ({r_ec}). La prévision "
     "des effectifs est testée sur les années passées, chaque chiffre a sa source, et les tests automatiques recalculent les "
     "résultats. Limites : données par province seulement, coûts et seuils posés comme hypothèses, effectifs incertains dans les "
     "zones d'insécurité. L'outil éclaire la décision ; il ne la remplace pas."),
    (("SOURCE", "D OU VIENNENT LES DONNEES", "QUELLES DONNEES", "QUELLE DONNEE"),
     "Sources : annuaires statistiques du primaire de la DGESS ({a0} à {ref}) ; recensement 2019 et projections de l'INSD ; "
     "déplacés par commune du CONASUR (fin 2022) ; population WorldPop calée sur l'INSD ; écoles repérées sur OpenStreetMap ; "
     "limites administratives OCHA ; coûts : marchés publics communaux 2025 et grille salariale. Chaque fiche indique l'année et la source de ses chiffres."),
    (("QUI DECIDE", "DECISION", "DECIDE", "REMPLACE", "A LA PLACE DU"),
     "L'outil propose, compare et explique ; il ne décide pas. Le plan calculé s'imprime en fiche de décision, que les directions "
     "chargées des affectations et du budget soumettent à l'arbitrage du cabinet. Toute exigence du décideur (au moins tant "
     "d'enseignants pour une région, par exemple) peut être imposée dans l'onglet Répartition."),
    (("DEPLAC", "PDI"),
     "Les personnes déplacées internes viennent du relevé du CONASUR par commune d'accueil (fin 2022) : {pdi} personnes au total. "
     "Elles apparaissent sur la carte au niveau des communes (indicateur « Déplacés accueillis ») et dans chaque fiche de commune. "
     "Les enseignants se répartissent par province : les déplacés y comptent à travers les élèves inscrits."),
    (("LIMITE",),
     "Limites principales : enseignants et salles ne sont connus que par province (pas par école) ; le besoin porte sur les "
     "élèves inscrits, pas sur les enfants non scolarisés ; coûts, norme par salle et seuils sont des hypothèses ; la remise en état "
     "des écoles fermées n'est pas chiffrée ; dans les zones d'insécurité, les effectifs futurs se raisonnent par scénarios. "
     "Le détail est dans l'onglet Méthode."),
    (("CLASSEMENT A CONFIRMER", "RANG SENSIBLE", "FOURCHETTE", "ENTRE .* ET .* SELON"),
     "« Classement à confirmer » : le rang de priorité d'une province dépend du poids donné à la surcharge des classes. "
     "L'outil refait le classement {tirages} fois avec des poids différents (de {p1} à {p2} pour la surcharge) ; si la province "
     "change de tiers (haut, milieu, bas) dans plus de {seuil} des cas, son rang est « à confirmer ». La fiche donne la fourchette de rangs."),
    (("INDICE DE BESOIN", "INDICE", "PRIORITE", "RANG"),
     "L'indice de besoin classe les 45 provinces de 0 (la mieux placée) à 1 (la plus en difficulté). Il combine la surcharge des "
     "classes ({ps} : élèves par enseignant et par salle) et l'état du bâti ({pb} : salles en paille ou banco, salles en mauvais état). "
     "Le rang de priorité en découle : n° 1 = la plus en difficulté. Source : annuaire DGESS {ref}."),
    (("ELEVES EN TROP", "SURCHARG", "AU DELA DE LA NORME"),
     "Des élèves sont « en trop » quand une classe dépasse la norme de {norme} élèves par enseignant. On compte, province par "
     "province, les élèves au-delà de cette norme : c'est le premier chiffre que l'outil cherche à réduire."),
    (("NORME",),
     "La norme est de {norme} élèves par enseignant (norme nationale, tableau de bord DGESS 2023-2024). Au-delà, la classe est "
     "surchargée. Le plan sectoriel de l'éducation 2017-2030 vise 40 : on peut choisir 40 ou 45 dans l'onglet Répartition."),
    (("PLAN TYPE", "PLAN DE REFERENCE"),
     "Le plan type est un exemple calculé par l'outil avec les réglages par défaut : {ens} nouveaux enseignants et {sal} salles "
     "à répartir. Les fiches de la carte en donnent le résultat pour chaque province ; l'onglet Répartition permet de changer ces moyens."),
    (("PARTAGE SELON LE NOMBRE", "PRORATA DES ELEVES", "PARTAGE SELON LES MANQUES", "PRORATA DES BESOINS", "REGLES SIMPLES"),
     "Le plan Yennenga est comparé à deux règles simples, avec les mêmes moyens : « partage selon le nombre d'élèves » (chaque "
     "province reçoit en proportion de ses élèves) et « partage selon les manques » (en proportion des enseignants qui lui manquent). "
     "Yennenga sert d'abord les provinces les plus chargées."),
    (("ECART ENTRE PROVINCES", "GINI"),
     "L'écart entre provinces (indice de Gini) vaut 0 si toutes les provinces ont le même nombre d'élèves par enseignant ; il monte "
     "quand les dotations sont inégales. Le plan Yennenga le réduit plus que les règles simples."),
    (("MUTATION", "REDEPLOI", "MUTE"),
     "Une mutation déplace un enseignant déjà en poste d'une province qui en a plus que la norme vers une province surchargée. "
     "Elle ne crée pas de poste (pas de salaire en plus) mais il faut une salle à l'arrivée. Dans l'onglet Répartition, on fixe un plafond."),
    (("ROUVRIR", "ECOLES FERMEES", "FERMETURE", "FERMEE"),
     "Les écoles fermées se comptent par province : écoles ouvertes en {ref} comparées à l'année où il y en avait le plus (depuis "
     "2017-2018), public et privé. Au-delà de {seuil_f} d'écoles fermées, l'outil ne construit pas : il propose de rouvrir d'abord "
     "les salles des écoles fermées, qui accueillent les enseignants envoyés."),
    (("TENDANCE", "REOUVERTURE", "SCENARIO", "PREVISION", "ELEVES ATTENDUS"),
     "Le plan se calcule sur les élèves attendus à la rentrée {h}. « Tendance » : chaque province prolonge, en l'amortissant, "
     "l'évolution de ses dernières années. « Réouverture » : les provinces touchées par l'insécurité regagnent une partie des élèves "
     "perdus si les écoles rouvrent."),
    (("PRIVE",),
     "Le privé scolarise environ 28 % des élèves du primaire en {ref} (deux tiers au Kadiogo, aucun au Yagha). L'État n'y affecte "
     "pas d'enseignants : l'outil répartit les moyens sur le public. Si des élèves du privé passent au public, le réglage « Élèves "
     "du privé qui passent au public » de l'onglet Répartition calcule les moyens nécessaires."),
    (("COUT", "PRIX", "SALAIRE", "BUDGET"),
     "Coûts retenus : une salle {cs} M FCFA (médiane de 5 marchés communaux de 2025) ; un poste d'enseignant {ce} M FCFA par an "
     "(enseignant débutant en zone rurale, salaire et indemnités). Dans un budget, un poste est compté sur {ab} ans."),
    (("FILLES POUR", "PARITE", "GENRE"),
     "« Filles pour 100 garçons » : élèves du primaire inscrits, public et privé, dans les annuaires DGESS. 100 = autant de filles "
     "que de garçons ; en dessous, des filles manquent à l'école. Le pays est proche de 100 ; quelques provinces sont bien en dessous "
     "(demandez « où manque-t-il le plus de filles ? »). Indicateur affiché sur la carte et dans les fiches ; il ne change pas le calcul de la répartition."),
    (("PAILLE", "BANCO", "PRECAIRE", "BATI"),
     "Les salles en paille ou en banco sont des salles aux murs précaires, comptées dans les annuaires DGESS. Leur part entre "
     "dans l'indice de besoin (état du bâti)."),
    (("LOIN", "3 KM", "DISTANCE", "ACCES", "SITE"),
     "En {h}, entre {loin_b} et {loin_h} enfants de 6 à 11 ans vivraient à plus de {rayon} km d'une école. Un enfant est « loin d'une école » à plus de {rayon} km. L'outil donne deux estimations par commune : au minimum (écoles "
     "manquantes des cartes placées au plus près des enfants) et au maximum (seules les écoles repérées sur OpenStreetMap). Les "
     "sites proposés sont les endroits où une école rapprocherait le plus d'enfants."),
]


def _definir(q: str) -> str | None:
    cfg, m = config(), _donnees()["meta"]
    ind, pond = cfg["indice"], cfg["indice"]["ponderations"]
    tot = sum(pond.values())
    v = {"norme": cfg["normes"]["eleves_par_maitre"], "ref": m["annee_reference"], "h": m["annee_horizon"][:4],
         "ps": _pc(pond["surcharge"] / tot), "pb": _pc(pond["bati"] / tot), "tirages": _nb(ind["tirages_robustesse"]),
         "p1": _pc(ind["robustesse"]["plage_poids_premiere_dimension"][0]), "p2": _pc(ind["robustesse"]["plage_poids_premiere_dimension"][1]),
         "seuil": _pc(ind["robustesse"]["seuil_changement_tiers"]), "ens": _nb(m["defauts"]["enseignants"]), "sal": _nb(m["defauts"]["salles"]),
         "seuil_f": _pc(cfg["implantation"]["seuil_fermeture_rouvrir"]), "cs": _nb(cfg["optimisation"]["cout_salle_fcfa"] / 1e6, 1),
         "ce": _nb(cfg["optimisation"]["cout_enseignant_fcfa"] / 1e6, 1), "ab": cfg["optimisation"].get("annees_budget", 1),
         "rayon": cfg["implantation"]["rayon_km"], "pdi": _nb(m["national"].get("pdi")),
         "a0": "2017-2018", "loin_b": _nb(m["national"].get("eloignes_basse")), "loin_h": _nb(m["national"].get("eloignes_haute"))}
    retro = (m.get("plan_reference") or {}).get("retrospectif") or []
    if retro:
        r0 = retro[0]
        v.update(r_o=r0["origine"][:4], r_f=r0["fin"][5:], r_so=_nb(r0["surnombre_outil"]), r_sr=_nb(r0["surnombre_reel"]),
                 r_ec=f"{_nb(100 * r0['ecart'])} %")
    else:
        v.update(r_o="—", r_f="—", r_so="—", r_sr="—", r_ec="—")
    for mots, texte in GLOSSAIRE:
        if any(re.search(r"\b" + mot, q) for mot in mots):
            return texte.format(**v)
    return None


@lru_cache(maxsize=1)
def _plan_type() -> dict:
    """Plan type complet (réglages par défaut), province par province, avec le « pourquoi »."""
    from dcb.service import Demande, repartir
    r = repartir(Demande())
    return {l["province"]: l for l in r["repartitions"]["optimisee"]}


def _texte_province(prov: str, q: str) -> str:
    d, cfg = _donnees(), config()
    p = next(x for x in d["provinces"] if x["province"] == prov)
    m, nom, norme = d["meta"], nom_officiel(prov), cfg["normes"]["eleves_par_maitre"]
    ref, h = m["annee_reference"], m["annee_horizon"][:4]
    l = _plan_type().get(prov, {})
    seuil_f = cfg["implantation"]["seuil_fermeture_rouvrir"]
    if p["construction_possible"] is False:
        if (p["part_ecoles_fermees"] or 0) > seuil_f:
            raison_c = (f"On n'y construit pas : la province a perdu {_pc(p['part_ecoles_fermees'])} de ses écoles depuis leur plus haut "
                        f"niveau, l'outil propose d'abord de rouvrir les écoles fermées.")
        else:
            raison_c = "On n'y construit pas : l'accès y est trop difficile (ses élèves sont tombés très en dessous de leur plus haut niveau)."
    else:
        raison_c = ""
    plan = (f"Dans le plan type ({_nb(m['defauts']['enseignants'])} enseignants et {_nb(m['defauts']['salles'])} salles pour le pays), "
            f"{nom} reçoit {_combien(p['enseignants_attribues'], 'enseignant', 'enseignants')} et {_combien(p['salles_attribuees'], 'salle', 'salles')}"
            + (f", avec {_nb(p['salles_rouvertes'])} salles d'écoles fermées à rouvrir" if p.get("salles_rouvertes") else "")
            + f" : {_nb(p['ratio_maitre_apres'])} élèves par enseignant à la rentrée {h}.")
    if _a(q, "POURQUOI", "COMMENT SE FAIT", "EXPLIQU", "RAISON"):
        motif = l.get("motif")
        return " ".join(x for x in [plan, _motif_simple(motif), raison_c,
                                    "(Calcul de l'outil ; détails dans l'onglet Répartition, colonne « Pourquoi ».)"] if x)
    if _a(q, "PRIVE", "PUBLIC ET", "PRIVEE"):
        fp = fiche_province(prov).get("public_prive_" + ref)
        if fp:
            return (f"{nom} en {ref} : {_nb(fp['eleves_public'])} élèves dans le public, {_nb(fp['eleves_prive'])} dans le privé, soit "
                    f"{_pc(fp['part_du_prive'])} dans le privé. L'État n'affecte des enseignants que dans le public. Source : annuaire DGESS {ref}.")
    rang = (f"Priorité n° {p['rang']} sur 45 selon l'indice de besoin ({_nb(p['indice_besoin'], 2)} sur 1)"
            + (f", classement à confirmer : entre le {p['rang_p05']}e et le {p['rang_p95']}e rang selon les poids." if p["rang_instable"]
               else f", classement stable (du {p['rang_p05']}e au {p['rang_p95']}e rang selon les poids)."))
    ferm = (f" {_pc(p['part_ecoles_fermees'])} de ses écoles ont fermé depuis leur plus haut niveau." if (p["part_ecoles_fermees"] or 0) >= 0.05 else "")
    fl = _filles().get(prov)
    if fl is not None:
        ferm += f" Filles pour 100 garçons inscrits : {_nb(fl)} (public et privé)."
    if _a(q, "FILLE", "PARITE", "GENRE") and fl is not None:
        tout = _filles()
        pays = 100 * sum(x["t"]["f"] for x in d["annees"]["valeurs"][ref].values() if x.get("t", {}).get("f") is not None) / \
            sum(x["t"]["g"] for x in d["annees"]["valeurs"][ref].values() if x.get("t", {}).get("g"))
        rang_f = sorted(tout.values()).index(fl) + 1
        return (f"{nom} en {ref} : {_nb(fl)} filles pour 100 garçons inscrits au primaire, public et privé (pays : {_nb(pays)}). "
                f"C'est la {'1re' if rang_f == 1 else f'{rang_f}e'} valeur la plus faible des 45 provinces. Source : annuaires DGESS, tableaux rétrospectifs.")
    return (f"{nom} (région {nom_officiel(p['region'])}). En {ref}, écoles publiques : {_nb(p['eleves'])} élèves, {_nb(p['maitres'])} enseignants, "
            f"soit {_nb(p['eleves_par_maitre'])} élèves par enseignant (norme : {norme}) et {_nb(p['eleves_par_salle'])} par salle. "
            f"{rang}{ferm} {plan} {raison_c} Source : annuaire DGESS {ref} ; calculs de l'outil.").replace("  ", " ").strip()


def _texte_commune(nom: str) -> str:
    f = fiche_commune(nom)
    if "communes_homonymes" in f:
        f = f["communes_homonymes"][0]
    h = _donnees()["meta"]["annee_horizon"][:4]
    loin = f["enfants_a_plus_de_3_km_d_une_ecole"]
    sites = f["sites_proposes"]
    dep = f["deplaces_fin_2022_CONASUR"]
    return (f"{f['commune']} (province {f['province_2025']}, région {f['region_2025']}). Habitants en 2019 : {_nb(f['habitants_2019_RGPH'])} "
            f"(recensement INSD). Enfants de 6 à 11 ans : {_nb(f['enfants_6_11_ans_2019'])} en 2019, {_nb(f[f'enfants_6_11_ans_{h}_projection_outil'])} "
            f"attendus en {h}. Enfants à plus de 3 km d'une école : entre {_nb(loin['au_minimum'])} et {_nb(loin['au_maximum'])}. "
            + (f"Déplacés accueillis fin 2022 : {_nb(dep)} (CONASUR). " if isinstance(dep, (int, float)) else "Déplacés : commune non relevée par le CONASUR. ")
            + (f"{len(sites)} site(s) proposé(s) pour une école ({', '.join(s['recommandation'] for s in sites)}). " if sites else "Aucun site d'école proposé. ")
            + "Les enseignants et les salles se répartissent par province : voir sa fiche.")


def _texte_classement(q: str, nombre: int) -> str:
    ind = ("filles_pour_100_garcons" if _a(q, "FILLE", "PARITE", "GENRE") else "indice_de_besoin" if _a(q, "BESOIN", "PRIORIT", "DIFFICULT") else "ecoles_fermees" if _a(q, "FERM")
           else "salles_paille_ou_banco" if _a(q, "PAILLE", "BANCO", "PRECAIRE") else "eleves_par_salle" if _a(q, "PAR SALLE")
           else "enseignants_recus_plan_type" if _a(q, "RECOI", "RECU", "PLAN TYPE") else "eleves_par_enseignant")
    croissant = _a(q, "MOINS", "MIEUX", "PLUS FAIBLE")
    if ind == "filles_pour_100_garcons":  # « où manque-t-il le plus de filles » : les valeurs les plus basses d'abord
        croissant = _a(q, "MANQU", "MOINS", "FAIBLE", "RETARD") or not _a(q, "PLUS DE FILLES", "MIEUX")
    c = classement(ind, nombre, "croissant" if croissant else "decroissant")
    fmt = (lambda v: _pc(v)) if ind in ("ecoles_fermees", "salles_paille_ou_banco") else \
        (lambda v: _nb(v, 2)) if ind == "indice_de_besoin" else (lambda v: _nb(v))
    liste = " ; ".join(f"{x['rang']}. {x['province']} ({fmt(x['valeur'])})" for x in c["provinces"])
    combien = (f"la province à la valeur la plus {'faible' if croissant else 'forte'}" if len(c["provinces"]) == 1
               else f"les {len(c['provinces'])} provinces aux valeurs les plus {'faibles' if croissant else 'fortes'}")
    return (f"{c['indicateur'][0].upper() + c['indicateur'][1:]} ({c['annee']}), {combien} : {liste}. Source : annuaire DGESS {c['annee']} ; calculs de l'outil.")


def _texte_plan(q: str, n: dict, provs: list[str], regs: list[str]) -> tuple[str, dict]:
    e: dict = {}
    if "milliards" in n:
        e["budget_milliards_fcfa"] = n["milliards"]
    else:
        if "enseignants" in n:
            e["enseignants"] = int(n["enseignants"])
            e.setdefault("salles", int(n.get("salles", _donnees()["meta"]["defauts"]["salles"])))
        if "salles" in n:
            e["salles"] = int(n["salles"])
    if _a(q, "REOUVERTURE", "ROUVRENT", "SI LES ECOLES"):
        e["scenario"] = "reouverture"
    if "pourcent" in n and _a(q, "PRIVE"):
        e["recul_prive_pourcent"] = min(50.0, n["pourcent"])
    for norme in (40, 45):
        if re.search(rf"\bNORME (DE )?{norme}\b|\b{norme} ELEVES PAR", q):
            e["norme"] = norme
    m = re.search(r"(\d[\d .]*)\s*MUTATIONS?|MUTER\s*(\d[\d .]*)", q)
    if m:
        e["mutations_max"] = int(re.sub(r"[ .]", "", m.group(1) or m.group(2)))
    for lieu, niveau in [(p, "province") for p in provs] + [(r, "region") for r in regs]:
        mm = re.search(r"AU MOINS\s*(\d[\d .]*?)\s*(ENSEIGNANTS?|SALLES?)?\b(?:\s|$)", _chiffres(q))
        if mm:
            e.setdefault("exigences", []).append({"niveau": niveau, "nom": lieu, "type": "min_salles" if (mm.group(2) or "").startswith("SALLE") else "min_enseignants",
                                                  "valeur": int(re.sub(r"[ .]", "", mm.group(1)))})
    r = calculer_plan(e)
    demande = r.pop("_demande")
    lignes = r.pop("_lignes", {})
    pp = r["province_la_plus_chargee_eleves_par_enseignant"]
    tr = r["eleves_en_trop_dans_les_classes_surchargees"]
    top = ", ".join(f"{x['province']} (+{_nb(x['enseignants'])})" for x in r["provinces_les_plus_servies"][:5])
    defauts = _donnees()["meta"]["defauts"]
    moyens = (f"un budget de {_nb(e['budget_milliards_fcfa'], 1)} milliards de FCFA" if "budget_milliards_fcfa" in e
              else f"{_combien(e.get('enseignants', defauts['enseignants']), 'enseignant', 'enseignants')} et "
                   f"{_combien(e.get('salles', defauts['salles']), 'salle', 'salles')}")
    hyp = [f"si {_nb(e['recul_prive_pourcent'])} % des élèves du privé passent au public" if e.get("recul_prive_pourcent") else "",
           "si les écoles fermées rouvrent" if e.get("scenario") == "reouverture" else "",
           f"avec une norme de {e['norme']} élèves par enseignant" if e.get("norme") else ""]
    moyens += "".join(f", {h}" for h in hyp if h)
    texte = (f"Avec {moyens}, le plan Yennenga affecte {_combien(r['enseignants_affectes'], 'enseignant', 'enseignants')} et construit "
             f"{_combien(r['salles_construites'], 'salle', 'salles')}"
             + (f" ({_nb(e['enseignants'] - r['enseignants_affectes'])} restent sans affectation : pas de salle pour eux)"
                if e.get("enseignants") and r["enseignants_affectes"] < e["enseignants"] else "")
             + (f", avec {_nb(r['enseignants_mutes'])} mutations" if r.get("enseignants_mutes") else "")
             + f", pour {_nb(r['cout_total_milliards_fcfa'], 1)} milliards de FCFA ({r['cout_detail']}). "
             f"À la rentrée {r['pour_la_rentree']}, la province la plus chargée aurait {_nb(pp['plan_yennenga'])} élèves par enseignant, contre "
             f"{_nb(pp['partage_selon_le_nombre_d_eleves'])} en partageant selon le nombre d'élèves et {_nb(pp['sans_moyens_nouveaux'])} sans moyens nouveaux. "
             f"Élèves en trop dans les classes surchargées : {_nb(tr['plan_yennenga'])}"
             + (f", soit {_nb((tr['sans_moyens_nouveaux'] - tr['plan_yennenga']) / r['cout_total_milliards_fcfa'])} élèves sortis de la surcharge "
                f"par milliard de FCFA" if r["cout_total_milliards_fcfa"] else "")
             + f". Provinces les plus servies : {top}. "
             f"Ouvrez ce plan dans l'onglet Répartition pour le vérifier, l'exporter ou l'imprimer.")
    # la ou les provinces nommées dans la question : ce qu'elles reçoivent dans ce plan, en tête de réponse
    detail = []
    for nom in provs[:3]:
        l = lignes.get(nom)
        if not l:
            continue
        avant = l["eleves_horizon"] / l["maitres"] if l.get("maitres") else None
        recu = (f"{nom_officiel(nom)} reçoit {_combien(l['enseignants_attribues'], 'enseignant', 'enseignants')} et "
                f"{_combien(l['salles_attribuees'], 'salle', 'salles')}"
                + (f", avec {_nb(l['salles_rouvertes'])} salles d'écoles fermées à rouvrir" if l.get("salles_rouvertes") else "")
                + (f" ({'+' if l['solde_redeploiement'] > 0 else '−'}{_nb(abs(l['solde_redeploiement']))} par mutations)" if l.get("solde_redeploiement") else "")
                + (f" : de {_nb(avant)} à {_nb(l['ratio_maitre_apres'])} élèves par enseignant à la rentrée {r['pour_la_rentree']}"
                   if avant and l.get("ratio_maitre_apres") and "PAR ENSEIGNANT" not in _q(l.get("motif") or "") else "")
                + (f". {l['motif'][0].upper()}{l['motif'][1:]}" if l.get("motif") else "") + ".")
        detail.append(recu)
    if detail:
        texte = " ".join(detail) + " Pour tout le pays : " + texte[0].lower() + texte[1:]
    if r["statut"] != "meilleur plan possible":
        texte += f" (Statut du calcul : {r['statut']}.)"
    return texte, demande


def _texte_manques(provs: list[str], regs: list[str]) -> str:
    d = _donnees()
    ref, norme = d["meta"]["annee_reference"], config()["normes"]["eleves_par_maitre"]
    lignes = d["provinces"]
    if provs:
        lignes, lieu = [x for x in lignes if x["province"] in provs], " et ".join(nom_officiel(x) for x in provs)
    elif regs:
        lignes, lieu = [x for x in lignes if x["region"] in regs], "la région " + " et ".join(nom_officiel(x) for x in regs)
    else:
        lieu = "le pays"
    m = sum(x.get("maitres_manquants") or 0 for x in lignes)
    s_ = sum(x.get("salles_manquantes") or 0 for x in lignes)
    return (f"En {ref}, dans les écoles publiques, il manque {_combien(m, 'enseignant', 'enseignants')} et {_combien(s_, 'salle', 'salles')} "
            f"pour {lieu}, pour ramener chaque province à la norme de {norme} élèves par enseignant (somme des manques des provinces "
            f"au-dessus de la norme). Pour la rentrée {d['meta']['annee_horizon'][:4]}, avec les élèves attendus, calculez un plan dans "
            f"l'onglet Répartition. Source : annuaire DGESS {ref} ; calculs de l'outil.")


def _texte_sites(provs: list[str]) -> str:
    d = _donnees()
    sites = d["sites"]
    if provs:
        anc = {c["pcode_commune"]: c["province_ancienne"] for c in d["communes"]}
        sites = [x for x in sites if anc.get(x["pcode_commune"]) in provs]
    constr = [x for x in sites if x["recommandation"] == "construire"]
    rouv = len(sites) - len(constr)
    lieu = " et ".join(nom_officiel(x) for x in provs) if provs else "le pays"
    tete = sorted(constr, key=lambda x: -x["enfants_rapproches"])[:5]
    liste = " ; ".join(f"{x['commune']} ({_nb(x['enfants_rapproches'])} enfants rapprochés)" for x in tete)
    return (f"Pour {lieu}, l'outil propose {_combien(len(constr), 'site où construire', 'sites où construire')} et "
            f"{_combien(rouv, 'site où rouvrir d’abord les écoles fermées', 'sites où rouvrir d’abord les écoles fermées')}. "
            + (f"Les sites à construire qui rapprochent le plus d'enfants : {liste}. " if tete else "")
            + "Un site est une maille de 1 km choisie pour rapprocher le plus d'enfants restés à plus de 3 km d'une école ; "
              "à vérifier sur le terrain. Voir la carte, niveau Communes.")


BONJOUR = ("Bonjour. Je réponds avec les chiffres et les calculs de l'outil. Essayez par exemple : « Que se passe-t-il avec 2 000 "
           "enseignants et 800 salles ? », « Quelles sont les provinces les plus surchargées ? », « Pourquoi le Soum ne reçoit-il "
           "pas de salles ? », « Où manque-t-il le plus de filles ? ».")


def _texte_pays() -> str:
    d = _donnees()
    ref = d["meta"]["annee_reference"]
    pr = d["provinces"]
    e, m, sa = (sum(x.get(k) or 0 for x in pr) for k in ("eleves", "maitres", "salles"))
    tot = ""
    if d["annees"]:
        v = d["annees"]["valeurs"].get(ref, {})
        et = sum(x.get("t", {}).get("e") or 0 for x in v.values())
        tot = f" Public et privé ensemble : {_nb(et)} élèves."
    horizon = sum(x.get("eleves_horizon") or 0 for x in pr)
    if horizon:
        tot += f" Élèves du public attendus à la rentrée {d['meta']['annee_horizon'][:4]} : {_nb(horizon)} (prévision de l'outil)."
    return (f"En {ref}, les écoles publiques du primaire comptent {_nb(e)} élèves, {_nb(m)} enseignants et {_nb(sa)} salles, soit "
            f"{_nb(e / m, 1)} élèves par enseignant en moyenne (norme : {config()['normes']['eleves_par_maitre']}).{tot} "
            f"Mais la moyenne cache de grands écarts entre provinces : demandez « les provinces les plus surchargées ». Source : annuaire DGESS {ref}.")


def _texte_deux_plans(entrees: list[dict]) -> tuple[str, dict]:
    """Deux plans calculés et comparés dans la conversation ; le second s'ouvre dans l'onglet Répartition."""
    r = [calculer_plan(dict(e)) for e in entrees]
    demandes = [x.pop("_demande") for x in r]
    for x in r:
        x.pop("_lignes", None)

    def nom(e):
        return (f"{_nb(e['budget_milliards_fcfa'])} milliards" if "budget_milliards_fcfa" in e
                else f"{_nb(e['enseignants'])} enseignants et {_nb(e['salles'])} salles")
    a, b = r
    ta, tb = a["eleves_en_trop_dans_les_classes_surchargees"]["plan_yennenga"], b["eleves_en_trop_dans_les_classes_surchargees"]["plan_yennenga"]
    pa, pb = a["province_la_plus_chargee_eleves_par_enseignant"]["plan_yennenga"], b["province_la_plus_chargee_eleves_par_enseignant"]["plan_yennenga"]
    texte = (f"Deux plans comparés. Avec {nom(entrees[0])} : {_nb(a['enseignants_affectes'])} enseignants affectés, {_nb(a['salles_construites'])} salles, "
             f"{_nb(a['cout_total_milliards_fcfa'], 1)} milliards de FCFA, {_nb(ta)} élèves en trop dans les classes surchargées, province la plus "
             f"chargée à {_nb(pa)} élèves par enseignant. Avec {nom(entrees[1])} : {_nb(b['enseignants_affectes'])} enseignants, "
             f"{_nb(b['salles_construites'])} salles, {_nb(b['cout_total_milliards_fcfa'], 1)} milliards, {_nb(tb)} élèves en trop, province la plus "
             f"chargée à {_nb(pb)}. Écart : {_nb(abs(b['cout_total_milliards_fcfa'] - a['cout_total_milliards_fcfa']), 1)} milliards de FCFA "
             f"pour {_nb(abs(ta - tb))} élèves en trop {'de moins' if tb < ta else 'de plus'} avec le second plan. "
             "Le second plan s'ouvre dans l'onglet Répartition ; « Garder ce plan pour comparer » permet de les mettre côte à côte.")
    return texte, demandes[1]


AIDE = ("Je n'ai pas compris la question. Je sais répondre, par exemple, à : « Que se passe-t-il avec 2 000 enseignants et 800 salles ? », "
        "« Quelles sont les 5 provinces les plus surchargées ? », « Pourquoi le Soum ne reçoit-il pas de salles ? », « Le Kadiogo », "
        "« La commune de Djibo », « Que veut dire classement à confirmer ? ».")


def repondre(historique: list[dict]) -> dict:
    """historique : [{"role": "user"|"assistant", "content": texte}] ; la dernière entrée est la question.
    Réponse immédiate, calculée sur le serveur : aucun service extérieur."""
    if not disponible():
        raise AssistantIndisponible("L'assistant n'est pas activé sur ce serveur.")
    questions = [str(h.get("content", "")) for h in historique if h.get("role") == "user" and h.get("content")]
    if not questions:
        raise ValueError("Aucune question.")
    brut = questions[-1][: int(reglages().get("longueur_question_max", 600))]
    q = _q(brut)
    lx = _lieux()
    provs = _trouver(q, lx["provinces"])
    coms = [c for c in _trouver(q, lx["communes"]) if _cle(c) not in lx["provinces"]] if not provs or _a(q, "COMMUNE") else []
    if _a(q, "COMMUNE"):
        coms = _trouver(q, lx["communes"])
    regs = [r for r in _regions(q, lx["regions"]) if _cle(r) not in lx["provinces"]]
    if not provs and not coms:
        p = _approche(q, lx["provinces"])
        provs = [p] if p else []
    # « au moins 200 enseignants pour le Loroum » est une exigence, pas les moyens du plan
    exigence = re.search(r"AU MOINS\s*\d", _chiffres(q)) is not None and bool(provs or regs)
    n = _nombres(re.sub(r"AU MOINS\s*\d[\d .]*\s*(ENSEIGNANTS?|SALLES?)?", " ", _chiffres(q)))
    if re.search(r"\bSANS (LES |DE |AUCUNE )?(NOUVELLES )?SALLES?\b", q):
        n["salles"] = 0.0
    # « combien pour le Loroum si j'en ai 2 000 ? » : le nombre sans unité reprend celle de la question (enseignants, salles, milliards)
    hyp = re.search(r"\b(?:SI (?:J EN AI|J AI|ON A|ON EN A|NOUS AVONS|IL Y A)|AVEC)\s+(\d{1,3}(?:[ .]\d{3})+|\d+(?:,\d+)?)\b(?!\s*(?:%|POUR ?CENT|EN \d))", _chiffres(q))
    if hyp and not n:
        v = float(re.sub(r"[ .]", "", hyp.group(1)).replace(",", "."))
        if _a(q, "MILLIARD", "BUDGET", "FCFA") and 1 <= v <= 500:
            n["milliards"] = v
        elif _a(q, "SALLE") and not _a(q, "ENSEIGNANT", "MAITRE") and 10 <= v <= 20000:
            n["salles"] = v
        elif _a(q, "ENSEIGNANT", "MAITRE", "RECRUE", "POSTE") and 100 <= v <= 20000:
            n["enseignants"] = v
    m = re.search(r"\b(\d{1,2})\s+(PREMIERES?\s+)?PROVINCES\b|\bTOP\s*(\d{1,2})\b", q)
    nombre = int(next(g for g in m.groups() if g and g.strip().isdigit())) if m else 10

    definir = _a(q, "QUE VEUT DIRE", "QU EST CE QU", "C EST QUOI", "DEFINI", "SIGNIFI", "VEUT DIRE", "COMMENT EST CALCUL", "COMPTEZ",
                 "CALCULEZ", "MESUREZ", "COMMENT .*COMPT", "COMMENT .*MESUR",
                 "COMMENT ON CALCUL", "COMMENT SE CALCUL", "COMMENT LIRE", "D OU VIEN")
    # question de suite : « Et avec 3 000 ? » après une question de plan, « Et le Houet ? » après une province
    precedente = _q(questions[-2]) if len(questions) > 1 else ""
    nus = re.findall(r"\b(\d{1,3}(?:[ .]\d{3})+|\d{3,6})\b", _chiffres(q))
    prec_n = _nombres(precedente) if precedente else {}
    prec_plan = bool(prec_n) or _a(precedente, "PLAN", "BUDGET") if precedente else False
    suite = q.startswith(" ET ") or len(q.split()) <= 7
    modif = _a(q, "NORME", "ROUVR", "REOUVERTURE", "PRIVE", "MUTATION", "BUDGET")
    q_plan = q
    # « pourquoi ? », « et les filles ? », « et le privé là-bas ? » après une question sur une province
    if suite and not provs and not coms and not n and precedente:
        prec_provs = _trouver(precedente, lx["provinces"]) or ([x] if (x := _approche(precedente, lx["provinces"])) else [])
        if prec_provs and not prec_plan:
            provs = prec_provs[:1]
    if suite and prec_plan and not coms and not (provs and not n and not exigence):
        if not n and nus:
            n = {**prec_n, "enseignants": float(re.sub(r"[ .]", "", nus[0]))}
        elif n or modif or exigence:
            n = {**prec_n, **n}
        q_plan = precedente + q  # les hypothèses de la question précédente (norme, réouverture, privé) restent valables
    plan = (bool({"enseignants", "salles", "milliards"} & set(n)) or ("pourcent" in n and _a(q, "PRIVE")) or exigence
            or _a(q, "CALCUL.* PLAN", "PLAN AVEC", "SI ON", "AVEC SEULEMENT", "REPARTI")
            or (not provs and not coms and _a(q, "MEILLEUR PLAN", "LE PLAN", "UN PLAN") and not _a(q, "PLAN TYPE")))
    pays = (not provs and not coms and not regs and not n
            and _a(q, "COMBIEN D ELEVES", "COMBIEN D ENSEIGNANTS", "COMBIEN DE SALLES", "AU TOTAL", "DANS LE PAYS", "AU BURKINA")
            and not _a(q, "MANQU", "LOIN", "DEPLAC", "FILLE", "PRIVE", "LYCEE", "COLLEGE", "SECONDAIRE", "UNIVERSIT", "POST PRIMAIRE"))
    manques = _a(q, "MANQU", "IL FAUT COMBIEN", "BESOIN EN") and not _a(q, "FILLE") and not coms
    construire = _a(q, "OU CONSTRUIRE", "OU FAUT IL CONSTRUIRE", "OU BATIR", "SITES?", "NOUVELLES? ECOLES?", "OU OUVRIR")
    salut = len(q.split()) <= 3 and _a(q, "BONJOUR", "BONSOIR", "SALUT", "MERCI", "AIDE")
    singulier = _a(q, "LA PROVINCE LA PLUS", "LA PROVINCE LA MOINS", "QUELLE EST LA PROVINCE", "QUELLE PROVINCE")
    if singulier and not m:
        nombre = 1
    classer = _a(q, "LES PLUS", "LES MOINS", "LA PLUS", "LA MOINS", "LE PLUS FORT", "LE PLUS ELEVE", "LE PLUS GRAND", "LE PLUS FAIBLE", "LE MOINS", "LE PLUS BESOIN", "PLUS DE BESOIN", "QUI A LE PLUS", "OU MANQUE", "LE PLUS DE", "LE PLUS D ", "LE MOINS DE", "LE MOINS D ",
                 "OU Y A T IL", "PRIORITAIRE", "CLASSEMENT", "TOP", "QUELLES PROVINCES", "QUELLES SONT LES", "LISTE DES PROVINCES", "PROVINCES LES")
    classer = classer and not _a(q, "LIMITE", "SOURCE")
    # compréhension générale : lieux (toutes mailles), mesure, années ; mémoire de la question précédente
    from dcb import comprendre as cp
    from dcb import connaissances
    zones = cp.trouver_lieux(q, _cle)
    mesure = cp.trouver_mesure(q)
    if precedente and suite and not plan:
        p_zones, p_mesure = cp.trouver_lieux(precedente, _cle), cp.trouver_mesure(precedente)
        if not zones and p_zones and (mesure or cp.trouver_annees(q)) and not _a(q, "PAYS", "BURKINA", "NATIONAL"):
            zones = p_zones                       # « et en 2019 ? », « et les filles ? » : même lieu
        if not mesure and p_mesure and (zones or cp.trouver_annees(q)) and not _a(q, "POURQUOI", "COMPAR"):
            mesure = p_mesure                     # « et le Houet ? » : même mesure
    if not zones and not provs and not coms:
        # faute de frappe sur une commune (« Ouagadougo »)
        c_proche = _approche(q, {k: v for k, v in _lieux()["communes"].items()})
        if c_proche:
            zones = cp.trouver_lieux(_q(c_proche), _cle)
    if not coms and not provs and len(zones) == 1 and zones[0].genre == "commune" and not mesure:
        coms = [zones[0].nom]                     # commune reconnue par son nom usuel ou malgré une faute de frappe
    comparaison = len(zones) >= 2 and not mesure and not plan
    portrait = (len(zones) == 1 and not mesure and not plan and zones[0].genre in ("region", "region_2025", "province_2025")
                and not definir and not classer)
    pourquoi = _a(q, "POURQUOI") and bool(provs)
    nationaux = mesure and not zones and mesure.cle in ("eleves", "enseignants", "salles") and not classer and not cp.trouver_annees(q)
    texte, demande, sujet, actions, relances = None, None, None, [], []
    deux_plans = None
    if _a(q, "COMPAR", "DIFFERENCE", "ENTRE .* ET", " OU ", "VERSUS", "VS ") and not provs and not coms:
        valeurs = [float(re.sub(r"[ .]", "", x)) for x in re.findall(r"\b(\d{1,3}(?:[ .]\d{3})+|\d+)\b", _chiffres(q))]
        if _a(q, "MILLIARD", "MDS?", "BUDGET") and len([v for v in valeurs if 1 <= v <= 500]) >= 2:
            v2 = [v for v in valeurs if 1 <= v <= 500][:2]
            deux_plans = [{"budget_milliards_fcfa": v} for v in v2]
        elif _a(q, "ENSEIGNANT", "MAITRE", "RECRUE", "POSTE", "PROF") and len([v for v in valeurs if 100 <= v <= 20000]) >= 2:
            v2 = [int(v) for v in valeurs if 100 <= v <= 20000][:2]
            deux_plans = [{"enseignants": v, "salles": int(n.get("salles", _donnees()["meta"]["defauts"]["salles"]))} for v in v2]
    procedure = (_a(q, "COMMENT (ON |JE |FAIRE|FAIT ON|EST CALCUL|PREVO|VOIR|AVOIR|OBTENIR|EXPORTER|IMPRIMER|CALCULER|UTILISER|IMPORTER|METTRE|"
                    "RETIRER|COMPARER|TELECHARGER|DECLARER|AJOUTER|LIRE|CHANGER|IMPOSER|ACCEDER|TU )")
                 and not ({"enseignants", "salles", "milliards"} & set(n)) and not zones)
    fiche = connaissances.chercher(q) if procedure else None
    try:
        if deux_plans:
            texte, demande = _texte_deux_plans(deux_plans)
            sujet = "plan"
            relances = ["Et avec 1 000 mutations ?", "Comment comparer deux plans dans l'onglet Répartition ?"]
        elif definir and (t := _definir(q)):
            texte, sujet = t, "definition"
        elif fiche is not None:
            texte, sujet = fiche.texte, "outil"
            if fiche.vue:
                actions = [{"libelle": f"Ouvrir l'onglet {dict(carte='Carte', repartition='Répartition', donnees='Données', methode='Méthode').get(fiche.vue, fiche.vue)}", "vue": fiche.vue}]
        elif plan and not (provs and _a(q, "POURQUOI")):
            texte, demande = _texte_plan(q_plan, n, provs, regs)
            sujet = "plan"
            relances = ["Et avec 1 000 mutations ?", "Et si les écoles fermées rouvrent ?", "Et avec un budget de 20 milliards ?"]
        elif portrait:
            r = cp.comparer_lieux(zones)
            texte, sujet, actions, relances = r["reponse"], "donnees", r["actions"], r["suggestions"]
        elif comparaison:
            r = cp.comparer_lieux(zones)
            texte, sujet, actions, relances = r["reponse"], "comparaison", r["actions"], r["suggestions"]
        elif mesure and not pourquoi and not nationaux and not (construire and not zones and mesure.cle != "sites") \
                and (r := cp.repondre_donnees(q, zones, mesure, classer=classer and not zones, nombre=nombre)):
            texte, sujet, actions, relances = r["reponse"], "donnees", r["actions"], r["suggestions"]
        elif salut:
            texte, sujet = BONJOUR, "salutation"
        elif construire and not plan and not classer:
            texte, sujet = _texte_sites(provs), "sites"
        elif pays:
            texte, sujet = _texte_pays(), "pays"
        elif manques and not classer:
            texte, sujet = _texte_manques(provs, regs), "manques"
        elif classer and not (provs and not _a(q, "PROVINCES")):
            texte, sujet = _texte_classement(q, nombre), "classement"
        elif provs:
            texte = " ".join(_texte_province(p, q) for p in provs[:2])
            sujet = "province"
            actions = [{"libelle": f"Voir {nom_officiel(provs[0])} sur la carte", "vue": "carte", "action": "province", "arg": provs[0]}]
            relances = [f"Élèves par enseignant au {nom_officiel(provs[0])} depuis 2017", f"Compare le {nom_officiel(provs[0])} et le {'Houet' if provs[0] != 'HOUET' else 'Kadiogo'}",
                        f"Pourquoi le {nom_officiel(provs[0])} reçoit-il ce qu'il reçoit ?"]
        elif coms:
            texte, sujet = _texte_commune(coms[0]), "commune"
        elif (t := _definir(q)) and _a(q, "POURQUOI", "MIEUX", "PROPORTIONNEL", "PARTAGE", "INVENT", "IA", "FIABL", "DECIDE"):
            texte, sujet = t, "definition"
        elif (f := connaissances.chercher(q)) is not None:
            texte, sujet = f.texte, "outil"
            if f.vue:
                actions = [{"libelle": f"Ouvrir l'onglet {dict(carte='Carte', repartition='Répartition', donnees='Données', methode='Méthode').get(f.vue, f.vue)}", "vue": f.vue}]
        elif t := _definir(q):
            texte, sujet = t, "definition"
    except ValueError as e:
        texte, sujet = f"Je ne peux pas calculer ce plan : {e}", "erreur"
    except Exception:  # noqa: BLE001 - une erreur de calcul ne doit jamais faire tomber la conversation
        texte, sujet = ("Le calcul n'a pas abouti. Réessayez dans un instant, ou calculez le plan dans l'onglet Répartition."), "erreur"
    if not texte:
        relances = ["Élèves par enseignant au Kadiogo", "Compare le Soum et le Loroum", "Comment mettre à jour les données ?"]
    return {"reponse": texte or AIDE, "plan": demande, "outils": [sujet or "aide"], "actions": actions, "suggestions": relances[:3]}
