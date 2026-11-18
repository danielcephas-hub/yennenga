"""Compréhension des questions sur les données, sans IA générative.

Une question est décomposée en quatre éléments :
- un ou plusieurs LIEUX : pays, région ou province des annuaires (13 et 45), région ou province du découpage de 2025, commune ;
- une MESURE, reconnue par ses synonymes, dans un catalogue d'une trentaine d'indicateurs ;
- une OPÉRATION : valeur, comparaison entre lieux, évolution entre deux années, classement ;
- une ANNÉE scolaire (2017-2018 à 2024-2025), la plus récente par défaut.

Chaque réponse est calculée sur les chiffres publiés par l'outil (outputs/web), avec l'année et la source, et accompagnée
d'actions (voir sur la carte) et de questions de relance. Rien n'est inventé : une mesure absente pour un lieu est dite absente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from dcb.territoire import nom_officiel


# --- outils de texte (les mêmes conventions que l'assistant : majuscules sans accents) -----------------------------

def _a(q: str, *motifs: str) -> bool:
    return any(re.search(r"\b" + m, q) for m in motifs)


def _nb(x, n=0) -> str:
    if x is None:
        return "—"
    v = round(float(x), n)
    return f"{v:,.{n}f}".replace(",", " ").replace(".", ",")


def _pc(x, n=0) -> str:
    return "—" if x is None else f"{_nb(100 * float(x), n)} %"


# --- lieux ------------------------------------------------------------------------------------------------------------

@dataclass
class Zone:
    """Un lieu de la question : les provinces des annuaires et les communes qui le composent."""
    nom: str                       # nom affiché
    genre: str                     # pays, region, province, region_2025, province_2025, commune
    provinces: list[str]           # provinces des annuaires (clés de provinces.json)
    communes: list[str]            # codes des communes
    cle: str = ""                  # identifiant pour les actions (province des annuaires, code de commune)
    note: str = ""                 # précision sur le découpage

    @property
    def article(self) -> str:
        if self.genre == "pays":
            return "le pays"
        return self.nom


@lru_cache(maxsize=1)
def _index_lieux(cle_texte) -> dict:
    """Tables nom normalisé → zone, construites une fois à partir des données publiées."""
    from dcb.assistant import _donnees
    d = _donnees()
    prov = d["provinces"]
    com = d["communes"]
    zones: dict[str, Zone] = {}
    par_prov_anc: dict[str, list[str]] = {}
    for c in com:
        par_prov_anc.setdefault(c["province_ancienne"], []).append(c["pcode_commune"])
    regions_anc: dict[str, list[str]] = {}
    for p in prov:
        regions_anc.setdefault(p["region"], []).append(p["province"])
    # 2025 : provinces et régions du nouveau découpage, à partir des communes
    p25: dict[str, list[dict]] = {}
    r25: dict[str, list[dict]] = {}
    for c in com:
        p25.setdefault(c["province"], []).append(c)
        r25.setdefault(c["region"], []).append(c)

    def ajouter(nom: str, z: Zone):
        k = cle_texte(nom)
        if k and k not in zones:
            zones[k] = z

    for p in prov:
        nom = nom_officiel(p["province"])
        z = Zone(nom, "province", [p["province"]], par_prov_anc.get(p["province"], []), cle=p["province"])
        ajouter(p["province"], z)
        ajouter(nom, z)
    for r, ps in regions_anc.items():
        nom = nom_officiel(r)
        z = Zone(nom, "region", ps, [c for pr in ps for c in par_prov_anc.get(pr, [])], cle=r, note="région des annuaires (13)")
        ajouter(r, z)
        ajouter(nom, z)
    for nom, cs in p25.items():
        anc = sorted({c["province_ancienne"] for c in cs})
        ajouter(nom, Zone(nom, "province_2025", anc, [c["pcode_commune"] for c in cs], cle=anc[0],
                          note=f"province du découpage de 2025 ; dans les annuaires : {', '.join(nom_officiel(a) for a in anc)}"))
    for nom, cs in r25.items():
        anc = sorted({c["province_ancienne"] for c in cs})
        ajouter(nom, Zone(nom, "region_2025", anc, [c["pcode_commune"] for c in cs],
                          note=f"région du découpage de 2025, soit {len(anc)} province(s) des annuaires"))
    communes: dict[str, Zone] = {}
    for c in com:
        z = Zone(c["commune"], "commune", [c["province_ancienne"]], [c["pcode_commune"]], cle=c["pcode_commune"],
                 note=f"province {c['province']} (2025), {nom_officiel(c['province_ancienne'])} dans les annuaires")
        ajouter(c["commune"], z)
        communes.setdefault(cle_texte(c["commune"]), z)
    zones["__communes__"] = communes  # type: ignore[assignment]
    # noms usuels des grandes villes
    for court, nom in (("OUAGA", "Ouagadougou"), ("BOBO", "Bobo-Dioulasso"), ("FADA", "Fada-Ngourma")):
        z = zones.get(cle_texte(nom))
        if z:
            zones.setdefault(court, z)
    return zones


_MOTS_COMMUNS = {"EST", "NORD", "CENTRE", "OUEST", "SUD", "SAHEL"}


def trouver_lieux(q: str, cle_texte) -> list[Zone]:
    """Lieux cités, du nom le plus long au plus court, sans chevauchement ; la province l'emporte sur la commune homonyme,
    sauf si la question dit « commune »."""
    zones = dict(_index_lieux(cle_texte))
    communes = zones.pop("__communes__")
    trouves, reste = [], q
    commune_demandee = _a(q, "COMMUNE", "VILLE")
    for k in sorted(zones, key=len, reverse=True):
        if f" {k} " not in reste:
            continue
        if k in _MOTS_COMMUNS and not re.search(rf"\b(REGION( DU| DE L| DE LA)?|DU|AU|LE|LA|L|DANS|POUR)\s+{k}\b", q):
            continue
        z = zones[k]
        if commune_demandee and z.genre != "commune" and k in communes:
            z = communes[k]  # « la commune de Gourcy » : la commune, pas la province homonyme
        trouves.append(z)
        reste = reste.replace(f" {k} ", " | ")
    return trouves


def pays() -> Zone:
    from dcb.assistant import _donnees
    d = _donnees()
    return Zone("Burkina Faso", "pays", [p["province"] for p in d["provinces"]], [c["pcode_commune"] for c in d["communes"]])


# --- mesures ------------------------------------------------------------------------------------------------------------

@dataclass
class Mesure:
    cle: str
    libelle: str                         # « élèves par enseignant dans les écoles publiques »
    motifs: tuple[str, ...]              # expressions reconnues (après normalisation)
    source: str
    format: str = "nombre"               # nombre, ratio, part, indice
    annuelle: bool = False               # disponible pour chaque année 2017-2025
    maille: str = "province"             # province ou commune
    calcul: Callable | None = None       # (zone, annee) -> valeur
    norme: float | None = None           # repère affiché à côté de la valeur
    plus_est_mieux: bool = False
    exclut: tuple[str, ...] = ()         # expressions qui écartent cette mesure
    priorite: int = 0                    # départage quand plusieurs mesures sont reconnues
    groupes: list = field(default_factory=list)


def _obs(annee: str) -> dict:
    from dcb.assistant import _donnees
    a = _donnees().get("annees") or {}
    return (a.get("valeurs") or {}).get(annee, {})


def _somme_obs(z: Zone, annee: str, statut: str, champ: str):
    v = _obs(annee)
    vals = [v[p][statut][champ] for p in z.provinces if p in v and statut in v[p] and v[p][statut].get(champ) is not None]
    return sum(vals) if vals else None


def _ratio_obs(z: Zone, annee: str, num: tuple[str, str], den: tuple[str, str], facteur: float = 1.0):
    a, b = _somme_obs(z, annee, *num), _somme_obs(z, annee, *den)
    return facteur * a / b if a is not None and b else None


def _part_precaires(z: Zone, annee: str):
    v = _obs(annee)
    num = den = 0.0
    for p in z.provinces:
        o = (v.get(p) or {}).get("pu") or {}
        if o.get("prec") is not None and o.get("s"):
            num += o["prec"] * o["s"]
            den += o["s"]
    return num / den if den else None


def _prov(z: Zone, champ: str, somme: bool = True):
    from dcb.assistant import _donnees
    vals = [p.get(champ) for p in _donnees()["provinces"] if p["province"] in z.provinces and p.get(champ) is not None]
    if not vals:
        return None
    return sum(vals) if somme else (vals[0] if len(vals) == 1 else None)


def _com(z: Zone, champ: str):
    from dcb.assistant import _donnees
    codes = set(z.communes)
    vals = [c.get(champ) for c in _donnees()["communes"] if c["pcode_commune"] in codes and isinstance(c.get(champ), (int, float))]
    return sum(vals) if vals else None


def _sites(z: Zone, recommandation: str | None = None):
    from dcb.assistant import _donnees
    codes = set(z.communes)
    return sum(1 for s in _donnees()["sites"] if s["pcode_commune"] in codes and (recommandation is None or s["recommandation"] == recommandation))


def _ratio_plan(z: Zone):
    from dcb.assistant import _donnees
    ps = [p for p in _donnees()["provinces"] if p["province"] in z.provinces]
    e = sum(p.get("eleves_horizon") or 0 for p in ps)
    m = sum((p.get("maitres") or 0) + (p.get("enseignants_attribues") or 0) for p in ps)
    return e / m if m else None


SRC_ANN = "annuaire statistique du primaire, DGESS"
SRC_OUTIL = "calcul de l'outil"


@lru_cache(maxsize=1)
def mesures() -> list[Mesure]:
    from dcb.indicateurs import config
    cfg = config()
    nm = cfg["normes"]["eleves_par_maitre"]
    return [
        # observées chaque année (annuaires)
        Mesure("ratio_maitre", "élèves par enseignant dans les écoles publiques", ("ELEVES PAR (ENSEIGNANT|MAITRE|INSTITUTEUR|PROF)", "RATIO", "TAUX D ENCADREMENT", "SURCHARG", "CHARGE DES CLASSES", "EFFECTIF PAR ENSEIGNANT"),
               SRC_ANN, "ratio", True, calcul=lambda z, a: _ratio_obs(z, a, ("pu", "e"), ("pu", "m")), norme=nm, priorite=5),
        Mesure("ratio_salle", "élèves par salle dans les écoles publiques", ("ELEVES PAR (SALLE|CLASSE)", "PAR SALLE", "TAILLE DES CLASSES", "CLASSES PLEINES"),
               SRC_ANN, "ratio", True, calcul=lambda z, a: _ratio_obs(z, a, ("pu", "e"), ("pu", "s")), norme=cfg["normes"]["eleves_par_salle"], priorite=5),
        Mesure("part_prive", "part des élèves scolarisés dans le privé", ("PART DU PRIVE", "POURCENTAGE .*PRIVE", "PROPORTION .*PRIVE", "PRIVE REPRESENTE", "POIDS DU PRIVE"),
               SRC_ANN, "part", True, calcul=lambda z, a: _ratio_obs(z, a, ("pr", "e"), ("t", "e")), priorite=6),
        Mesure("eleves_prive", "élèves du privé", ("ELEVES DU PRIVE", "ELEVES DANS LE PRIVE", "ECOLES PRIVEES", "PRIVE"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "pr", "e"), exclut=("PART", "POURCENT", "PROPORTION", "PAR ENSEIGNANT", "ENSEIGNANTS DU PRIVE"), priorite=3),
        Mesure("enseignants_prive", "enseignants du privé", ("ENSEIGNANTS? DU PRIVE", "MAITRES? DU PRIVE", "ENSEIGNANTS? DANS LE PRIVE"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "pr", "m"), priorite=6),
        Mesure("filles_100", "filles pour 100 garçons inscrits (public et privé)", ("FILLES POUR 100", "PARITE", "GENRE", "FILLES ET GARCONS", "SCOLARISATION DES FILLES", "FILLES"),
               SRC_ANN, "ratio", True, calcul=lambda z, a: _ratio_obs(z, a, ("t", "f"), ("t", "g"), 100), norme=100, plus_est_mieux=True,
               exclut=("NOMBRE DE FILLES", "COMBIEN DE FILLES"), priorite=4),
        Mesure("filles", "filles inscrites (public et privé)", ("NOMBRE DE FILLES", "COMBIEN DE FILLES"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "t", "f"), priorite=6),
        Mesure("eleves_total", "élèves inscrits, public et privé", ("PUBLIC ET PRIVE", "TOUS LES ELEVES", "ELEVES AU TOTAL", "TOTAL DES ELEVES", "SCOLARISES"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "t", "e"), priorite=4),
        Mesure("eleves", "élèves des écoles publiques", ("ELEVES", "EFFECTIFS?", "INSCRITS", "ENFANTS SCOLARISES"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "pu", "e"), exclut=("PAR ", "6 A 11", "6 11", "LOIN", "PLUS DE 3"), priorite=1),
        Mesure("enseignants", "enseignants des écoles publiques", ("ENSEIGNANTS?", "MAITRES?", "INSTITUTEURS?", "PROFESSEURS?", "PROFS?"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "pu", "m"), exclut=("PAR ENSEIGNANT", "PAR MAITRE", "MANQU", "RECOI", "RECU", "PLAN"), priorite=2),
        Mesure("salles", "salles de classe des écoles publiques", ("SALLES?", "SALLES DE CLASSE"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "pu", "s"), exclut=("PAR SALLE", "PAILLE", "BANCO", "PRECAIRE", "MANQU", "RECOI", "RECU", "PLAN", "CONSTRUI"), priorite=2),
        Mesure("ecoles", "écoles publiques ouvertes", ("ECOLES?", "ETABLISSEMENTS?"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "pu", "ec"), exclut=("FERM", "LOIN", "PRIVE", "REPEREES", "OSM", "OPENSTREETMAP", "NOUVELLE", "CONSTRUI"), priorite=1),
        Mesure("ecoles_total", "écoles ouvertes, public et privé", ("ECOLES PUBLIQUES ET PRIVEES", "TOUTES LES ECOLES"),
               SRC_ANN, "nombre", True, calcul=lambda z, a: _somme_obs(z, a, "t", "ec"), priorite=5),
        Mesure("precaires", "part des salles en paille ou banco (public)", ("PAILLE", "BANCO", "PRECAIRE", "ETAT DES SALLES", "BATI"),
               SRC_ANN, "part", True, calcul=_part_precaires, priorite=6),
        # calculs de l'outil sur l'année de référence
        Mesure("indice", "indice de besoin (0 à 1)", ("INDICE", "BESOIN", "PRIORITE", "RANG", "DIFFICULTE"),
               SRC_OUTIL, "indice", calcul=lambda z, a: _prov(z, "indice_besoin", somme=False), exclut=("BESOIN EN", "MANQU"), priorite=3),
        Mesure("fermees", "part des écoles fermées depuis le plus haut niveau 2017-2025", ("ECOLES? FERMEES?", "FERMETURES?", "FERME", "TOUCHEE", "INSECURITE", "CRISE SECURITAIRE"),
               "annuaires DGESS, public et privé", "part", calcul=lambda z, a: (lambda o, f: (1 - o / f) if o is not None and f else None)(
                   _somme_obs(z, a, "t", "ec"), max((_somme_obs(z, x, "t", "ec") or 0) for x in annees())), priorite=6),
        Mesure("manque_maitres", "enseignants manquants pour atteindre la norme (public)", ("ENSEIGNANTS? MANQU", "MANQUE D ENSEIGNANTS", "MANQUE.*ENSEIGNANTS", "DEFICIT D ENSEIGNANTS", "BESOIN EN ENSEIGNANTS"),
               SRC_OUTIL, "nombre", calcul=lambda z, a: _prov(z, "maitres_manquants"), priorite=7),
        Mesure("manque_salles", "salles manquantes pour atteindre la norme (public)", ("SALLES? MANQU", "MANQUE DE SALLES", "MANQUE.*SALLES", "DEFICIT DE SALLES", "BESOIN EN SALLES"),
               SRC_OUTIL, "nombre", calcul=lambda z, a: _prov(z, "salles_manquantes"), priorite=7),
        Mesure("eleves_2030", "élèves du public attendus à la rentrée 2030", ("2030", "PREVISION", "ATTENDUS", "A L HORIZON", "DANS LE FUTUR", "FUTUR"),
               "prévision de l'outil", "nombre", calcul=lambda z, a: _prov(z, "eleves_horizon"), exclut=("ENFANTS", "6 A 11", "6 11"), priorite=4),
        Mesure("plan_enseignants", "enseignants reçus dans le plan type (3 000 enseignants, 1 500 salles)", ("RECOI.*ENSEIGNANTS", "ENSEIGNANTS RECUS", "ENSEIGNANTS.*PLAN", "PLAN TYPE"),
               SRC_OUTIL, "nombre", calcul=lambda z, a: _prov(z, "enseignants_attribues"), priorite=8),
        Mesure("plan_salles", "salles reçues dans le plan type", ("RECOI.*SALLES", "SALLES RECUES", "SALLES.*PLAN"),
               SRC_OUTIL, "nombre", calcul=lambda z, a: _prov(z, "salles_attribuees"), priorite=8),
        Mesure("ratio_2030", "élèves par enseignant à la rentrée 2030 avec le plan type", ("APRES LE PLAN", "AVEC LE PLAN", "RATIO EN 2030", "PAR ENSEIGNANT EN 2030"),
               SRC_OUTIL, "ratio", calcul=lambda z, a: _ratio_plan(z), norme=nm, priorite=9),
        # communes (recensement, WorldPop, CONASUR, OSM)
        Mesure("population", "habitants (recensement 2019)", ("HABITANTS", "POPULATION"),
               "RGPH 2019, INSD", "nombre", maille="commune", calcul=lambda z, a: _com(z, "population_2019"), exclut=("SCOLAIRE",), priorite=5),
        Mesure("enfants", "enfants de 6 à 11 ans (2019)", ("ENFANTS? DE 6", "6 A 11", "6 11", "AGE SCOLAIRE", "POPULATION SCOLAIRE", "ENFANTS EN AGE"),
               "RGPH 2019, INSD", "nombre", maille="commune", calcul=lambda z, a: _com(z, "enfants_6_11_2019"), exclut=("2030", "ATTENDUS", "LOIN"), priorite=6),
        Mesure("enfants_2030", "enfants de 6 à 11 ans attendus en 2030", ("ENFANTS.*2030", "2030.*ENFANTS", "ENFANTS ATTENDUS"),
               "projection INSD répartie par commune", "nombre", maille="commune", calcul=lambda z, a: _com(z, "enfants_6_11_2030"), priorite=7),
        Mesure("loin", "enfants à plus de 3 km d'une école", ("LOIN", "PLUS DE 3", "3 KM", "DISTANCE", "ACCES A L ECOLE", "ELOIGNES"),
               "WorldPop 2030 calé sur l'INSD, écoles OpenStreetMap", "nombre", maille="commune", calcul=lambda z, a: _com(z, "eloignes_borne_basse"), priorite=7),
        Mesure("deplaces", "personnes déplacées accueillies (fin 2022)", ("DEPLACES", "PDI", "REFUGIES", "DEPLACEMENT"),
               "CONASUR, fin 2022", "nombre", maille="commune", calcul=lambda z, a: _com(z, "pdi_total"), priorite=7),
        Mesure("ecoles_osm", "écoles repérées sur OpenStreetMap (liste partielle)", ("REPEREES", "OSM", "OPENSTREETMAP", "GEOLOCALISEES", "SUR LA CARTE"),
               "OpenStreetMap", "nombre", maille="commune", calcul=lambda z, a: _com(z, "sites_scolaires_osm"), priorite=7),
        Mesure("sites", "sites proposés pour une école", ("SITES?", "OU CONSTRUIRE", "NOUVELLES? ECOLES?"),
               SRC_OUTIL, "nombre", maille="commune", calcul=lambda z, a: _sites(z), priorite=6),
    ]


@lru_cache(maxsize=1)
def annees() -> list[str]:
    from dcb.assistant import _donnees
    a = _donnees().get("annees") or {}
    return list(a.get("annees") or [])


def trouver_mesure(q: str) -> Mesure | None:
    candidates = []
    for m in mesures():
        if any(re.search(r"\b" + mo, q) for mo in m.motifs) and not any(re.search(r"\b" + e, q) for e in m.exclut):
            candidates.append(m)
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.priorite)


def trouver_annees(q: str) -> list[str]:
    """« 2019-2020 », « 2019 », « en 2020 » → années scolaires connues, dans l'ordre de la question."""
    ans = annees()
    out = []
    for deb, fin in re.findall(r"\b(20[12]\d)(?:\s*[-/ ]\s*(20[12]\d))?\b", q):
        d = int(deb)
        cand = [f"{d}-{d + 1}"] if not fin else [f"{d}-{fin}"]
        cand.append(f"{d - 1}-{d}")
        a = next((c for c in cand if c in ans), None)
        if a and a not in out:
            out.append(a)
    return out


