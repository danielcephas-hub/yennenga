"""Entrepôt des données : chaque année, un technicien ajoute de nouvelles données sans toucher au code.

Principe
- Les types de données acceptés sont décrits dans `referentiel/types_donnees.yaml` (variables, bornes, contrôles).
- Un fichier (Excel ou CSV, au format du gabarit) est d'abord contrôlé. Une anomalie bloquante (code de territoire
  inconnu, valeur négative, doublon, colonne manquante…) refuse l'import et dit pourquoi ; une anomalie d'avertissement
  (ratio inhabituel, forte variation sur un an…) est consignée et n'empêche pas l'import.
- Chaque import est un « lot » daté, avec son empreinte, son auteur, son découpage territorial et son rapport de
  contrôle. Pour une année donnée, c'est le lot publié le plus récent qui fait foi ; retirer un lot rétablit le
  précédent. Rien n'est jamais effacé : tout calcul passé peut être rejoué.
- Les territoires sont identifiés par leur code (référentiel territorial) ; un nom est accepté s'il est reconnu,
  variantes d'écriture comprises. Les données sont relues dans le découpage voulu (`territoire.convertir`).

Stockage : un seul fichier SQLite (data/entrepot/entrepot.sqlite), sans serveur de base de données.

Usage :
  PYTHONPATH=src python -m dcb.entrepot amorcer                       charge les données extraites des annuaires
  PYTHONPATH=src python -m dcb.entrepot gabarit primaire_province 2025-2026   produit le fichier à remplir
  PYTHONPATH=src python -m dcb.entrepot controler FICHIER TYPE        contrôle sans importer
  PYTHONPATH=src python -m dcb.entrepot importer FICHIER TYPE AUTEUR   contrôle puis importe
  PYTHONPATH=src python -m dcb.entrepot lots                          liste les lots
  PYTHONPATH=src python -m dcb.entrepot retirer N AUTEUR              retire le lot N (le précédent refait foi)
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from dcb import geo, territoire
from dcb.lecture import RACINE

ENTREPOT = RACINE / "data" / "entrepot" / "entrepot.sqlite"
CATALOGUE = RACINE / "referentiel" / "types_donnees.yaml"
_ANNEE = re.compile(r"^(\d{4})-(\d{4})$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
    lot INTEGER PRIMARY KEY AUTOINCREMENT,
    type_donnee TEXT NOT NULL, fichier TEXT NOT NULL, empreinte TEXT NOT NULL, decoupage TEXT NOT NULL,
    annees TEXT NOT NULL, lignes INTEGER NOT NULL, auteur TEXT NOT NULL, source TEXT,
    depose_le TEXT NOT NULL, statut TEXT NOT NULL, rapport TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
    lot INTEGER NOT NULL REFERENCES lots(lot), annee_scolaire TEXT NOT NULL, code_territoire TEXT NOT NULL,
    cles TEXT NOT NULL, variable TEXT NOT NULL, valeur REAL
);
CREATE INDEX IF NOT EXISTS obs_lot ON observations(lot);
CREATE TABLE IF NOT EXISTS journal (
    horodatage TEXT NOT NULL, auteur TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL
);
"""


def catalogue() -> dict:
    return yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connexion(chemin: Path | None = None) -> sqlite3.Connection:
    chemin = chemin or ENTREPOT  # lu à l'appel : un test peut rediriger l'entrepôt
    chemin.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(chemin)
    con.executescript(SCHEMA)
    return con


def rentree(annee: str) -> str:
    """Date de rentrée d'une année scolaire « 2025-2026 » -> « 2025-10-01 » (sert à choisir le découpage)."""
    return f"{annee[:4]}-10-01"


# --- contrôle ------------------------------------------------------------------------------------------------

@dataclass
class Rapport:
    type_donnee: str
    decoupage: str = ""
    lignes: int = 0
    annees: list[str] = field(default_factory=list)
    bloquants: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    apercu: list[str] = field(default_factory=list)       # ce que l'import changera, année par année
    decoupage_libelle: str = ""

    @property
    def accepte(self) -> bool:
        return not self.bloquants

    def texte(self) -> str:
        t = [f"Type : {self.type_donnee} ; découpage : {self.decoupage or '?'} ; {self.lignes} lignes ; "
             f"années : {', '.join(self.annees) or '?'}",
             "Résultat : " + ("ACCEPTÉ" if self.accepte else "REFUSÉ")]
        t += [f"  [bloquant] {b}" for b in self.bloquants]
        t += [f"  [à vérifier] {a}" for a in self.avertissements]
        return "\n".join(t)


