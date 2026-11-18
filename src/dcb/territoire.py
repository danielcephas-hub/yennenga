"""Référentiel territorial versionné : la commune est l'unité stable, provinces et régions sont des regroupements datés.

Le découpage administratif change (13 régions et 45 provinces jusqu'en 2025, 17 régions et 47 provinces ensuite ;
noms modifiés, provinces créées). L'outil ne code donc aucun découpage en dur : ils sont décrits par des tables du
dossier `referentiel/`, modifiables sans toucher au code.

- `communes.csv`        : une ligne par commune (code P actuel = identifiant stable, nom, ancien code, centre, superficie)
- `decoupages.csv`      : un découpage par ligne (identifiant, libellé, date d'entrée en vigueur, source)
- `rattachements.csv`   : pour chaque découpage, la province et la région de chaque commune
- `variantes_noms.csv`  : écritures rencontrées dans les fichiers -> code (les noms ne servent jamais de clé)

Créer une province, en scinder une, la renommer = ajouter un découpage (copie du précédent, lignes modifiées).
`convertir` fait passer une table d'un découpage à l'autre : exacte quand une province est une réunion de provinces
entières, estimée (au prorata d'un poids par commune, la population par défaut) quand une province est scindée.

Usage : PYTHONPATH=src python -m dcb.territoire            contrôle le référentiel et affiche son contenu
        PYTHONPATH=src python -m dcb.territoire --initialiser   le construit depuis les limites COD-AB du Data Pack
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from dcb import geo
from dcb.lecture import RACINE

REFERENTIEL = RACINE / "referentiel"
FICHIERS = ("communes", "decoupages", "rattachements", "variantes_noms")
COLONNES = {
    "communes": ["pcode_commune", "commune", "pcode_commune_ancien", "commune_ancien", "lat", "lon", "superficie_km2"],
    "decoupages": ["decoupage", "libelle", "valide_du", "source"],
    "rattachements": ["decoupage", "pcode_commune", "code_province", "province", "code_region", "region"],
    "variantes_noms": ["decoupage", "niveau", "variante", "code"],
}


@dataclass
class Referentiel:
    communes: pd.DataFrame
    decoupages: pd.DataFrame
    rattachements: pd.DataFrame
    variantes_noms: pd.DataFrame

    # --- lecture ---------------------------------------------------------------------------------------------
    def decoupage(self, ident: str) -> pd.DataFrame:
        """Communes et leurs rattachements dans un découpage."""
        r = self.rattachements[self.rattachements["decoupage"] == ident]
        if r.empty:
            raise KeyError(f"découpage inconnu : {ident}")
        return r.drop(columns="decoupage").reset_index(drop=True)

    def en_vigueur(self, date: str) -> str:
        """Identifiant du découpage en vigueur à une date (AAAA-MM-JJ)."""
        d = self.decoupages[self.decoupages["valide_du"] <= date].sort_values("valide_du")
        if d.empty:
            raise KeyError(f"aucun découpage en vigueur le {date}")
        return d.iloc[-1]["decoupage"]

    def provinces(self, ident: str) -> pd.DataFrame:
        return (self.decoupage(ident).groupby(["code_province", "province", "code_region", "region"], as_index=False)
                .agg(communes=("pcode_commune", "count")))

    def code(self, ident: str, niveau: str, texte: str) -> str | None:
        """Code d'une province ou d'une région à partir d'un libellé quelconque (accents, casse, variantes)."""
        c = geo.cle(texte)
        lieux = self.provinces(ident)
        noms = {geo.cle(n): k for n, k in zip(lieux[niveau], lieux[f"code_{niveau}"])}
        if c in noms:
            return noms[c]
        v = self.variantes_noms
        v = v[(v["decoupage"] == ident) & (v["niveau"] == niveau)]
        return dict(zip(v["variante"].map(geo.cle), v["code"])).get(c)

    # --- passage d'un découpage à l'autre --------------------------------------------------------------------
    def matrice_passage(self, de: str, vers: str, niveau: str = "province",
                        poids: pd.Series | None = None) -> pd.DataFrame:
        """Part de chaque unité de `de` qui revient à chaque unité de `vers`.

        `poids` : valeur par commune (index pcode_commune). Les appels de la chaîne passent la population des
        communes (recensement) quand elle est connue ; sans poids, la superficie sert de repli. Toute répartition
        d'une unité scindée est marquée « estimee »."""
        a = self.decoupage(de)[["pcode_commune", f"code_{niveau}"]].rename(columns={f"code_{niveau}": "code_de"})
        b = self.decoupage(vers)[["pcode_commune", f"code_{niveau}"]].rename(columns={f"code_{niveau}": "code_vers"})
        m = a.merge(b, on="pcode_commune", how="outer", indicator=True)
        if (m["_merge"] != "both").any():
            manquantes = sorted(m.loc[m["_merge"] != "both", "pcode_commune"])
            raise ValueError(f"communes absentes d'un des deux découpages : {manquantes[:10]}")
        w = poids if poids is not None else self.communes.set_index("pcode_commune")["superficie_km2"]
        m["poids"] = m["pcode_commune"].map(w).astype(float)
        if m["poids"].isna().any():
            raise ValueError(f"poids manquant pour {m['poids'].isna().sum()} communes")
        g = m.groupby(["code_de", "code_vers"], as_index=False)["poids"].sum()
        g["part"] = g["poids"] / g.groupby("code_de")["poids"].transform("sum")
        g["exacte"] = g.groupby("code_de")["code_vers"].transform("nunique") == 1
        return g.drop(columns="poids")

    def convertir(self, table: pd.DataFrame, de: str, vers: str, colonnes: list[str], niveau: str = "province",
                  cle: str = "code_province", autres_cles: list[str] | None = None,
                  poids: pd.Series | None = None) -> pd.DataFrame:
        """Réexprime des effectifs (sommables) d'un découpage dans un autre. Les totaux sont conservés.

        Colonne `estime` : vrai si la valeur vient, même en partie, d'une province scindée (répartie au prorata)."""
        p = self.matrice_passage(de, vers, niveau, poids)
        autres = autres_cles or []
        t = table.merge(p, left_on=cle, right_on="code_de", how="left")
        if t["code_vers"].isna().any():
            raise ValueError(f"codes inconnus dans le découpage {de} : {sorted(t.loc[t['code_vers'].isna(), cle].unique())}")
        for c in colonnes:
            t[c] = t[c] * t["part"]
        t["estime"] = ~t["exacte"]
        # min_count=1 : une somme de valeurs toutes inconnues reste inconnue (pas de zéro inventé)
        out = t.groupby([*autres, "code_vers"], as_index=False).agg(
            {**{c: (lambda s: s.sum(min_count=1)) for c in colonnes}, "estime": "any"})
        noms = self.provinces(vers)[[f"code_{niveau}", niveau]].drop_duplicates()
        out = out.rename(columns={"code_vers": f"code_{niveau}"}).merge(noms, on=f"code_{niveau}", how="left")
        return out[[*autres, f"code_{niveau}", niveau, *colonnes, "estime"]]

    # --- contrôle --------------------------------------------------------------------------------------------
    def controler(self) -> list[str]:
        """Liste des anomalies (vide si le référentiel est cohérent)."""
        pb = []
        c = self.communes
        if c["pcode_commune"].duplicated().any():
            pb.append("codes de commune en double")
        if c["commune"].isna().any() or (c["commune"].astype(str).str.strip() == "").any():
            pb.append("commune sans nom")
        if self.decoupages["decoupage"].duplicated().any():
            pb.append("identifiant de découpage en double")
        connus = set(c["pcode_commune"])
        for ident in self.decoupages["decoupage"]:
            r = self.rattachements[self.rattachements["decoupage"] == ident]
            if r.empty:
                pb.append(f"{ident} : aucun rattachement")
                continue
            if r["pcode_commune"].duplicated().any():
                pb.append(f"{ident} : commune rattachée à plusieurs provinces")
            manque = connus - set(r["pcode_commune"])
            if manque:
                pb.append(f"{ident} : {len(manque)} communes sans province")
            inconnues = set(r["pcode_commune"]) - connus
            if inconnues:
                pb.append(f"{ident} : communes inconnues {sorted(inconnues)[:5]}")
            pr = r.groupby("code_province")["code_region"].nunique()
            if (pr > 1).any():
                pb.append(f"{ident} : provinces dans plusieurs régions {list(pr[pr > 1].index)}")
            for niveau in ("province", "region"):
                n = r.groupby(f"code_{niveau}")[niveau].nunique()
                if (n > 1).any():
                    pb.append(f"{ident} : {niveau}s à plusieurs noms {list(n[n > 1].index)}")
        inconnus = set(self.rattachements["decoupage"]) - set(self.decoupages["decoupage"])
        if inconnus:
            pb.append(f"rattachements à des découpages non déclarés : {sorted(inconnus)}")
        return pb

    # --- évolution du découpage ------------------------------------------------------------------------------
    def nouveau_decoupage(self, ident: str, libelle: str, valide_du: str, source: str, depuis: str,
                          changements: pd.DataFrame | None = None, renommages: dict | None = None) -> "Referentiel":
        """Nouveau découpage = copie de `depuis`, avec des communes déplacées et des unités renommées.

        changements : lignes (pcode_commune, code_province, province, code_region, region) qui remplacent celles
        de `depuis` ; renommages : {(niveau, code): nouveau_nom}. L'ancien nom devient une variante reconnue."""
        if ident in set(self.decoupages["decoupage"]):
            raise ValueError(f"le découpage {ident} existe déjà")
        r = self.decoupage(depuis).set_index("pcode_commune")
        if changements is not None and not changements.empty:
            ch = changements.set_index("pcode_commune")
            inconnues = set(ch.index) - set(r.index)
            if inconnues:
                raise ValueError(f"communes inconnues : {sorted(inconnues)}")
            r.loc[ch.index, ch.columns] = ch
        variantes = []
        for (niveau, code), nom in (renommages or {}).items():
            masque = r[f"code_{niveau}"] == code
            if not masque.any():
                raise ValueError(f"{niveau} inconnue : {code}")
            variantes += [{"decoupage": ident, "niveau": niveau, "variante": v, "code": code}
                          for v in r.loc[masque, niveau].unique()]
            r.loc[masque, niveau] = nom
        anciennes = self.variantes_noms[self.variantes_noms["decoupage"] == depuis].assign(decoupage=ident)
        nouveau = Referentiel(
            communes=self.communes,
            decoupages=pd.concat([self.decoupages, pd.DataFrame([{"decoupage": ident, "libelle": libelle,
                                                                   "valide_du": valide_du, "source": source}])],
                                 ignore_index=True),
            rattachements=pd.concat([self.rattachements, r.reset_index().assign(decoupage=ident)[COLONNES["rattachements"]]],
                                    ignore_index=True),
            variantes_noms=pd.concat([self.variantes_noms, anciennes, pd.DataFrame(variantes, columns=COLONNES["variantes_noms"])],
                                     ignore_index=True).drop_duplicates(),
        )
        pb = nouveau.controler()
        if pb:
            raise ValueError("découpage incohérent : " + " ; ".join(pb))
        return nouveau

    def enregistrer(self, dossier: Path = REFERENTIEL) -> None:
        dossier.mkdir(parents=True, exist_ok=True)
        for nom in FICHIERS:
            getattr(self, nom)[COLONNES[nom]].to_csv(dossier / f"{nom}.csv", index=False, sep=";", encoding="utf-8")


