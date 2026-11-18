"""Lecture sûre des CSV du Data Pack.

Les CSV issus de PDF ont pour colonnes : document ; page ; ligne ; nb_cellules ; c1 … cN,
plus une colonne `remarque_collecte` absente du Guide, qui contient des textes parasites
sans rapport avec les données. Elle est supprimée à la lecture.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
DATAPACK = RACINE / "data" / "external" / "datapack" / "DataPack_DCB_2026"
CSV = DATAPACK / "data"

COLONNE_PARASITE = "remarque_collecte"
_ESPACES = re.compile(r"[\s   ]+")


def lire_csv(chemin: str | Path) -> pd.DataFrame:
    """Lit un CSV du Data Pack en texte, sans la colonne parasite."""
    df = pd.read_csv(chemin, sep=";", dtype=str, encoding="utf-8", keep_default_na=False)
    if COLONNE_PARASITE in df.columns:
        df = df.drop(columns=[COLONNE_PARASITE])
    for col in ("page", "ligne", "nb_cellules"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def nombre(texte: str) -> float | None:
    """Convertit « 306 926 » ou « 78,2 » en nombre ; None si ce n'est pas un nombre."""
    if texte is None:
        return None
    t = _ESPACES.sub("", str(texte)).replace(",", ".").rstrip("%")
    if t in ("", "-", "–", "nd", "ND", "//", "///"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def cellules(df: pd.DataFrame) -> list[str]:
    """Noms des colonnes de cellules c1 … cN, dans l'ordre."""
    return sorted((c for c in df.columns if re.fullmatch(r"c\d+", c)), key=lambda c: int(c[1:]))


def nombre_de_tests() -> int | None:
    """Nombre de cas de test collectés par pytest (paramétrés compris), pour les chiffres publiés."""
    import re
    import subprocess
    import sys
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", str(RACINE / "tests")], cwd=RACINE,
                           capture_output=True, text=True, timeout=120, env={**__import__("os").environ, "PYTHONPATH": str(RACINE / "src")})
        m = re.search(r"(\d+) tests? collected", r.stdout)
        return int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        return None