def lire_fichier(chemin: Path) -> pd.DataFrame:
    chemin = Path(chemin)
    if chemin.suffix.lower() in (".xlsx", ".xlsm"):
        onglets = pd.ExcelFile(chemin).sheet_names
        if "donnees" not in onglets:
            raise ValueError(f"l'onglet « donnees » est introuvable (onglets du fichier : {', '.join(onglets)}). "
                             "Utiliser le fichier type sans renommer ses onglets.")
        return pd.read_excel(chemin, sheet_name="donnees", dtype=object)
    try:
        return pd.read_csv(chemin, sep=None, engine="python", dtype=object, encoding="utf-8-sig")
    except (UnicodeDecodeError, pd.errors.ParserError) as e:
        raise ValueError("fichier CSV illisible : l'enregistrer en UTF-8, séparateur point-virgule") from e


def _nombre(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    if s in ("", "-", "nan", "None"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return "invalide"


def _exemples(df: pd.DataFrame, masque: pd.Series, colonne: str | None = None, n: int = 5) -> str:
    """« ligne 7 (Bam) : -3 ; ligne 12 (Séno) : abc … » pour les lignes du masque."""
    lignes = df.loc[masque]
    morceaux = []
    for _, x in lignes.head(n).iterrows():
        nom = x.get("_nom") if pd.notna(x.get("_nom")) else "?"
        if pd.notna(x.get("_cle")) and x.get("_cle"):
            nom = f"{nom}, {x['_cle']}"
        v = x[colonne] if colonne else None
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        morceaux.append(f"ligne {x['_ligne']} ({nom})" + (f" : {v}" if colonne else ""))
    reste = len(lignes) - n
    return " ; ".join(morceaux) + (f" ; et {reste} autres" if reste > 0 else "")


def controler(df: pd.DataFrame, type_donnee: str, ref: territoire.Referentiel | None = None,
              decoupage: str | None = None, precedent: pd.DataFrame | None = None) -> tuple[Rapport, pd.DataFrame]:
    """Contrôle un tableau au format du gabarit. Renvoie le rapport et la table normalisée (codes, nombres).

    Chaque anomalie cite la ligne du fichier (en-tête = ligne 1), le territoire et la valeur en cause."""
    cat = catalogue()
    r = Rapport(type_donnee)
    if type_donnee not in cat:
        r.bloquants.append(f"Type de données inconnu : {type_donnee} (types connus : {', '.join(cat)}).")
        return r, pd.DataFrame()
    spec = cat[type_donnee]
    ref = ref or territoire.charger()
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["_ligne"] = range(2, len(df) + 2)
    df = df.dropna(how="all", subset=[c for c in df.columns if c != "_ligne"])
    variables = spec["variables"]
    cles = spec.get("cles") or {}
    niveau = spec["niveau"]

    # colonnes
    obligatoires = ["annee_scolaire", *cles, *[v for v, s in variables.items() if not s.get("facultatif")]]
    manquantes = [c for c in obligatoires if c not in df.columns]
    if "code_territoire" not in df.columns and "territoire" not in df.columns:
        manquantes.append("code_territoire (ou territoire)")
    if manquantes:
        r.bloquants.append(f"Colonnes manquantes : {', '.join(manquantes)}. Utiliser le fichier type sans renommer ses colonnes.")
        return r, pd.DataFrame()
    inconnues = set(df.columns) - {"annee_scolaire", "code_territoire", "territoire", "_ligne", *cles, *variables}
    if inconnues:
        r.avertissements.append(f"Colonnes ignorées : {', '.join(sorted(inconnues))}.")
    # une ligne sans aucune valeur chiffrée n'est pas une donnée : elle est écartée (cas du fichier type non rempli)
    remplies = df[[v for v in variables if v in df.columns]].map(lambda x: not (_nombre(x) is np.nan or
                                                                                 (isinstance(_nombre(x), float) and np.isnan(_nombre(x)))))
    vides = ~remplies.any(axis=1)
    if vides.all():
        r.bloquants.append("Aucune valeur renseignée : le fichier ne contient que les noms des territoires.")
        return r, pd.DataFrame()
    if vides.any():
        r.avertissements.append(f"{int(vides.sum())} lignes sans aucune valeur ont été ignorées (territoires non renseignés).")
        df = df.loc[~vides]
    r.lignes = len(df)

    # années
    df["annee_scolaire"] = df["annee_scolaire"].astype(str).str.strip().str.replace("/", "-")
    mal = ~df["annee_scolaire"].str.match(_ANNEE)
    if mal.any():
        df["_nom"] = df.get("territoire", df.get("code_territoire"))
        r.bloquants.append(f"Année scolaire au format AAAA-AAAA attendue (exemple : 2025-2026) : {_exemples(df, mal, 'annee_scolaire')}.")
        return r, pd.DataFrame()
    ok = df["annee_scolaire"].map(lambda a: int(a[5:]) == int(a[:4]) + 1)
    if not ok.all():
        r.bloquants.append(f"Années incohérentes (la seconde doit suivre la première) : {', '.join(df.loc[~ok, 'annee_scolaire'].unique()[:5])}.")
    r.annees = sorted(df["annee_scolaire"].unique())

    # découpage : celui en vigueur à la rentrée, sauf indication contraire ; un fichier = un seul découpage
    decs = {ref.en_vigueur(rentree(a)) for a in r.annees}
    if decoupage is None:
        if len(decs) > 1:
            r.bloquants.append(f"Le fichier couvre des années de découpages territoriaux différents ({', '.join(sorted(decs))}) : "
                               "faire un fichier par découpage.")
            return r, pd.DataFrame()
        decoupage = decs.pop()
    if decoupage not in set(ref.decoupages["decoupage"]):
        r.bloquants.append(f"Découpage territorial inconnu : {decoupage}.")
        return r, pd.DataFrame()
    r.decoupage = decoupage
    r.decoupage_libelle = str(ref.decoupages.set_index("decoupage").loc[decoupage, "libelle"])

    # territoires : code reconnu, ou nom reconnu (variantes comprises) ; un désaccord code / nom est signalé
    if niveau == "commune":
        lieux_noms = ref.communes.set_index("pcode_commune")["commune"]
        connus = set(ref.decoupage(decoupage)["pcode_commune"])
        noms = {geo.cle(n): c for c, n in zip(ref.communes["pcode_commune"], ref.communes["commune"])}
    else:
        lieux = ref.provinces(decoupage)
        lieux_noms = lieux.drop_duplicates(f"code_{niveau}").set_index(f"code_{niveau}")[niveau]
        connus = set(lieux[f"code_{niveau}"])
        noms = None
    code_saisi = df["code_territoire"].astype(str).str.strip() if "code_territoire" in df.columns else pd.Series("", index=df.index)
    code = code_saisi.where(code_saisi.isin(connus))
    if "territoire" in df.columns:
        par_nom = df["territoire"].map(lambda t: (noms.get(geo.cle(t)) if noms is not None else ref.code(decoupage, niveau, t))
                                       if pd.notna(t) else None)
        df["_nom"] = df["territoire"]
        corrige = code.isna() & par_nom.notna() & code_saisi.ne("") & code_saisi.ne("nan")
        if corrige.any():
            r.avertissements.append(f"Code de territoire inconnu, territoire reconnu par son nom : {_exemples(df, corrige, 'code_territoire')}.")
        desaccord = code.notna() & par_nom.notna() & code.ne(par_nom)
        if desaccord.any():
            r.bloquants.append(f"Le code et le nom désignent deux territoires différents : {_exemples(df, desaccord, 'code_territoire')}. "
                               "Corriger l'un ou l'autre.")
        code = code.fillna(par_nom)
    else:
        df["_nom"] = code.map(lieux_noms)
    if code.isna().any():
        df["_nom"] = df["_nom"].fillna(code_saisi)
        r.bloquants.append(f"{int(code.isna().sum())} lignes avec un territoire inconnu dans le découpage « {r.decoupage_libelle or decoupage} » : "
                           f"{_exemples(df, code.isna())}.")
    df["code_territoire"] = code
    df["_nom"] = code.map(lieux_noms).fillna(df["_nom"])

    # clés
    for k, valeurs in cles.items():
        df[k] = df[k].astype(str).str.strip().str.lower()
    df["_cle"] = df[list(cles)].astype(str).agg(", ".join, axis=1).str.replace("prive", "privé") if cles else ""
    for k, valeurs in cles.items():
        hors = ~df[k].isin(valeurs)
        if hors.any():
            r.bloquants.append(f"Valeurs inattendues pour {k} (attendu : {', '.join(valeurs)}) : {_exemples(df, hors, k)}.")

    # doublons
    id_cols = ["annee_scolaire", "code_territoire", *cles]
    dup = df.duplicated(id_cols, keep=False) & df["code_territoire"].notna()
    if dup.any():
        r.bloquants.append(f"Lignes en double (même année, même territoire{', même ' + ', '.join(cles) if cles else ''}) : "
                           f"{_exemples(df, dup)}. Garder une seule ligne.")

    # valeurs
    for v, s in variables.items():
        if v not in df.columns:
            continue
        lib = s.get("libelle", v)
        brut = df[v].copy()
        df[v] = df[v].map(_nombre)
        inval = df[v].map(lambda x: isinstance(x, str))
        if inval.any():
            df["_brut"] = brut
            r.bloquants.append(f"{lib} : valeurs non numériques : {_exemples(df, inval, '_brut')}.")
            df.loc[inval, v] = np.nan
        df[v] = pd.to_numeric(df[v])
        if "min" in s and (df[v] < s["min"]).any():
            r.bloquants.append(f"{lib} : valeurs inférieures à {s['min']} : {_exemples(df, df[v] < s['min'], v)}.")
        if "max" in s and (df[v] > s["max"]).any():
            r.bloquants.append(f"{lib} : valeurs supérieures à {s['max']} : {_exemples(df, df[v] > s['max'], v)}.")
        if not s.get("facultatif") and df[v].isna().all():
            r.bloquants.append(f"{lib} : aucune valeur renseignée.")
        elif not s.get("facultatif") and (df[v].isna() & ~inval).any():
            r.avertissements.append(f"{lib} : valeur vide (inconnue) : {_exemples(df, df[v].isna() & ~inval)}.")

    if r.bloquants:
        return r, pd.DataFrame()

    # complétude : un fichier remplace toute l'année ; il doit couvrir presque tous les territoires
    seuil = spec.get("completude_min")
    if seuil:
        for annee, g in df.groupby("annee_scolaire"):
            presents = set(g["code_territoire"].dropna())
            absents = sorted(connus - presents)
            part = len(presents & connus) / len(connus)
            noms_absents = [str(lieux_noms.get(c, c)) for c in absents]
            if part < seuil:
                r.bloquants.append(f"{annee} : {len(presents & connus)} territoires renseignés sur {len(connus)} "
                                   f"(au moins {100 * seuil:.0f} % attendus). Un fichier remplace toute l'année : "
                                   f"le compléter avant de l'importer. Manquants : {', '.join(noms_absents[:8])}"
                                   f"{'…' if len(absents) > 8 else ''}.")
            elif absents:
                r.avertissements.append(f"{annee} : {len(absents)} territoires non renseignés ({', '.join(noms_absents[:6])}"
                                        f"{'…' if len(absents) > 6 else ''}) : ils seront comptés comme inconnus cette année-là.")
    if r.bloquants:
        return r, pd.DataFrame()

    # avertissements : ratios, cohérence des totaux, variation sur un an
    for q in spec.get("ratios", []) or []:
        a, b = df[q["numerateur"]], df[q["denominateur"]]
        x = (a / b).where(b > 0)
        hors = (x < q["min"]) | (x > q["max"])
        if hors.any():
            df["_ratio"] = x.round(1)
            r.avertissements.append(f"{q['libelle'][:1].upper() + q['libelle'][1:]} inhabituel (hors de {q['min']} à {q['max']}) : {_exemples(df, hors, '_ratio')}.")
    for c in spec.get("coherence", []) or []:
        k = c["sur"]
        w = df.pivot_table(index=["annee_scolaire", "code_territoire"], columns=k,
                           values=[v for v, s in variables.items() if s.get("somme") and v in df.columns], aggfunc="sum")
        for v in w.columns.get_level_values(0).unique():
            if not {c["total"], *c["parties"]} <= set(w[v].columns):
                continue
            ecart = (w[v][c["total"]] - w[v][c["parties"]].sum(axis=1)).abs() / w[v][c["total"]].replace(0, np.nan)
            mauvais = ecart[ecart > 0.005]
            if len(mauvais):
                ex = ", ".join(str(lieux_noms.get(t, t)) for _, t in mauvais.index[:5])
                r.avertissements.append((f"{variables[v].get('libelle', v)} : {c['total']} ≠ {' + '.join(c['parties'])} "
                                         f"pour {len(mauvais)} territoires ({ex}).").replace("prive", "privé"))
    if precedent is not None and not precedent.empty and spec.get("variation_max"):
        p = precedent.copy()
        p["annee_suivante"] = p["annee_scolaire"].map(lambda a: f"{int(a[:4]) + 1}-{int(a[:4]) + 2}")
        m = df.merge(p, left_on=["annee_scolaire", "code_territoire", *cles],
                     right_on=["annee_suivante", "code_territoire", *cles], suffixes=("", "_prec"))
        for v, s in variables.items():
            if v in df.columns and f"{v}_prec" in m.columns:
                ecart = (m[v] - m[f"{v}_prec"]).abs() / m[f"{v}_prec"].replace(0, np.nan)
                hors = ecart > spec["variation_max"]
                if hors.any():
                    m["_evol"] = m.apply(lambda z: f"{z[f'{v}_prec']:,.0f} → {z[v]:,.0f}".replace(",", " "), axis=1)
                    r.avertissements.append(f"{s.get('libelle', v)} : variation de plus de {100 * spec['variation_max']:.0f} % sur un an "
                                            f"(à vérifier) : {_exemples(m, hors, '_evol')}.")
    # aperçu : ce que l'import changera
    deja = set(precedent["annee_scolaire"]) if precedent is not None and not precedent.empty else set()
    for annee, g in df.groupby("annee_scolaire"):
        if annee in deja:
            r.apercu.append(f"{annee} : remplacera la version en vigueur ({g['code_territoire'].nunique()} territoires).")
        else:
            r.apercu.append(f"{annee} : nouvelle année ({g['code_territoire'].nunique()} territoires).")
    return r, df[[*id_cols, *[v for v in variables if v in df.columns]]]


def controler_fichier(df: pd.DataFrame, type_donnee: str, con: sqlite3.Connection | None = None) -> Rapport:
    """Contrôle sans rien enregistrer, avec la comparaison à l'année précédente (comme à l'import)."""
    ref = territoire.charger()
    try:
        precedent = lire(type_donnee, con=con or connexion(), ref=ref)
    except (KeyError, ValueError):
        precedent = None
    r, _ = controler(df, type_donnee, ref, None, precedent)
    return r


# --- écriture et lecture ---------------------------------------------------------------------------------------

def _journal(con: sqlite3.Connection, auteur: str, action: str, detail: str) -> None:
    con.execute("INSERT INTO journal VALUES (?, ?, ?, ?)", (_maintenant(), auteur, action, detail))


def importer(chemin: Path, type_donnee: str, auteur: str, source: str = "", decoupage: str | None = None,
             con: sqlite3.Connection | None = None, ref: territoire.Referentiel | None = None) -> tuple[Rapport, int | None]:
    """Contrôle puis importe un fichier. Renvoie (rapport, numéro du lot ou None si refusé)."""
    chemin = Path(chemin)
    empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
    return importer_table(lire_fichier(chemin), type_donnee, auteur, chemin.name, empreinte, source, decoupage, con, ref)


def importer_table(df: pd.DataFrame, type_donnee: str, auteur: str, fichier: str, empreinte: str, source: str = "",
                   decoupage: str | None = None, con: sqlite3.Connection | None = None,
                   ref: territoire.Referentiel | None = None) -> tuple[Rapport, int | None]:
    con = con or connexion()
    ref = ref or territoire.charger()
    deja = con.execute("SELECT lot FROM lots WHERE empreinte = ? AND type_donnee = ? AND statut = 'publie'",
                       (empreinte, type_donnee)).fetchone()
    if deja:
        r = Rapport(type_donnee)
        r.avertissements.append(f"fichier identique déjà importé (lot {deja[0]}) : rien à faire")
        return r, deja[0]
    spec = catalogue().get(type_donnee, {})
    try:
        precedent = lire(type_donnee, con=con, ref=ref, decoupage=decoupage)
    except (KeyError, ValueError):
        precedent = None
    r, t = controler(df, type_donnee, ref, decoupage, precedent)
    if not r.accepte:
        _journal(con, auteur, "import refusé", f"{type_donnee} {fichier} : {' ; '.join(r.bloquants)}")
        con.commit()
        return r, None
    cles = list((spec.get("cles") or {}).keys())
    cur = con.execute("INSERT INTO lots (type_donnee, fichier, empreinte, decoupage, annees, lignes, auteur, source, "
                      "depose_le, statut, rapport) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'publie', ?)",
                      (type_donnee, fichier, empreinte, r.decoupage, ",".join(r.annees), len(t), auteur, source,
                       _maintenant(), json.dumps({"bloquants": r.bloquants, "avertissements": r.avertissements},
                                                 ensure_ascii=False)))
    lot = cur.lastrowid
    long = t.melt(id_vars=["annee_scolaire", "code_territoire", *cles], var_name="variable", value_name="valeur")
    long["cles"] = long[cles].astype(str).agg("|".join, axis=1) if cles else ""
    con.executemany("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?)",
                    [(lot, a, c, k, v, None if pd.isna(x) else float(x)) for a, c, k, v, x in
                     long[["annee_scolaire", "code_territoire", "cles", "variable", "valeur"]].itertuples(index=False)])
    _journal(con, auteur, "import", f"lot {lot} : {type_donnee}, {fichier}, {len(t)} lignes, années {', '.join(r.annees)}")
    con.commit()
    return r, lot


def retirer(lot: int, auteur: str, con: sqlite3.Connection | None = None) -> None:
    """Retire un lot : il reste conservé, mais c'est de nouveau le lot précédent qui fait foi."""
    con = con or connexion()
    n = con.execute("UPDATE lots SET statut = 'retire' WHERE lot = ? AND statut = 'publie'", (lot,)).rowcount
    if not n:
        raise KeyError(f"aucun lot publié n° {lot}")
    _journal(con, auteur, "retrait", f"lot {lot}")
    con.commit()


def lots(con: sqlite3.Connection | None = None) -> pd.DataFrame:
    con = con or connexion()
    return pd.read_sql("SELECT lot, type_donnee, fichier, decoupage, annees, lignes, auteur, depose_le, statut "
                       "FROM lots ORDER BY lot", con)


def lire(type_donnee: str, decoupage: str | None = None, con: sqlite3.Connection | None = None,
         ref: territoire.Referentiel | None = None, poids: pd.Series | None = None) -> pd.DataFrame:
    """Données en vigueur d'un type, une ligne par année × territoire × clés, dans le découpage demandé.

    Pour chaque année, le lot publié le plus récent fait foi. Si `decoupage` est donné, les années déposées dans
    un autre découpage sont converties (colonne `estime` vraie pour les valeurs réparties au prorata)."""
    con = con or connexion()
    ref = ref or territoire.charger()
    spec = catalogue()[type_donnee]
    cles = list((spec.get("cles") or {}).keys())
    l = pd.read_sql("SELECT lot, decoupage, annees FROM lots WHERE type_donnee = ? AND statut = 'publie' ORDER BY lot",
                    con, params=(type_donnee,))
    if l.empty:
        raise KeyError(f"aucune donnée publiée pour {type_donnee}")
    fait_foi = {}
    for lot, dec, annees in l.itertuples(index=False):
        for a in annees.split(","):
            fait_foi[a] = (lot, dec)  # le plus récent écrase
    morceaux = []
    for (lot, dec), annees in pd.Series(list(fait_foi.keys()), index=pd.MultiIndex.from_tuples(list(fait_foi.values()))).groupby(level=[0, 1]):
        o = pd.read_sql("SELECT annee_scolaire, code_territoire, cles, variable, valeur FROM observations WHERE lot = ?",
                        con, params=(int(lot),))
        o = o[o["annee_scolaire"].isin(set(annees))]
        w = o.pivot_table(index=["annee_scolaire", "code_territoire", "cles"], columns="variable", values="valeur",
                          aggfunc="first").reset_index()
        w.columns.name = None
        if cles:
            w[cles] = w["cles"].str.split("|", expand=True)
        w = w.drop(columns="cles").assign(lot=int(lot), decoupage=dec)
        morceaux.append(w)
    t = pd.concat(morceaux, ignore_index=True)
    t["estime"] = False
    if decoupage is not None and spec["niveau"] != "commune" and poids is None and (t["decoupage"] != decoupage).any():
        # une province scindée est répartie au prorata de la population de ses communes (recensement), si connue
        try:
            pop = lire("population_commune", con=con, ref=ref)
            poids = pop.sort_values("annee_scolaire").groupby("code_territoire")["population"].last()
        except KeyError:
            poids = None
    if decoupage is not None and spec["niveau"] != "commune":
        variables = [v for v, s in spec["variables"].items() if s.get("somme") and v in t.columns]
        out = []
        for dec, g in t.groupby("decoupage"):
            if dec == decoupage:
                out.append(g)
                continue
            niveau = spec["niveau"]
            c = ref.convertir(g.rename(columns={"code_territoire": f"code_{niveau}"}), dec, decoupage, variables,
                              niveau=niveau, cle=f"code_{niveau}", autres_cles=["annee_scolaire", *cles, "lot"], poids=poids)
            out.append(c.drop(columns=niveau).rename(columns={f"code_{niveau}": "code_territoire"}).assign(decoupage=decoupage))
        t = pd.concat(out, ignore_index=True)
    return t.sort_values(["annee_scolaire", "code_territoire", *cles]).reset_index(drop=True)


# --- gabarit ---------------------------------------------------------------------------------------------------

def gabarit(type_donnee: str, annee: str, chemin: Path, ref: territoire.Referentiel | None = None,
            decoupage: str | None = None, deja: pd.DataFrame | None = None) -> Path:
    """Fichier Excel à remplir : une ligne par territoire (et par clé), avec un onglet d'explications.

    Les colonnes de repère (année, code, nom, clés) sont verrouillées ; les cases à remplir n'acceptent que des
    nombres positifs ; chaque en-tête porte son libellé en commentaire. `deja` pré-remplit le fichier
    (téléchargement des données d'une année déjà en place, pour la corriger)."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Font, PatternFill, Protection
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    ref = ref or territoire.charger()
    spec = catalogue()[type_donnee]
    decoupage = decoupage or ref.en_vigueur(rentree(annee))
    niveau = spec["niveau"]
    if niveau == "commune":
        lieux = ref.decoupage(decoupage).merge(ref.communes, on="pcode_commune")[["pcode_commune", "commune", "province"]]
        lieux.columns = ["code_territoire", "territoire", "rattachement"]
    else:
        p = ref.provinces(decoupage)
        lieux = p[[f"code_{niveau}", niveau, "region"]].drop_duplicates() if niveau == "province" else \
            p[["code_region", "region"]].drop_duplicates().assign(rattachement="")
        lieux.columns = ["code_territoire", "territoire", "rattachement"]
    cles = spec.get("cles") or {}
    lignes = lieux.assign(_k=1)
    for k, valeurs in cles.items():
        lignes = lignes.merge(pd.DataFrame({k: valeurs, "_k": 1}), on="_k")
    lignes = lignes.drop(columns="_k").sort_values(["rattachement", "territoire", *cles])
    wb = Workbook()
    ws = wb.active
    ws.title = "donnees"
    entete = ["annee_scolaire", "code_territoire", "territoire", *cles, *spec["variables"]]
    ws.append(entete)
    pre = None
    if deja is not None and not deja.empty:
        pre = deja[deja["annee_scolaire"] == annee].set_index(["code_territoire", *cles])
    for _, x in lignes.iterrows():
        cle = (x["code_territoire"], *[x[k] for k in cles]) if cles else x["code_territoire"]
        vals = []
        for v in spec["variables"]:
            try:
                val = pre.loc[cle, v] if pre is not None and v in pre.columns else None
                vals.append(None if val is None or pd.isna(val) else float(val))
            except KeyError:
                vals.append(None)
        ws.append([annee, x["code_territoire"], x["territoire"], *[x[k] for k in cles], *vals])
    gras, fond, fond_repere = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E79"), PatternFill("solid", fgColor="EEF1F4")
    nrep = 3 + len(cles)
    for i, nom in enumerate(entete, 1):
        ws.cell(1, i).font, ws.cell(1, i).fill = gras, fond
        ws.column_dimensions[get_column_letter(i)].width = 18 if i > nrep else 16
        s = spec["variables"].get(nom)
        aide = (f"{s['libelle']}{' (facultatif)' if s.get('facultatif') else ''}. Nombre positif ; case vide = inconnu."
                if s else {"annee_scolaire": "Année scolaire, ne pas modifier.", "code_territoire": "Code officiel, ne pas modifier.",
                           "territoire": "Nom, pour repère."}.get(nom, "Ne pas modifier."))
        ws.cell(1, i).comment = Comment(aide, "Yennenga")
    # repères verrouillés, cases à remplir libres ; seuls des nombres positifs sont acceptés
    n = ws.max_row
    for r in range(2, n + 1):
        for c in range(1, len(entete) + 1):
            cell = ws.cell(r, c)
            if c <= nrep:
                cell.fill = fond_repere
            else:
                cell.protection = Protection(locked=False)
    if len(entete) > nrep:
        dv = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=True,
                            showErrorMessage=True, errorTitle="Valeur refusée",
                            error="Un nombre positif est attendu (laisser vide si la valeur est inconnue).")
        dv.add(f"{get_column_letter(nrep + 1)}2:{get_column_letter(len(entete))}{n}")
        ws.add_data_validation(dv)
    ws.protection.sheet = True
    ws.protection.formatColumns = False
    ws.protection.autoFilter = False
    ws.protection.sort = False
    ws.auto_filter.ref = f"A1:{get_column_letter(len(entete))}{n}"
    ws.freeze_panes = ws.cell(2, nrep + 1)
    lm = wb.create_sheet("lisez_moi")
    lm.append([spec["libelle"]])
    lm["A1"].font = Font(bold=True, size=13)
    for l in [
        "",
        f"Année scolaire : {annee}. Découpage territorial : {decoupage} "
        f"({ref.decoupages.set_index('decoupage').loc[decoupage, 'libelle']}).",
        f"Source habituelle : {spec.get('source_habituelle', '')}.",
        "IMPORTANT : ce fichier remplace toute l'année. Il doit couvrir au moins 90 % des territoires.",
        "Remplir les cases blanches de l'onglet « donnees » (une ligne par territoire). Les colonnes grisées",
        "(année, code, nom) sont verrouillées : ne pas les modifier, ne pas renommer les onglets ni les colonnes.",
        "Seuls des nombres positifs sont acceptés. Un commentaire sur chaque en-tête rappelle ce qu'il faut saisir.",
        "Le code du territoire fait foi ; le nom est donné pour repère (un nom seul est accepté s'il est reconnu).",
        "Une case vide = valeur inconnue (ne pas écrire 0 si la valeur n'est pas connue).",
        "Le fichier est contrôlé à l'import : les anomalies bloquantes sont expliquées, rien n'est enregistré tant",
        "qu'elles ne sont pas corrigées. Les avertissements (valeur inhabituelle) sont consignés.",
        "",
        "Colonnes :",
        *[f"  {v} : {s['libelle']}{' (facultatif)' if s.get('facultatif') else ''}" for v, s in spec["variables"].items()],
        *[f"  {k} : une ligne pour chacune des valeurs {', '.join(v)}" for k, v in cles.items()],
    ]:
        lm.append([l])
    lm.column_dimensions["A"].width = 110
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    wb.save(chemin)
    return chemin


# --- amorçage depuis la chaîne d'extraction des annuaires ------------------------------------------------------

def amorcer(con: sqlite3.Connection | None = None, remplacer: bool = False) -> list[str]:
    """Charge dans l'entrepôt les tables extraites des annuaires et du recensement (lots « système »).

    Idempotent. Un type déjà amorcé n'est plus touché : un lot retiré par un administrateur n'est pas réimporté et
    une correction déposée par un technicien n'est pas écrasée. `remplacer=True` (option --remplacer) force un
    nouvel amorçage, par exemple après une nouvelle extraction des annuaires."""
    global _REMPLACER
    _REMPLACER = remplacer
    from dcb import population_communes
    from dcb.indicateurs import INTERIM, MURS, COMPTES

    con = con or connexion()
    ref = territoire.charger()
    code = ref.provinces("annuaires_2017_2025").set_index("province")["code_province"]
    messages = []

    syn = pd.read_csv(INTERIM / "synthese.csv", sep=";", encoding="utf-8")
    syn = syn[syn["niveau"] == "province"][["annee_scolaire", "province", "statut", *COMPTES]]
    murs = pd.read_csv(INTERIM / "murs.csv", sep=";", encoding="utf-8")
    murs = murs[murs["niveau"] == "province"][["annee_scolaire", "province", "statut", *MURS, "salles"]]
    murs = murs.rename(columns={"salles": "salles_tableau_murs"})
    t = syn.merge(murs, how="left", on=["annee_scolaire", "province", "statut"])
    t.insert(1, "code_territoire", t["province"].map(code))
    messages.append(_amorcer_table(con, ref, t.drop(columns="province"), "primaire_province",
                                   "annuaires_extraits.csv", "Annuaires statistiques DGESS 2017-2018 à 2024-2025 (extraction des PDF)"))

    h = pd.read_csv(INTERIM / "historique_effectifs.csv", sep=";", encoding="utf-8")
    h = h[(h["niveau"] == "province") & (h["sexe"] == "total")].dropna(subset=["eleves"])
    h = h.sort_values("annuaire").groupby(["annee_scolaire", "province"], as_index=False).last()
    s = pd.DataFrame({"annee_scolaire": h["annee_scolaire"], "code_territoire": h["province"].map(code), "eleves": h["eleves"]})
    messages.append(_amorcer_table(con, ref, s, "serie_effectifs_province", "series_longues_extraites.csv",
                                   "Annuaires statistiques DGESS, tableaux rétrospectifs (extraction des PDF)"))

    if population_communes.SORTIE.exists():
        p = pd.read_csv(population_communes.SORTIE, sep=";", encoding="utf-8")
        p = pd.DataFrame({"annee_scolaire": "2019-2020", "code_territoire": p["pcode_commune"], "population": p["population"],
                          "age_6_11": p["age_6_11"], "age_12_14": p["age_12_14"]})
        messages.append(_amorcer_table(con, ref, p, "population_commune", "rgph2019_localites.csv",
                                       "INSD, Fichier des localités du 5e RGPH (2019)", decoupage="reforme_2025"))
    from dcb import carte_scolaire
    d = carte_scolaire.deplaces_conasur(ref)
    messages.append(_amorcer_table(con, ref, d, "deplaces_commune", "conasur_pdi_31-12-2022.csv",
                                   "CONASUR, situation des PDI par commune d'accueil au 31 décembre 2022", decoupage="reforme_2025"))
    return messages


_REMPLACER = False


def _amorcer_table(con, ref, t, type_donnee, fichier, source, decoupage=None) -> str:
    deja = con.execute("SELECT lot, statut FROM lots WHERE type_donnee = ? AND auteur LIKE 'systeme%' ORDER BY lot DESC",
                       (type_donnee,)).fetchone()
    if deja and not _REMPLACER:
        return f"{type_donnee} : déjà amorcé (lot {deja[0]}, {'en vigueur' if deja[1] == 'publie' else 'retiré'}), non modifié"
    empreinte = hashlib.sha256(pd.util.hash_pandas_object(t, index=False).values.tobytes()).hexdigest()
    if decoupage is None:
        decoupage = "annuaires_2017_2025"
    r, lot = importer_table(t, type_donnee, "systeme (amorçage)", fichier, empreinte, source, decoupage, con, ref)
    if lot is None:
        raise ValueError(f"amorçage refusé pour {type_donnee} :\n{r.texte()}")
    if r.lignes == 0:
        return f"{type_donnee} : déjà à jour (lot {lot})"
    return f"{type_donnee} : lot {lot} ({r.lignes} lignes, {len(r.avertissements)} avertissements)"


if __name__ == "__main__":
    args = sys.argv[1:]
    action = args[0] if args else "lots"
    if action == "amorcer":
        for m in amorcer(remplacer="--remplacer" in args):
            print(m)
    elif action == "gabarit":
        typ, annee = args[1], args[2]
        print(gabarit(typ, annee, RACINE / "outputs" / "gabarits" / f"gabarit_{typ}_{annee}.xlsx"))
    elif action == "controler":
        r, _ = controler(lire_fichier(Path(args[1])), args[2], precedent=None)
        print(r.texte())
    elif action == "importer":
        r, lot = importer(Path(args[1]), args[2], args[3])
        print(r.texte())
        print(f"lot {lot}" if lot else "rien n'a été enregistré")
    elif action == "retirer":
        retirer(int(args[1]), args[2])
        print(f"lot {args[1]} retiré")
    print(lots().to_string(index=False))