def noms_officiels(dossier: Path = REFERENTIEL) -> dict[str, str]:
    """Nom d'affichage officiel (accents, traits d'union) des provinces et régions publiées en majuscules sans accent."""
    f = dossier / "noms_officiels.csv"
    if not f.exists():
        return {}
    t = pd.read_csv(f, sep=";", encoding="utf-8", dtype=str)
    return dict(zip(t["nom"], t["nom_officiel"]))


def nom_officiel(nom: str) -> str:
    """« SENO » → « Séno » ; « PLATEAU CENTRAL » → « Plateau-Central » ; un nom déjà en casse mixte est gardé."""
    if not isinstance(nom, str) or not nom:
        return "" if nom is None else str(nom)
    global _NOMS
    if _NOMS is None:
        _NOMS = noms_officiels()
    if nom in _NOMS:
        return _NOMS[nom]
    if nom != nom.upper():
        return nom
    petits = {"du", "de", "des", "la", "le", "les"}
    mots = nom.lower().replace("-", " - ").split(" ")
    return " ".join(m if i and m in petits else m[:1].upper() + m[1:] for i, m in enumerate(mots)).replace(" - ", "-")


_NOMS: dict[str, str] | None = None


def charger(dossier: Path = REFERENTIEL) -> Referentiel:
    t = {nom: pd.read_csv(dossier / f"{nom}.csv", sep=";", encoding="utf-8", dtype=str, keep_default_na=False)
         for nom in FICHIERS}
    for col in ("lat", "lon", "superficie_km2"):
        t["communes"][col] = pd.to_numeric(t["communes"][col])
    return Referentiel(**t)