# --- réponses -----------------------------------------------------------------------------------------------------------

def _fmt(m: Mesure, v) -> str:
    if v is None:
        return "non disponible"
    if m.format == "part":
        return _pc(v, 1 if v < 0.1 else 0)
    if m.format == "indice":
        return _nb(v, 2)
    if m.format == "ratio":
        return _nb(v, 1 if v < 100 else 0)
    return _nb(v)


def _commentaire(m: Mesure, v) -> str:
    if v is None or m.norme is None:
        return ""
    ecart = v - m.norme
    if m.plus_est_mieux:
        return " (autant de filles que de garçons)" if abs(ecart) < 1 else (f" : {_nb(abs(ecart))} filles de moins pour 100 garçons" if ecart < 0 else " : plus de filles que de garçons")
    if abs(ecart) < 0.5:
        return f" (norme : {_nb(m.norme)}, atteinte)"
    return f" (norme : {_nb(m.norme)}, soit {_nb(abs(ecart))} {'au-dessus' if ecart > 0 else 'en dessous'})"


def _rang(m: Mesure, z: Zone, annee: str) -> str:
    """Place de la province parmi les 45 pour cette mesure (quand c'est parlant)."""
    if z.genre != "province" or m.maille != "province" or m.format not in ("ratio", "part", "indice"):
        return ""
    from dcb.assistant import _donnees
    vals = []
    for p in _donnees()["provinces"]:
        zp = Zone(p["province"], "province", [p["province"]], [])
        v = m.calcul(zp, annee)
        if v is not None:
            vals.append((p["province"], v))
    if len(vals) < 10:
        return ""
    desc = not m.plus_est_mieux
    vals.sort(key=lambda t: t[1], reverse=desc)
    rang = next((i + 1 for i, (p, _) in enumerate(vals) if p == z.provinces[0]), None)
    if rang is None:
        return ""
    sens = "la plus faible" if m.plus_est_mieux else "la plus forte"
    return f" C'est la {'1re' if rang == 1 else f'{rang}e'} valeur {sens} des {len(vals)} provinces."


