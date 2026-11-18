"""Tests des calculs sensibles. Lancer depuis la racine : PYTHONPATH=src python -m pytest -q"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dcb import geo
from dcb.indicateurs import SORTIE, config
from dcb.lecture import nombre
from dcb.optimisation import comparer, evaluer, optimiser, repartition_proportionnelle
from dcb.prevision import _croissance_amortie, _demographique, _naive, cas_communs, fiabilite

INTERIM = SORTIE.parent / "interim"
donnees_presentes = pytest.mark.skipif(not (SORTIE / "province_annee.csv").exists(),
                                       reason="lancer d'abord la chaîne : python -m dcb.pipeline")


# ---------- lecture et référentiel ----------
@pytest.mark.parametrize("texte, attendu", [("306 926", 306926.0), ("78,2", 78.2), ("3 308 096", 3308096.0),
                                            ("100%", 100.0), ("-", None), ("", None), ("BANWA", None)])
def test_nombre(texte, attendu):
    assert nombre(texte) == attendu


def test_referentiel_45_provinces_13_regions():
    assert len(geo.PROVINCES) == 45 and len(geo.REGIONS_PROVINCES) == 13
    assert len(set(geo.PROVINCES)) == 45


@pytest.mark.parametrize("libelle, attendu", [("LES BALE", "BALE"), ("Balé", "BALE"), ("KOURITTENGA", "KOURITENGA"),
                                              ("Komandjari", "KOMANDJOARI"), ("Kénédougou", "KENEDOUGOU"),
                                              ("Total Région", None), ("CENTRE", None)])
def test_province_variantes(libelle, attendu):
    assert geo.province(libelle) == attendu


def test_region_variantes():
    assert geo.region("HAUT-BASSINS") == "HAUTS-BASSINS"
    assert geo.region("Boucle du Mouhoun") == "BOUCLE DU MOUHOUN"
    assert geo.region("KADIOGO") is None


# ---------- prévision ----------
def test_methodes_de_prevision():
    y = np.array([100.0, 110.0, 121.0, 133.1, 146.41])  # +10 % par an
    assert _naive(y, 3, 5) == 146.41
    un_an = _croissance_amortie(y, 1, 5)
    assert un_an == pytest.approx(146.41 * 1.10)
    assert _croissance_amortie(y, 2, 5) == pytest.approx(un_an * 1.05)  # croissance réduite de moitié
    assert _demographique(1000.0, 2024, 2, {2025: 200.0, 2027: 220.0}) == pytest.approx(1100.0)
    assert _demographique(1000.0, 2024, 2, {2025: 200.0}) is None


def test_wape_et_cas_communs():
    t = pd.DataFrame({"methode": ["a", "a", "b"], "province": ["P", "Q", "P"], "origine": [2020, 2020, 2020],
                      "horizon": [1, 1, 1], "prevu": [90.0, 220.0, 100.0], "realise": [100.0, 200.0, 100.0]})
    f = fiabilite(t).set_index("methode")["wape"]
    assert f["a"] == pytest.approx(30 / 300) and f["b"] == 0
    assert len(cas_communs(t)) == 2  # seul le cas (P, 2020, 1) est prévu par les deux méthodes


# ---------- indice de besoin ----------
def test_indice_regroupe_et_classe():
    from dcb.indice import indice_besoin

    cfg = config()
    n = 9
    t = pd.DataFrame({"annee_scolaire": cfg["annee_reference"], "statut": cfg["statut_cible"], "region": "R",
                      "province": [f"P{i}" for i in range(n)], "aucune_ecole_ouverte": False,
                      "eleves_par_maitre": range(40, 40 + 5 * n, 5), "eleves_par_salle": range(40, 40 + 5 * n, 5),
                      "part_salles_precaires": [0.1] * n, "part_salles_mauvais_etat": [0.1] * n})
    ind, bilan = indice_besoin(t, cfg)
    # P8 est la plus surchargée, le bâti est identique partout : elle est 1re, sans ambiguïté
    assert ind.iloc[0]["province"] == f"P{n - 1}" and ind.iloc[0]["rang"] == 1
    assert ind["indice_besoin"].between(0, 1).all() and not ind.iloc[0]["rang_instable"]
    assert set(["score_surcharge", "score_bati"]) <= set(ind.columns)


# ---------- répartition ----------
def test_repartition_proportionnelle_somme_exacte():
    r = repartition_proportionnelle(pd.Series([1.0, 1.0, 1.0]), 10)
    assert r.sum() == 10 and sorted(r) == [3, 3, 4]
    assert repartition_proportionnelle(pd.Series([3.0, 1.0]), 0).sum() == 0


def _cas_jouet() -> pd.DataFrame:
    # A est très surchargée (100 élèves par maître), B est juste à la norme
    return pd.DataFrame({"province": ["A", "B"], "region": ["R", "R"], "eleves_actuels": [1000.0, 1000.0],
                         "maitres": [10.0, 20.0], "salles": [10.0, 20.0], "eleves_horizon": [1000.0, 1000.0],
                         "part_du_pic": [1.0, 1.0], "construction_possible": [True, True]})


def test_optimisation_cas_jouet():
    cfg = config()
    cfg["normes"] = {"eleves_par_maitre": 50, "eleves_par_salle": 50}
    cfg["optimisation"].update(un_maitre_par_salle=True, absorption_max_part=None, budget_fcfa=None)
    res, statut = optimiser(_cas_jouet(), cfg, n=10, m=10)
    assert statut == "Optimal"
    a = res.set_index("province")
    # tous les moyens vont à la province surchargée, qui retombe à la norme : 1000 / (10 + 10) = 50
    assert a.loc["A", "enseignants_attribues"] == 10 and a.loc["A", "salles_attribuees"] == 10
    assert a.loc["B", "enseignants_attribues"] == 0
    assert evaluer(res, cfg)["eleves_au_dela_norme_maitre"] == 0


def test_optimisation_respecte_les_contraintes():
    cfg = config()
    cfg["optimisation"].update(un_maitre_par_salle=True, absorption_max_part=None, budget_fcfa=None)
    d = _cas_jouet()
    d.loc[0, "construction_possible"] = False
    res, _ = optimiser(d, cfg, n=10, m=10)
    a = res.set_index("province")
    assert a.loc["A", "salles_attribuees"] == 0          # pas de construction en zone peu accessible
    assert a.loc["A", "enseignants_attribues"] == 0      # donc pas d'enseignant sans salle
    assert res["enseignants_attribues"].sum() <= 10 and res["salles_attribuees"].sum() <= 10


def test_optimisee_jamais_pire_que_proportionnelle():
    cfg = config()
    cfg["optimisation"].update(un_maitre_par_salle=False, absorption_max_part=None, budget_fcfa=None)
    _, bilan, _ = comparer(_cas_jouet(), cfg, n=6, m=6)
    b = bilan.set_index("methode")["eleves_au_dela_norme_maitre"]
    assert b["optimisee"] <= b["proportionnelle"] <= b["sans_moyens_nouveaux"]


def _trois_provinces() -> pd.DataFrame:
    # A : 100 élèves par maître ; C : 1000 / 14 ≈ 71,4 ; B : à la norme (50)
    return pd.DataFrame({"province": ["A", "B", "C"], "region": ["R"] * 3, "eleves_actuels": [1000.0] * 3,
                         "maitres": [10.0, 20.0, 14.0], "salles": [30.0, 30.0, 30.0], "eleves_horizon": [1000.0] * 3,
                         "part_du_pic": [1.0] * 3, "construction_possible": [True] * 3})


def _cfg_simple() -> dict:
    cfg = config()
    cfg["normes"] = {"eleves_par_maitre": 50, "eleves_par_salle": 50}
    cfg["optimisation"].update(un_maitre_par_salle=True, absorption_max_part=None, budget_fcfa=None)
    return cfg


def test_optimisation_sert_d_abord_la_plus_chargee():
    # 4 enseignants : A passe de 100 à 1000 / 14 ≈ 71,4, le niveau de C ; C et B ne reçoivent rien
    res, statut = optimiser(_trois_provinces(), _cfg_simple(), n=4, m=0)
    a = res.set_index("province")["enseignants_attribues"]
    assert statut == "Optimal" and a["A"] == 4 and a["B"] == 0 and a["C"] == 0


def test_optimisation_independante_de_l_ordre():
    cfg = _cfg_simple()
    d = _trois_provinces()
    r1, _ = optimiser(d, cfg, n=9, m=0)
    r2, _ = optimiser(d.iloc[::-1].reset_index(drop=True), cfg, n=9, m=0)
    a1 = r1.set_index("province")["enseignants_attribues"]
    a2 = r2.set_index("province")["enseignants_attribues"]
    assert (a1.sort_index() == a2.sort_index()).all()


def test_besoins_respecte_les_regles():
    from dcb.optimisation import au_prorata_des_besoins

    cfg = _cfg_simple()
    d = _cas_jouet()
    d.loc[0, "construction_possible"] = False  # A ne peut pas construire, et n'a aucune salle libre
    r = au_prorata_des_besoins(d, cfg, n=10, m=10).set_index("province")
    assert r.loc["A", "salles_attribuees"] == 0 and r.loc["A", "enseignants_attribues"] == 0
    assert r["enseignants_attribues"].sum() <= 10 and r["salles_attribuees"].sum() <= 10


def test_rouvrir_d_abord_sans_construction_mais_avec_salles_rouvertes():
    from dcb.optimisation import au_prorata_des_besoins

    cfg = _cfg_simple()
    # A : aucune salle libre, on n'y construit pas (rouvrir d'abord), 3 salles d'écoles fermées à rouvrir
    d = pd.DataFrame({"province": ["A", "B"], "region": ["R"] * 2, "eleves_actuels": [1000.0] * 2,
                      "maitres": [10.0, 20.0], "salles": [10.0, 20.0], "eleves_horizon": [1000.0] * 2,
                      "part_du_pic": [1.0] * 2, "construction_possible": [False, True], "salles_a_rouvrir": [3, 0]})
    for r in (optimiser(d, cfg, n=10, m=5)[0], au_prorata_des_besoins(d, cfg, n=10, m=5)):
        r = r.set_index("province")
        assert r.loc["A", "salles_attribuees"] == 0
        assert r.loc["A", "enseignants_attribues"] == 3 == r.loc["A", "salles_rouvertes"]
        assert r.loc["B", "salles_rouvertes"] == 0


# ---------- contrôle avant dépôt ----------
def test_controle_depot_detecte_un_terme_cache(tmp_path, monkeypatch):
    import zipfile

    from dcb import depot

    termes = tmp_path / "termes.txt"
    termes.write_text("mot-interdit\n", encoding="utf-8")
    monkeypatch.setattr(depot, "TERMES", termes)
    propre = tmp_path / "E01_04-analyse_D3_analyst_table_v1.csv"
    propre.write_text("a;b\n1;2\n", encoding="utf-8")
    archive = tmp_path / "E01_04-analyse_D3_scientist_code_v1.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:  # compressé : le terme n'est pas lisible de l'extérieur
        z.writestr("src/module.py", "# un commentaire avec MOT-INTERDIT dedans\n" * 50)
    assert depot.controler([propre]) == []
    problemes = depot.controler([propre, archive])
    assert len(problemes) == 1 and "module.py" in problemes[0]
    mal_nomme = tmp_path / "fichier avec espace.csv"
    mal_nomme.write_text("a\n", encoding="utf-8")
    assert any("espace ou accent" in p for p in depot.controler([mal_nomme]))


# ---------- données produites par la chaîne ----------
@donnees_presentes
def test_table_province_annee_complete():
    t = pd.read_csv(SORTIE / "province_annee.csv", sep=";")
    assert len(t) == 8 * 45 * 3
    pivot = t.pivot_table(index=["annee_scolaire", "province"], columns="statut", values="eleves")
    assert (pivot["public"] + pivot["prive"] == pivot["total"]).all()


@donnees_presentes
def test_totaux_nationaux_publies():
    syn = pd.read_csv(INTERIM / "annuaires" / "synthese.csv", sep=";")
    for annee, g in syn[syn["statut"] == "total"].groupby("annee_scolaire"):
        national = g[g["niveau"] == "national"]
        provinces = g[g["niveau"] == "province"]
        for mesure in ("ecoles", "salles", "maitres", "eleves"):
            assert provinces[mesure].sum() == national[mesure].iloc[0], (annee, mesure)


@donnees_presentes
def test_rapprochement_fichier_principal():
    r = pd.read_csv(SORTIE.parent.parent / "outputs" / "controles" / "rapprochement_annuaires_principal.csv", sep=";")
    assert len(r) == 224
    assert (r["ecart"].abs() / r["fichier_principal"]).max() < 0.001  # au plus 0,1 % d'écart


@donnees_presentes
def test_population_6_11_complete():
    p = pd.read_csv(INTERIM / "demographie" / "population_6_11_province.csv", sep=";")
    p = p[p["niveau"] == "province"]
    assert p["entite"].nunique() == 45 and len(p) == 45 * 16


# ---------- post-primaire ----------
from dcb.post_primaire import NATIONAL, _libelle, _valeurs, extraire_tableau  # noqa: E402


def test_post_primaire_signe_detache():
    # « - ¦ 11,5 » : signe moins détaché du nombre dans les tableaux de 2022-23
    assert _valeurs(["2 798", "-", "11,5", "55"]) == [2798.0, -11.5, 55.0]
    assert _valeurs(["Public", "12"]) is None


def test_post_primaire_libelles():
    assert _libelle("Boucle du") == "BOUCLE DU MOUHOUN"
    assert _libelle("Centre Nord") == "CENTRE-NORD"
    assert _libelle("Total National") == NATIONAL and _libelle("Burkina Faso") == NATIONAL


def test_post_primaire_ligne_nationale_avant_les_regions_ignoree():
    regions = list(geo.REGIONS_PROVINCES)
    lignes = [["TITRE"], ["Total", "1", "2"]] + [[r, "10", "20"] for r in regions] + [["Burkina Faso", "130", "260"]]
    df = pd.DataFrame([{"page": 1, "c1": l[0], "c2": l[1] if len(l) > 1 else "", "c3": l[2] if len(l) > 2 else ""}
                       for l in lignes])
    t = extraire_tableau(df, "TITRE", ["a", "b"]).set_index("region")
    assert t.loc[NATIONAL, "a"] == 130 and len(t) == 14


@pytest.mark.skipif(not (SORTIE / "post_primaire_region.csv").exists(), reason="lancer d'abord dcb.post_primaire")
def test_post_primaire_totaux_publies():
    t = pd.read_csv(SORTIE / "post_primaire_region.csv", sep=";")
    n = t[(t["niveau"] == "national") & (t["annee_scolaire"] == "2023-2024")].iloc[0]
    # chiffres imprimés dans le tableau de bord 2023-2024 (p. 12, 46, 48 et commentaire p. 49)
    assert n["eleves_pp_sec"] == 1_189_432 and n["etablissements_2019"] == 4_322
    assert n["salles_2019"] == 26_176 and n["excedent_net_places"] == 55_064
    assert len(t[t["niveau"] == "region"]) == 26


# --- Contraintes du décideur et service en ligne ---

def test_contraintes_plancher_et_plafond_respectes():
    from dcb.optimisation import optimiser
    d, cfg = _trois_provinces(), _cfg_simple()
    libre, _ = optimiser(d, cfg, n=30, m=0)
    tri = libre.sort_values("enseignants_attribues")
    moins_servie, plus_servie = tri.iloc[0]["province"], tri.iloc[-1]["province"]
    plancher = int(tri.iloc[0]["enseignants_attribues"]) + 2
    plafond = max(0, int(tri.iloc[-1]["enseignants_attribues"]) - 2)
    c = {"provinces": {moins_servie: {"min_enseignants": plancher}, plus_servie: {"max_enseignants": plafond}}}
    res, statut = optimiser(d, cfg, n=30, m=0, contraintes=c)
    r = res.set_index("province")["enseignants_attribues"]
    assert statut == "Optimal" and r[moins_servie] >= plancher and r[plus_servie] <= plafond


def test_contraintes_impossibles_signalees():
    from dcb.optimisation import comparer
    d, cfg = _trois_provinces(), _cfg_simple()
    with pytest.raises(ValueError):
        comparer(d, cfg, n=5, m=0, contraintes={"provinces": {d["province"].iloc[0]: {"min_enseignants": 50}}})


def test_contrainte_sur_province_inconnue_refusee():
    from dcb.optimisation import optimiser
    with pytest.raises(ValueError):
        optimiser(_trois_provinces(), _cfg_simple(), n=5, m=0, contraintes={"provinces": {"ATLANTIDE": {"min_enseignants": 1}}})


# --- Référentiel territorial : le découpage évolue sans toucher au code ---

def _ref():
    from dcb import territoire
    if not (territoire.REFERENTIEL / "communes.csv").exists():
        pytest.skip("référentiel non construit (python -m dcb.territoire --initialiser)")
    return territoire.charger()


def test_referentiel_coherent_et_deux_decoupages():
    ref = _ref()
    assert ref.controler() == []
    assert len(ref.provinces("annuaires_2017_2025")) == 45
    assert len(ref.provinces("reforme_2025")) == 47
    assert ref.en_vigueur("2024-10-01") == "annuaires_2017_2025"
    assert ref.en_vigueur("2026-10-01") == "reforme_2025"


def test_passage_ancien_vers_2025_conserve_les_totaux():
    ref = _ref()
    p = ref.provinces("annuaires_2017_2025")
    t = pd.DataFrame({"code_province": p["code_province"], "eleves": range(1000, 1000 + 45 * 10, 10)})
    out = ref.convertir(t, "annuaires_2017_2025", "reforme_2025", ["eleves"])
    assert len(out) == 47
    assert out["eleves"].sum() == pytest.approx(t["eleves"].sum())
    # seules les provinces issues d'une province scindée (Soum, Tapoa) sont estimées
    assert out["estime"].sum() == 4


def test_creation_d_une_province():
    ref = _ref()
    d = ref.decoupage("reforme_2025")
    code = d["code_province"].value_counts().index[0]  # province ayant le plus de communes
    deux = d.loc[d["code_province"] == code, "pcode_commune"].head(2)
    region = d.loc[d["code_province"] == code, ["code_region", "region"]].iloc[0]
    ch = pd.DataFrame({"pcode_commune": deux, "code_province": "BF99NOUV", "province": "Nouvelle province",
                       "code_region": region["code_region"], "region": region["region"]})
    ref2 = ref.nouveau_decoupage("essai_creation", "essai", "2030-01-01", "test", "reforme_2025", changements=ch)
    assert len(ref2.provinces("essai_creation")) == 48
    assert ref2.en_vigueur("2031-01-01") == "essai_creation"
    p = ref2.provinces("reforme_2025")
    t = pd.DataFrame({"code_province": p["code_province"], "maitres": 100.0})
    poids = pd.Series(1.0, index=ref.communes["pcode_commune"])
    out = ref2.convertir(t, "reforme_2025", "essai_creation", ["maitres"], poids=poids)
    assert out["maitres"].sum() == pytest.approx(t["maitres"].sum())
    assert set(out.loc[out["estime"], "code_province"]) == {code, "BF99NOUV"}


def test_renommage_d_une_province_reste_lisible_sous_l_ancien_nom():
    ref = _ref()
    p = ref.provinces("reforme_2025").iloc[0]
    ref2 = ref.nouveau_decoupage("essai_renommage", "essai", "2030-01-01", "test", "reforme_2025",
                                 renommages={("province", p["code_province"]): "Nom tout neuf"})
    assert ref2.code("essai_renommage", "province", "NOM TOUT NEUF") == p["code_province"]
    assert ref2.code("essai_renommage", "province", p["province"]) == p["code_province"]
    m = ref2.matrice_passage("reforme_2025", "essai_renommage")
    assert m["exacte"].all()


def test_decoupage_incoherent_refuse():
    ref = _ref()
    d = ref.decoupage("reforme_2025")
    une = d.iloc[[0]].assign(code_region="BF00")  # la province se retrouve dans deux régions
    with pytest.raises(ValueError):
        ref.nouveau_decoupage("essai_faux", "essai", "2030-01-01", "test", "reforme_2025", changements=une)


# --- Entrepôt : ajout de données par un technicien, contrôles, retour arrière ---

def _entrepot(tmp_path):
    from dcb import entrepot
    ref = _ref()
    return entrepot, entrepot.connexion(tmp_path / "e.sqlite"), ref


def _fichier_primaire(ref, annee="2025-2026", decoupage="reforme_2025", eleves=5000.0):
    p = ref.provinces(decoupage)
    lignes = []
    for c in p["code_province"]:
        for st, k in (("public", 0.8), ("prive", 0.2), ("total", 1.0)):
            lignes.append({"annee_scolaire": annee, "code_territoire": c, "statut": st, "ecoles": 10 * k,
                           "salles": 100 * k, "groupes_pedagogiques": 100 * k, "maitres": 100 * k, "eleves": eleves * k})
    return pd.DataFrame(lignes)


def test_import_d_une_nouvelle_annee_dans_le_nouveau_decoupage(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    r, lot = e.importer_table(_fichier_primaire(ref), "primaire_province", "technicien", "f.xlsx", "h1", con=con, ref=ref)
    assert r.accepte and lot == 1 and r.decoupage == "reforme_2025"
    t = e.lire("primaire_province", con=con, ref=ref)
    assert len(t) == 47 * 3
    # relue dans l'ancien découpage : 45 provinces, totaux conservés
    a = e.lire("primaire_province", decoupage="annuaires_2017_2025", con=con, ref=ref)
    assert a["code_territoire"].nunique() == 45
    assert a["eleves"].sum() == pytest.approx(t["eleves"].sum())


def test_import_refuse_territoire_inconnu_doublon_et_negatif(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    f = _fichier_primaire(ref)
    f.loc[0, "code_territoire"] = "BF0000"
    f.loc[1, "eleves"] = -3
    f = pd.concat([f, f.iloc[[5]]])
    r, lot = e.importer_table(f, "primaire_province", "technicien", "f.xlsx", "h2", con=con, ref=ref)
    assert lot is None and not r.accepte
    texte = r.texte()
    assert "territoire inconnu" in texte and "double" in texte and "inférieures à 0" in texte
    assert e.lots(con).empty


def test_nom_de_province_accepte_a_la_place_du_code(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    f = _fichier_primaire(ref, annee="2023-2024", decoupage="annuaires_2017_2025")
    noms = ref.provinces("annuaires_2017_2025").set_index("code_province")["province"]
    f["territoire"] = f["code_territoire"].map(noms).str.lower()
    f.loc[f["territoire"] == "bale", "territoire"] = "Les Balé"  # variante d'écriture connue
    r, lot = e.importer_table(f.drop(columns="code_territoire"), "primaire_province", "t", "f.csv", "h3", con=con, ref=ref)
    assert r.accepte, r.texte()


def test_nouvelle_version_d_une_annee_puis_retrait(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    _, l1 = e.importer_table(_fichier_primaire(ref, eleves=5000), "primaire_province", "t", "v1", "a", con=con, ref=ref)
    r2, l2 = e.importer_table(_fichier_primaire(ref, eleves=7000), "primaire_province", "t", "v2", "b", con=con, ref=ref)
    assert l2 == 2 and any("variation" in a for a in r2.avertissements) is False  # même année : pas une variation annuelle
    assert e.lire("primaire_province", con=con, ref=ref)["eleves"].max() == 7000
    e.retirer(l2, "t", con=con)
    assert e.lire("primaire_province", con=con, ref=ref)["eleves"].max() == 5000
    assert len(e.lots(con)) == 2  # rien n'est effacé


def test_forte_variation_signalee_sans_bloquer(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    e.importer_table(_fichier_primaire(ref, annee="2025-2026", eleves=5000), "primaire_province", "t", "a", "x", con=con, ref=ref)
    r, lot = e.importer_table(_fichier_primaire(ref, annee="2026-2027", eleves=9000), "primaire_province", "t", "b", "y", con=con, ref=ref)
    assert lot is not None and any("variation" in a for a in r.avertissements)


def test_gabarit_rempli_puis_importe(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    chemin = e.gabarit("primaire_province", "2025-2026", tmp_path / "g.xlsx", ref=ref)
    g = pd.read_excel(chemin, sheet_name="donnees")
    assert len(g) == 47 * 3
    for v, x in (("ecoles", 10), ("salles", 100), ("groupes_pedagogiques", 100), ("maitres", 100), ("eleves", 5000)):
        g[v] = x
    g.loc[g["statut"] == "total", ["ecoles", "salles", "groupes_pedagogiques", "maitres", "eleves"]] *= 2
    g.to_excel(tmp_path / "rempli.xlsx", sheet_name="donnees", index=False)
    r, lot = e.importer(tmp_path / "rempli.xlsx", "primaire_province", "technicien", con=con, ref=ref)
    assert r.accepte and lot is not None, r.texte()


# --- Carte scolaire à la commune ---

def _carte():
    from dcb.indicateurs import SORTIE
    f = SORTIE / "carte_scolaire_commune.csv"
    if not f.exists():
        pytest.skip("carte scolaire non produite (python -m dcb.carte_scolaire)")
    return pd.read_csv(f, sep=";", encoding="utf-8")


def test_carte_couvre_toutes_les_communes_et_le_recensement():
    c = _carte()
    assert len(c) == 351 and c["pcode_commune"].is_unique
    assert c["population_2019"].sum() == 20_505_155  # total officiel du 5e RGPH


def test_projection_communale_conserve_les_totaux_provinciaux():
    from dcb.carte_scolaire import PROJECTIONS
    c = _carte()
    p = pd.read_csv(PROJECTIONS, sep=";", encoding="utf-8")
    p = p[(p["niveau"] == "province") & (p["annee"] == 2030)].set_index("entite")["population_6_11"]
    somme = c.groupby("province_ancienne")["enfants_6_11_2030"].sum()
    assert (somme - p.reindex(somme.index)).abs().max() <= 20  # écarts d'arrondi seulement


def test_deplaces_egal_total_conasur():
    c = _carte()
    assert c["pdi_total"].sum() == 1_882_391  # ligne ENSEMBLE du relevé CONASUR du 31/12/2022


# --- Sites à construire : couverture maximale gloutonne ---

def test_sites_servent_d_abord_le_plus_gros_groupe_d_enfants_eloignes():
    from dcb.implantation import sites_a_construire
    rng = np.random.default_rng(0)
    def groupe(lon, lat, n, total):
        return pd.DataFrame({"lon": lon + rng.normal(0, 0.003, n), "lat": lat + rng.normal(0, 0.003, n),
                             "enfants": total / n, "pcode_commune": "A", "distance_km": 10.0})
    d = pd.concat([groupe(-1.0, 12.0, 50, 600), groupe(-2.0, 13.0, 50, 300), groupe(-3.0, 11.0, 50, 100)])
    s = sites_a_construire(d, rayon_km=3, seuil=150, nombre_max=10, communes_exclues=set())
    assert len(s) == 2  # le troisième groupe (100 enfants) est sous le seuil
    assert s.iloc[0]["enfants_rapproches"] == pytest.approx(600, rel=0.01)
    assert abs(s.iloc[0]["lon"] + 1.0) < 0.05
    # les enfants déjà proches d'une école et les communes exclues ne comptent pas
    assert sites_a_construire(d.assign(distance_km=1.0), 3, 150, 10, set()).empty
    assert sites_a_construire(d, 3, 150, 10, {"A"}).empty


def test_gabarit_vide_refuse(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    chemin = e.gabarit("primaire_province", "2025-2026", tmp_path / "vide.xlsx", ref=ref)
    r, lot = e.importer(chemin, "primaire_province", "technicien", con=con, ref=ref)
    assert lot is None and any("aucune valeur" in b.lower() for b in r.bloquants)


def test_service_controle_et_import_protege(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from dcb import entrepot
    from dcb.service import app
    ref = _ref()
    monkeypatch.setenv("DCB_JETON_ADMIN", "jeton-de-test")
    monkeypatch.setattr(entrepot, "ENTREPOT", tmp_path / "e.sqlite")
    f = tmp_path / "f.csv"
    _fichier_primaire(ref).to_csv(f, index=False, sep=";")
    c = TestClient(app)
    r = c.post("/api/entrepot/controler", data={"type_donnee": "primaire_province"}, files={"fichier": ("f.csv", f.read_bytes())})
    assert r.status_code == 200 and r.json()["accepte"]
    sans = c.post("/api/entrepot/importer", data={"type_donnee": "primaire_province", "auteur": "t"}, files={"fichier": ("f.csv", f.read_bytes())})
    assert sans.status_code == 401
    avec = c.post("/api/entrepot/importer", data={"type_donnee": "primaire_province", "auteur": "t"},
                  files={"fichier": ("f.csv", f.read_bytes())}, headers={"Authorization": "Bearer jeton-de-test"})
    assert avec.status_code == 200 and avec.json()["lot"] == 1


# --- Robustesse de la mise à jour annuelle (audit du 16/11) ---

def test_fichier_partiel_refuse(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    f = _fichier_primaire(ref)
    trois = f["code_territoire"].drop_duplicates().head(3)
    r, lot = e.importer_table(f[f["code_territoire"].isin(trois)], "primaire_province", "t", "p.xlsx", "hp", con=con, ref=ref)
    assert lot is None and any("le compléter" in b for b in r.bloquants)


def test_conversion_garde_les_valeurs_inconnues():
    ref = _ref()
    p = ref.provinces("annuaires_2017_2025")
    t = pd.DataFrame({"code_province": p["code_province"], "salles_precaires": np.nan, "eleves": 100.0})
    out = ref.convertir(t, "annuaires_2017_2025", "reforme_2025", ["salles_precaires", "eleves"])
    assert out["salles_precaires"].isna().all() and out["eleves"].sum() == pytest.approx(4500)


def test_amorcage_ne_reimporte_pas_un_lot_retire(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    t = _fichier_primaire(ref, annee="2024-2025", decoupage="annuaires_2017_2025")
    _, lot = e.importer_table(t, "primaire_province", "systeme (amorçage)", "a.csv", "x", decoupage="annuaires_2017_2025", con=con, ref=ref)
    e.retirer(lot, "admin", con=con)
    e._REMPLACER = False
    msg = e._amorcer_table(con, ref, t, "primaire_province", "a.csv", "source")
    assert "déjà amorcé" in msg and len(e.lots(con)) == 1


def test_service_repartir_par_defaut_et_contrainte_impossible():
    from fastapi.testclient import TestClient
    from dcb.indicateurs import SORTIE
    from dcb.service import app
    if not (SORTIE / "province_annee.csv").exists():
        pytest.skip("chaîne non exécutée")
    c = TestClient(app)
    r = c.post("/api/repartir", json={"enseignants": 500, "salles": 200})
    assert r.status_code == 200 and r.json()["statut"] == "Optimal" and r.json()["enseignants_utilises"] <= 500
    prov = r.json()["repartitions"]["optimisee"][0]["province"]
    assert c.post("/api/repartir", json={"enseignants": 10, "provinces": {prov: {"min_enseignants": 500}}}).status_code == 422


def test_service_erreurs_lisibles_et_sante():
    from fastapi.testclient import TestClient

    from dcb.service import app
    if not (SORTIE / "province_annee.csv").exists():
        pytest.skip("chaîne non exécutée")
    c = TestClient(app)
    assert c.get("/api/sante").json()["etat"] == "ok"
    r = c.post("/api/repartir", json={"enseignants": -5})
    assert r.status_code == 422 and r.json()["detail"] == "enseignants à répartir : doit être positif ou nul"
    # LOROUM : on y rouvre d'abord, on n'y construit pas : un plancher de salles est expliqué, pas un échec muet
    r = c.post("/api/repartir", json={"provinces": {"LOROUM": {"min_salles": 10}}})
    assert r.status_code == 422 and "aucune salle neuve" in r.json()["detail"]


def test_retrospectif_sans_information_du_futur():
    from dcb.retrospectif import _sans_fuite, periode
    if not (SORTIE / "province_annee.csv").exists():
        pytest.skip("chaîne non exécutée")
    cfg = config()
    t = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    assert _sans_fuite(t, "2019-2020")["annee_scolaire"].max() == "2019-2020"
    b, _ = periode(t, cfg, "2019-2020", "2024-2025")
    b = b.set_index("methode")
    # mêmes moyens pour toutes les répartitions ; l'optimisée ne fait pas pire que la réalité
    assert (b["enseignants_attribues"] <= b.loc["reelle", "enseignants_attribues"]).all()
    assert b.loc["optimisee", "eleves_au_dela_norme_maitre"] <= b.loc["reelle", "eleves_au_dela_norme_maitre"]


def test_redeploiement_ne_vide_pas_une_province_sous_la_norme():
    cfg = _cfg_simple()
    # B : 20 maîtres pour 500 élèves (norme 50 : 10 suffisent) ; A : 100 élèves par maître, salles libres
    d = pd.DataFrame({"province": ["A", "B"], "region": ["R"] * 2, "eleves_actuels": [1000.0, 500.0],
                      "maitres": [10.0, 20.0], "salles": [30.0, 20.0], "eleves_horizon": [1000.0, 500.0],
                      "part_du_pic": [1.0] * 2, "construction_possible": [True] * 2})
    r, statut = optimiser(d, cfg, n=0, m=0, redeploiement=50)
    r = r.set_index("province")
    assert statut == "Optimal" and r.loc["B", "redeployes_sortants"] == 10 == r.loc["A", "redeployes_entrants"]
    assert r.loc["B", "maitres"] + r.loc["B", "solde_redeploiement"] >= 500 / 50


def test_export_excel_du_plan():
    import io

    import openpyxl
    from fastapi.testclient import TestClient

    from dcb.service import app
    if not (SORTIE / "province_annee.csv").exists():
        pytest.skip("chaîne non exécutée")
    r = TestClient(app).post("/api/repartir.xlsx", json={"enseignants": 500, "salles": 200})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Fiche", "Plan par province", "Comparaison", "Hypothèses"]
    plan = wb["Plan par province"]
    affectes = sum(plan.cell(i, 5).value for i in range(2, plan.max_row) if isinstance(plan.cell(i, 5).value, int))
    assert affectes == 500


def test_gabarit_rempli_pour_quelques_provinces_refuse(tmp_path):
    # le fichier type contient toutes les lignes : seules les lignes remplies comptent pour la complétude
    e, con, ref = _entrepot(tmp_path)
    chemin = e.gabarit("primaire_province", "2025-2026", tmp_path / "partiel.xlsx", ref=ref)
    g = pd.read_excel(chemin, sheet_name="donnees", dtype=object)
    remplir = g["code_territoire"].drop_duplicates().head(10)
    for v in ("ecoles", "salles", "groupes_pedagogiques", "maitres", "eleves"):
        g.loc[g["code_territoire"].isin(remplir), v] = 100
    r, lot = e.importer_table(g, "primaire_province", "t", "partiel.xlsx", "hpart", con=con, ref=ref)
    assert lot is None and any("territoires renseignés" in b for b in r.bloquants)


def test_message_de_controle_cite_la_ligne_et_la_valeur(tmp_path):
    e, con, ref = _entrepot(tmp_path)
    f = _fichier_primaire(ref).reset_index(drop=True)
    f.loc[3, "maitres"] = -7
    r, lot = e.importer_table(f, "primaire_province", "t", "neg.csv", "hneg", con=con, ref=ref)
    assert lot is None
    msg = next(b for b in r.bloquants if "inférieures" in b)
    assert "ligne 5" in msg and "-7" in msg


def test_contrainte_impossible_nommee():
    from fastapi.testclient import TestClient

    from dcb.service import app
    if not (SORTIE / "province_annee.csv").exists():
        pytest.skip("chaîne non exécutée")
    r = TestClient(app).post("/api/repartir", json={"enseignants": 3000, "salles": 0, "provinces": {"KADIOGO": {"min_enseignants": 2000}}})
    assert r.status_code == 422 and "Kadiogo : au moins 2000 enseignants" in r.json()["detail"]


def test_noms_officiels_accentues():
    from dcb.territoire import nom_officiel
    assert [nom_officiel(x) for x in ("SENO", "PLATEAU CENTRAL", "BOUCLE DU MOUHOUN", "Séno")] == \
        ["Séno", "Plateau-Central", "Boucle du Mouhoun", "Séno"]


def test_donnees_d_une_annee_relues_et_recontrolees():
    import io

    from fastapi.testclient import TestClient

    from dcb import entrepot
    from dcb.service import app
    if not entrepot.ENTREPOT.exists():
        pytest.skip("entrepôt non amorcé")
    c = TestClient(app)
    r = c.get("/api/entrepot/donnees/primaire_province/2024-2025")
    assert r.status_code == 200
    t = pd.read_excel(io.BytesIO(r.content), sheet_name="donnees", dtype=object)
    assert entrepot.controler_fichier(t, "primaire_province").accepte
    assert c.post("/api/entrepot/retirer", data={"lot": 1, "auteur": "x"}).status_code == 401


def test_mouvements_apparient_departs_et_arrivees():
    from dcb.optimisation import mouvements
    res = pd.DataFrame({"province": ["A", "B", "C"], "solde_redeploiement": [-5, 3, 2]})
    m = mouvements(res, {"A": (12.0, -1.0), "B": (12.1, -1.0), "C": (13.0, -1.0)})
    assert sum(x["enseignants"] for x in m) == 5 and m[0] == {"de": "A", "vers": "B", "enseignants": 3, "distance_km": 11}


def test_recul_du_prive_augmente_les_eleves_du_public():
    """Le scénario « recul du privé » ajoute au public une part des élèves du privé, surtout là où le privé est fort."""
    from dcb.indicateurs import SORTIE
    from dcb.optimisation import donnees_probleme
    if not (SORTIE / "province_annee.csv").exists():
        pytest.skip("chaîne non exécutée")
    cfg = config()
    t = pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8")
    pv = pd.read_csv(SORTIE / "prevision_effectifs.csv", sep=";", encoding="utf-8")
    a, b = donnees_probleme(t, pv, cfg), donnees_probleme(t, pv, cfg, recul_prive=0.2)
    gain = (b.set_index("province")["eleves_horizon"] - a.set_index("province")["eleves_horizon"])
    assert (gain >= 0).all() and gain.sum() > 0
    assert gain.idxmax() == "KADIOGO"  # 2/3 des élèves dans le privé
    ref = t[(t["annee_scolaire"] == cfg["annee_reference"]) & (t["statut"] == "prive")].set_index("province")["eleves"]
    sans_prive = ref[ref.fillna(0) == 0].index
    assert (gain.reindex(sans_prive).fillna(0) == 0).all()


# --- Assistant IA (sans appel au service d'IA) ---

def _web_pret():
    from dcb.assistant import WEB
    if not (WEB / "provinces.json").exists() or not (SORTIE / "province_annee.csv").exists():
        pytest.skip("chaîne non exécutée")


def test_assistant_outils_lisent_les_chiffres_publies():
    _web_pret()
    from dcb import assistant
    p = assistant.fiche_province("séno")  # accents et casse indifférents
    assert p["province"] == "Séno" and p["calculs_outil"]["rang_priorite_sur_45"] >= 1
    with pytest.raises(ValueError, match="Province inconnue"):
        assistant.fiche_province("Atlantide")
    c = assistant.classement("eleves_par_enseignant", 3)
    assert len(c["provinces"]) == 3 and c["provinces"][0]["valeur"] >= c["provinces"][1]["valeur"]
    plan = assistant.calculer_plan({"enseignants": 500, "salles": 200,
                                    "exigences": [{"niveau": "province", "nom": "Kadiogo", "type": "min_enseignants", "valeur": 50}]})
    assert plan["enseignants_affectes"] <= 500 and plan["_demande"]["provinces"]["KADIOGO"]["min_enseignants"] == 50


def test_assistant_comprend_les_questions_types():
    """Moteur sans IA générative : lieux, nombres et intention reconnus ; chiffres tirés de l'outil."""
    _web_pret()
    from dcb import assistant

    def rep(*questions):
        h = []
        for q in questions:
            h += [{"role": "user", "content": q}, {"role": "assistant", "content": "…"}]
        return assistant.repondre(h[:-1])

    r = rep("Quelles sont les 5 provinces les plus surchargées ?")
    assert r["outils"][0] in ("classement", "donnees") and "5. " in r["reponse"] and "6. " not in r["reponse"] and "Loroum" in r["reponse"]
    r = rep("Que se passe-t-il avec 2 000 enseignants et 800 salles ?")
    assert r["outils"] == ["plan"] and r["plan"]["enseignants"] == 2000 and r["plan"]["salles"] == 800
    r = rep("Que se passe-t-il avec 2 000 enseignants et 800 salles ?", "Et avec 3 000 ?")
    assert r["plan"]["enseignants"] == 3000 and r["plan"]["salles"] == 800
    r = rep("Et si 20 % des élèves du privé passent au public ?")
    assert r["plan"]["recul_prive"] == 20 and "privé" in r["reponse"]
    r = rep("Avec un budget de 20 milliards")
    assert r["plan"]["budget_seul"] is True and r["plan"]["budget_fcfa"] == 20e9
    r = rep("Pourquoi le Soum ne reçoit-il pas de salles ?")
    assert r["outils"] == ["province"] and "rouvrir" in r["reponse"] and "aucune salle" in r["reponse"]
    assert "Kadiogo" in rep("Kadiogoo")["reponse"]  # faute de frappe
    assert rep("Que veut dire classement à confirmer ?")["outils"] == ["definition"]
    assert rep("La commune de Djibo")["outils"] == ["commune"]
    assert rep("Quel temps fait-il ?")["outils"] == ["aide"]


def test_assistant_se_coupe_par_la_configuration(monkeypatch):
    from fastapi.testclient import TestClient

    from dcb import assistant
    from dcb.service import app
    monkeypatch.setattr(assistant, "reglages", lambda: {"actif": False})
    c = TestClient(app)
    assert c.get("/api/assistant").json() == {"disponible": False}
    r = c.post("/api/assistant", json={"messages": [{"role": "user", "content": "Bonjour"}]})
    assert r.status_code == 503 and "pas activé" in r.json()["detail"]


def test_assistant_banque_de_questions():
    """Banque de questions réalistes (tests/questions_assistant.py) : au moins 90 % de bonnes réponses."""
    _web_pret()
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from questions_assistant import Q

    from dcb import assistant
    bons = 0
    for prev, q, sujets, mots in Q:
        h = ([{"role": "user", "content": prev}, {"role": "assistant", "content": "…"}] if prev else []) + [{"role": "user", "content": q}]
        r = assistant.repondre(h)
        texte = r["reponse"].replace(" ", " ").lower()
        bons += r["outils"][0] in sujets and all(m.lower() in texte for m in mots)
    assert bons >= 0.9 * len(Q), f"{bons}/{len(Q)}"