def initialiser() -> Referentiel:
    """Référentiel de départ, construit depuis les limites COD-AB du Data Pack (version v03, valide au 2025-08-01).

    Deux découpages : celui des annuaires 2017-2025 (13 régions, 45 provinces) et celui de 2025 (17 régions,
    47 provinces). Les codes P anciens des communes donnent leur province d'avant la réforme."""
    from dcb.lecture import CSV, lire_csv

    def lire(n: str) -> pd.DataFrame:
        t = lire_csv(CSV / "04_Cartographie_SIG" / "COD-AB_limites_administratives" / f"bfa_admin_boundaries__bfa_{n}.csv")
        t.columns = t.iloc[0]
        return t.iloc[1:].reset_index(drop=True)

    c3, c2, c1 = lire("admin3"), lire("admin2"), lire("admin1")
    communes = pd.DataFrame({
        "pcode_commune": c3["adm3_pcode"], "commune": c3["adm3_name1"].where(c3["adm3_name1"].astype(str) != "", c3["adm3_name"]),
        "pcode_commune_ancien": c3["adm3_pcode_old"], "commune_ancien": c3["adm3_name_old"].where(c3["adm3_name_old"].astype(str) != "", c3["adm3_name"]),
        "lat": pd.to_numeric(c3["center_lat"]), "lon": pd.to_numeric(c3["center_lon"]),
        "superficie_km2": pd.to_numeric(c3["area_sqkm"]).round(2),
    }).sort_values("pcode_commune").reset_index(drop=True)
    nom_region = dict(zip(c1["adm1_pcode"], c1["adm1_name1"].where(c1["adm1_name1"].astype(str) != "", c1["adm1_name"])))
    nom_province = dict(zip(c2["adm2_pcode"], c2["adm2_name1"].where(c2["adm2_name1"].astype(str) != "", c2["adm2_name"])))
    nouveau = pd.DataFrame({
        "decoupage": "reforme_2025", "pcode_commune": c3["adm3_pcode"],
        "code_province": c3["adm2_pcode"], "province": c3["adm2_pcode"].map(nom_province),
        "code_region": c3["adm1_pcode"], "region": c3["adm1_pcode"].map(nom_region),
    })
    # ancien découpage : la province d'une commune se lit dans son ancien code P (BFrrpp…)
    nom_ancien = {k: geo.province(v) for k, v in zip(c2["adm2_pcode_old"], c2["adm2_name_old"])}
    code_p = c3["adm3_pcode_old"].str[:6]
    province_a = code_p.map(nom_ancien)
    if province_a.isna().any():
        raise ValueError("province ancienne introuvable pour certaines communes")
    region_a = province_a.map(geo.REGION_DE)
    code_r = {r: sorted(set(c3["adm3_pcode_old"].str[:4][region_a == r]))[0] for r in region_a.unique()}
    ancien = pd.DataFrame({
        "decoupage": "annuaires_2017_2025", "pcode_commune": c3["adm3_pcode"], "code_province": code_p,
        "province": province_a, "code_region": region_a.map(code_r), "region": region_a,
    })
    decoupages = pd.DataFrame([
        {"decoupage": "annuaires_2017_2025", "libelle": "13 régions, 45 provinces (annuaires statistiques 2017-2018 à 2024-2025)",
         "valide_du": "2001-01-01", "source": "COD-AB Burkina Faso v03, colonnes adm*_pcode_old (Data Pack)"},
        {"decoupage": "reforme_2025", "libelle": "17 régions, 47 provinces (réforme adoptée en Conseil des ministres le 2 juillet 2025)",
         "valide_du": "2025-07-02", "source": "COD-AB Burkina Faso v03, valide au 2025-08-01 (Data Pack)"},
    ])
    variantes = [{"decoupage": "annuaires_2017_2025", "niveau": "province", "variante": v, "code": code_p[province_a == p].iloc[0]}
                 for v, p in geo._ALIAS_PROVINCES.items()]
    variantes += [{"decoupage": "annuaires_2017_2025", "niveau": "region", "variante": v, "code": code_r[r]}
                  for v, r in geo._ALIAS_REGIONS.items()]
    # les provinces renommées en 2025 restent reconnues sous leur ancien nom
    ancien_par_nouveau = dict(zip(c2["adm2_pcode"], c2["adm2_name_old"]))
    variantes += [{"decoupage": "reforme_2025", "niveau": "province", "variante": ancien_par_nouveau[k], "code": k}
                  for k in nom_province if geo.cle(ancien_par_nouveau.get(k, "")) not in ("", geo.cle(nom_province[k]))]
    # centre des communes : le fichier n'en donne pas, on prend un point intérieur de chaque contour
    import geopandas as gpd

    from dcb.lecture import DATAPACK

    archive = DATAPACK / "04_Cartographie_SIG" / "COD-AB_limites_administratives" / "bfa_admin_boundaries.geojson.zip"
    g = gpd.read_file(f"zip://{archive.as_posix()}!bfa_admin3.geojson").set_index("adm3_pcode")
    pt = g.geometry.representative_point()
    communes["lat"] = communes["pcode_commune"].map(pt.y).round(5)
    communes["lon"] = communes["pcode_commune"].map(pt.x).round(5)
    # une variante qui désigne plusieurs unités (province scindée) n'est pas une variante : on l'écarte
    variantes = pd.DataFrame(variantes, columns=COLONNES["variantes_noms"]).drop_duplicates()
    ambigu = variantes.groupby(["decoupage", "niveau", "variante"])["code"].transform("nunique") > 1
    variantes = variantes[~ambigu]
    ref = Referentiel(communes=communes, decoupages=decoupages,
                      rattachements=pd.concat([ancien, nouveau], ignore_index=True)[COLONNES["rattachements"]],
                      variantes_noms=variantes.reset_index(drop=True))
    pb = ref.controler()
    if pb:
        raise ValueError(" ; ".join(pb))
    return ref


if __name__ == "__main__":
    if "--initialiser" in sys.argv:
        initialiser().enregistrer()
        print(f"référentiel écrit dans {REFERENTIEL.relative_to(RACINE)}")
    ref = charger()
    pb = ref.controler()
    print("contrôle :", "aucune anomalie" if not pb else pb)
    for _, d in ref.decoupages.iterrows():
        p = ref.provinces(d["decoupage"])
        print(f"- {d['decoupage']} (dès le {d['valide_du']}) : {p['code_region'].nunique()} régions, {len(p)} provinces, "
              f"{int(p['communes'].sum())} communes")
    m = ref.matrice_passage("annuaires_2017_2025", "reforme_2025")
    print("provinces anciennes scindées :", sorted(m.loc[~m["exacte"], "code_de"].unique()))