def _non_disponible_commune(m: Mesure, z: Zone, annee: str | None = None) -> str | None:
    if z.genre == "commune" and m.maille == "province":
        prov = Zone(nom_officiel(z.provinces[0]), "province", z.provinces, [], cle=z.provinces[0])
        v = m.calcul(prov, annee)
        chiffre = (f" Pour toute la province {prov.nom} : {_fmt(m, v)}{'' if m.format in ('part', 'indice') else ' ' + m.libelle}"
                   f"{_commentaire(m, v)}{', en ' + annee if m.annuelle and annee else ''}.") if v is not None else ""
        return (f"Les annuaires ne donnent pas les {m.libelle.split(' (')[0]} par commune : seulement par province. "
                f"{z.nom} fait partie de la province {prov.nom} dans les annuaires.{chiffre}")
    return None


def _actions(zs: list[Zone]) -> list[dict]:
    out = []
    for z in zs[:2]:
        if z.genre == "province":
            out.append({"libelle": f"Voir {z.nom} sur la carte", "vue": "carte", "action": "province", "arg": z.cle})
        elif z.genre == "commune":
            out.append({"libelle": f"Voir {z.nom} sur la carte (communes de la province {nom_officiel(z.provinces[0])})", "vue": "carte", "action": "communes", "arg": z.provinces[0]})
    return out


