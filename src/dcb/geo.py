"""Référentiel géographique : 13 régions et 45 provinces du découpage en vigueur dans les annuaires.

Les annuaires écrivent les noms de provinces de plusieurs façons (« LES BALE », « KOURITTENGA »…).
Tout libellé passe par `province()` ou `region()`, qui renvoient le nom de référence ou None.
"""
from __future__ import annotations

import re
import unicodedata

REGIONS_PROVINCES: dict[str, list[str]] = {
    "BOUCLE DU MOUHOUN": ["BALE", "BANWA", "KOSSI", "MOUHOUN", "NAYALA", "SOUROU"],
    "CASCADES": ["COMOE", "LERABA"],
    "CENTRE": ["KADIOGO"],
    "CENTRE-EST": ["BOULGOU", "KOULPELOGO", "KOURITENGA"],
    "CENTRE-NORD": ["BAM", "NAMENTENGA", "SANMATENGA"],
    "CENTRE-OUEST": ["BOULKIEMDE", "SANGUIE", "SISSILI", "ZIRO"],
    "CENTRE-SUD": ["BAZEGA", "NAHOURI", "ZOUNDWEOGO"],
    "EST": ["GNAGNA", "GOURMA", "KOMANDJOARI", "KOMPIENGA", "TAPOA"],
    "HAUTS-BASSINS": ["HOUET", "KENEDOUGOU", "TUY"],
    "NORD": ["LOROUM", "PASSORE", "YATENGA", "ZONDOMA"],
    "PLATEAU CENTRAL": ["GANZOURGOU", "KOURWEOGO", "OUBRITENGA"],
    "SAHEL": ["OUDALAN", "SENO", "SOUM", "YAGHA"],
    "SUD-OUEST": ["BOUGOURIBA", "IOBA", "NOUMBIEL", "PONI"],
}
REGION_DE: dict[str, str] = {p: r for r, ps in REGIONS_PROVINCES.items() for p in ps}
PROVINCES: list[str] = sorted(REGION_DE)

# variantes d'écriture rencontrées -> nom de référence (clés déjà passées par `cle`)
_ALIAS_PROVINCES = {
    "LESBALE": "BALE",
    "BALES": "BALE",
    "KOURITTENGA": "KOURITENGA",
    "KOMONDJARI": "KOMANDJOARI",
    "KOMONDJOARI": "KOMANDJOARI",
    "KOMANDJARI": "KOMANDJOARI",
    "KOMPIENGA": "KOMPIENGA",
    "ZOUNDWEOGO": "ZOUNDWEOGO",
}
_ALIAS_REGIONS = {
    "HAUTBASSINS": "HAUTS-BASSINS",
    "PLATEAUCENTRAL": "PLATEAU CENTRAL",
}


def correspondance():
    """Découpage de 2025 (17 régions, 47 provinces) rattaché aux 45 provinces des annuaires.

    Source : limites administratives COD-AB du Data Pack (colonnes adm2_pcode_old / adm2_name_old)."""
    from dcb.lecture import CSV, lire_csv

    f = CSV / "04_Cartographie_SIG" / "COD-AB_limites_administratives" / "bfa_admin_boundaries__bfa_admin2.csv"
    t = lire_csv(f)
    t.columns = t.iloc[0]
    t = t.iloc[1:]
    c = t[["adm2_name_old", "adm2_pcode_old", "adm2_name", "adm2_pcode", "adm1_name", "adm1_pcode"]].copy()
    c.columns = ["province_ancienne_libelle", "pcode_province_ancienne", "province_2025", "pcode_province_2025",
                 "region_2025", "pcode_region_2025"]
    c.insert(0, "province", c["province_ancienne_libelle"].map(province))
    c.insert(1, "region", c["province"].map(REGION_DE))
    if c["province"].isna().any() or c["province"].nunique() != len(PROVINCES):
        raise ValueError("correspondance des provinces incomplète")
    return c.drop(columns="province_ancienne_libelle").sort_values(["region", "province", "province_2025"]).reset_index(drop=True)


def contours_provinces(tolerance: float = 0.01):
    """Contours simplifiés des 45 provinces des annuaires (fusion des provinces de 2025 issues d'une même ancienne)."""
    import geopandas as gpd

    from dcb.lecture import DATAPACK

    archive = DATAPACK / "04_Cartographie_SIG" / "COD-AB_limites_administratives" / "bfa_admin_boundaries.geojson.zip"
    g = gpd.read_file(f"zip://{archive.as_posix()}!bfa_admin2.geojson")
    corr = correspondance().set_index("pcode_province_2025")["province"]
    g["province"] = g["adm2_pcode"].map(corr)
    g = g.dissolve(by="province").reset_index()[["province", "geometry"]]
    g["geometry"] = g.geometry.simplify(tolerance, preserve_topology=True)
    g["region"] = g["province"].map(REGION_DE)
    return g


def cle(texte: str) -> str:
    """Majuscules, sans accents, lettres seulement : « Boucle du Mouhoun » -> BOUCLEDUMOUHOUN."""
    t = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z]", "", t.upper())


_CLE_PROVINCE = {cle(p): p for p in PROVINCES} | _ALIAS_PROVINCES
_CLE_REGION = {cle(r): r for r in REGIONS_PROVINCES} | _ALIAS_REGIONS


def province(texte: str) -> str | None:
    """Nom de référence de la province, ou None si le libellé n'en est pas une."""
    return _CLE_PROVINCE.get(cle(texte))


def region(texte: str) -> str | None:
    """Nom de référence de la région, ou None si le libellé n'en est pas une."""
    return _CLE_REGION.get(cle(texte))