def _suggestions(m: Mesure, zs: list[Zone], annee: str) -> list[str]:
    s = []
    z = zs[0] if zs else None
    if m.annuelle and annees() and annee != annees()[0]:
        s.append(f"Évolution depuis {annees()[0][:4]} ?")
    if z and z.genre == "province" and len(zs) == 1:
        voisine = "Houet" if z.cle != "HOUET" else "Kadiogo"
        s.append(f"Comparer avec le {voisine}")
        s.append(f"Pourquoi le {z.nom} reçoit-il ce qu'il reçoit dans le plan ?")
    if m.maille == "province" and m.format in ("ratio", "part", "indice"):
        court = m.libelle.split(" (")[0].replace(" dans les écoles publiques", "")
        s.append(f"Les 5 provinces les plus fortes : {court}")
    return s[:3]


def repondre_donnees(q: str, zs: list[Zone], m: Mesure, classer: bool = False, nombre: int = 10) -> dict | None:
    """Réponse chiffrée à une question sur une mesure. None si la question ne relève pas de ce moteur."""
    ans = trouver_annees(q)
    ref = annees()[-1] if annees() else None
    evolution = m.annuelle and (len(ans) >= 2 or _a(q, "EVOLU", "DEPUIS", "A AUGMENTE", "A BAISSE", "A DIMINUE", "TENDANCE", "PROGRESS", "CHANGE", "VARIE"))
    if m.annuelle and evolution:
        a0 = ans[0] if ans else annees()[0]
        a1 = ans[1] if len(ans) >= 2 else (ans[0] if ans and ans[0] != a0 else ref)
        if a0 == a1:
            a0 = annees()[0]
    annee = ans[0] if ans and m.annuelle else ref
    if not m.annuelle and ans and ans[0] != ref:
        note_annee = f" (disponible seulement pour {ref})"
    else:
        note_annee = ""

    # classement des provinces (ou des communes pour les mesures communales)
    if classer and not zs:
        return _classement(q, m, annee, nombre)

    cibles = zs or [pays()]
    lignes, vals = [], []
    for z in cibles[:4]:
        nd = _non_disponible_commune(m, z, a1 if (m.annuelle and evolution) else annee)
        if nd:
            lignes.append(nd)
            continue
        if m.annuelle and evolution:
            v0, v1 = m.calcul(z, a0), m.calcul(z, a1)
            if v0 is None or v1 is None:
                lignes.append(f"{z.article} : {m.libelle} non disponible pour ces années.")
                continue
            d = v1 - v0
            rel = f" ({'+' if d >= 0 else '−'}{_pc(abs(d / v0), 0)})" if v0 and m.format == "nombre" else ""
            dd = _pc(abs(d), 1) if m.format == "part" else _fmt(m, abs(d))
            lignes.append(f"{z.article}, {m.libelle} : de {_fmt(m, v0)} en {a0} à {_fmt(m, v1)} en {a1}, "
                          f"soit {'+' if d >= 0 else '−'}{dd}{' point' + ('s' if abs(100 * d) >= 2 else '') if m.format == 'part' else ''}{rel}.")
        else:
            v = m.calcul(z, annee)
            vals.append((z, v))
            if v is None:
                lignes.append(f"{z.article} : {m.libelle} non disponible.")
            else:
                corps = (f"{m.libelle} : {_fmt(m, v)}" if m.format in ("part", "indice") else f"{_fmt(m, v)} {m.libelle}")
                if m.cle == "loin":
                    vmax = _com(z, "eloignes_borne_haute")
                    corps = (f"entre {_nb(v)} et {_nb(vmax)} enfants à plus de 3 km d'une école (le minimum suppose les écoles absentes "
                             f"des cartes placées au plus près des enfants ; le maximum ne compte que les écoles repérées sur OpenStreetMap)")
                elif m.format == "nombre" and round(v) == 0:
                    corps = {"sites": "aucun site proposé pour une école", "deplaces": "aucune personne déplacée relevée",
                             "ecoles_osm": "aucune école repérée sur OpenStreetMap"}.get(m.cle, f"0 {m.libelle}")
                lignes.append(f"{z.article}{' (' + z.note + ')' if z.genre in ('province_2025', 'region_2025') else ''} : {corps}{_commentaire(m, v)}"
                              + (f", en {annee}" if m.annuelle else "") + "." + (_rang(m, z, annee) if len(cibles) == 1 else ""))
    if len(vals) >= 2 and all(v is not None for _, v in vals):
        haut = max(vals, key=lambda t: t[1])
        bas = min(vals, key=lambda t: t[1])
        if haut[0] is not bas[0]:
            lignes.append(f"Écart : {_fmt(m, haut[1] - bas[1]) if m.format != 'part' else _pc(haut[1] - bas[1], 1)} entre {haut[0].article} et {bas[0].article}.")
    periode = f"{a0} et {a1}" if m.annuelle and evolution else (annee if m.annuelle else (ref or ""))
    texte = " ".join(lignes) + f" Source : {m.source}{', ' + periode if periode and m.source.startswith('annuaire') else ''}{note_annee}."
    return {"reponse": texte, "actions": _actions(cibles if zs else []), "suggestions": _suggestions(m, zs, annee)}


def _classement(q: str, m: Mesure, annee: str, nombre: int) -> dict | None:
    from dcb.assistant import _donnees
    croissant = _a(q, "MOINS", "PLUS FAIBLE", "PLUS BAS", "MIEUX")
    if m.plus_est_mieux and _a(q, "MANQU", "RETARD"):
        croissant = True
    if _a(q, "REGIONS?") and not _a(q, "COMMUNES"):
        regions: dict[str, list[str]] = {}
        for p in _donnees()["provinces"]:
            regions.setdefault(p["region"], []).append(p["province"])
        codes: dict[str, list[str]] = {}
        for c in _donnees()["communes"]:
            codes.setdefault(c["region_ancienne"], []).append(c["pcode_commune"])
        items = [(nom_officiel(r), m.calcul(Zone(nom_officiel(r), "region", ps, codes.get(r, [])), annee)) for r, ps in regions.items()]
        quoi = "régions"
    elif m.maille == "commune" or _a(q, "COMMUNES"):
        if m.maille != "commune":
            return None
        items = [(c["commune"], m.calcul(Zone(c["commune"], "commune", [c["province_ancienne"]], [c["pcode_commune"]]), annee))
                 for c in _donnees()["communes"]]
        quoi = "communes"
    else:
        items = [(nom_officiel(p["province"]), m.calcul(Zone(p["province"], "province", [p["province"]], []), annee)) for p in _donnees()["provinces"]]
        quoi = "provinces"
    items = [(n, v) for n, v in items if v is not None]
    items.sort(key=lambda t: t[1], reverse=not croissant)
    n = max(1, min(nombre, 20))
    liste = " ; ".join(f"{i + 1}. {nom} ({_fmt(m, v)})" for i, (nom, v) in enumerate(items[:n]))
    texte = (f"{m.libelle[0].upper() + m.libelle[1:]}{', ' + annee if m.annuelle else ''} : les {n} {quoi} aux valeurs les plus "
             f"{'faibles' if croissant else 'fortes'} : {liste}. Source : {m.source}.")
    return {"reponse": texte, "actions": [], "suggestions": [f"Et les {quoi} aux valeurs les plus {'fortes' if croissant else 'faibles'} ?"]}


def comparer_lieux(zs: list[Zone]) -> dict:
    """« Compare le Soum et le Loroum » sans mesure précise : les indicateurs clés de chaque lieu, côte à côte."""
    cles = ["ratio_maitre", "ratio_salle", "indice", "fermees", "part_prive", "filles_100"]
    ms = [m for m in mesures() if m.cle in cles]
    ref = annees()[-1] if annees() else None
    lignes = []
    for z in zs[:3]:
        if z.genre == "commune":
            ms_c = [m for m in mesures() if m.cle in ("population", "enfants_2030", "loin", "deplaces", "ecoles_osm")]
            parts = [f"{m.libelle.split(' (')[0]} {_fmt(m, m.calcul(z, ref))}" for m in ms_c]
        else:
            parts = [f"{m.libelle.split(' (')[0].replace(' dans les écoles publiques', '')} {_fmt(m, v)}" for m in ms
                     if (v := m.calcul(z, ref)) is not None]
        lignes.append(f"{z.article} : " + " ; ".join(parts) + ".")
    texte = f"En {ref} : " + " ".join(lignes) + " Sources : annuaires DGESS ; calculs de l'outil ; RGPH, CONASUR pour les communes."
    sugg = [f"Évolution des élèves par enseignant au {zs[0].nom} depuis 2017"] if zs and zs[0].genre == "province" else []
    return {"reponse": texte, "actions": _actions(zs), "suggestions": sugg}
