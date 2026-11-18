"""Génère la documentation (15 pages au plus) à partir des sorties de la chaîne.

Tous les chiffres du texte sont lus dans les tables produites par la chaîne : le document ne peut pas
contredire les résultats. Le HTML est écrit dans docs/documentation.html, puis converti en PDF par un
navigateur Chromium (Edge ou Chrome) en mode sans interface, s'il est présent.

Usage : PYTHONPATH=src python -m dcb.documentation   (après dcb.pipeline)
"""
from __future__ import annotations

import base64
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pandas as pd

from dcb.indicateurs import SORTIE as TRAITE
from dcb.indicateurs import config
from dcb.indice import indice_besoin
from dcb.lecture import RACINE
from dcb.tableau_de_bord import LARGEUR, tracer_provinces

DOCS = RACINE / "docs"
TDB = RACINE / "outputs" / "tableau_de_bord" / "tableau_de_bord.html"
RAMPE = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
BLEU, ORANGE, GRIS, ENCRE, MUET, GRILLE = "#2a78d6", "#eb6834", "#c3c2b7", "#0b0b0b", "#898781", "#e1e0d9"
NAVIGATEURS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
]


def _lire(nom: str) -> pd.DataFrame:
    return pd.read_csv(TRAITE / nom, sep=";", encoding="utf-8")


def nb(x, d: int = 0) -> str:
    """Nombre à la française : espace insécable fine pour les milliers, virgule décimale."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{x:,.{d}f}".replace(",", "\u202f").replace(".", ",")
    return s


def joli(nom: str) -> str:
    from dcb.territoire import nom_officiel
    return nom_officiel(nom)


# ---------------------------------------------------------------- figures (SVG)
def fig_carte(valeurs: dict[str, float], titre: str, d: int = 0) -> str:
    provinces, _, hauteur = tracer_provinces()
    v = sorted(x for x in valeurs.values() if x is not None and not math.isnan(x))
    seuils = sorted({v[min(len(v) - 1, int(p * len(v)))] for p in (0.2, 0.4, 0.6, 0.8)})
    debut = len(RAMPE) - 1 - len(seuils)
    corps = ""
    for p in provinces:
        x = valeurs.get(p["nom"])
        if x is None or math.isnan(x):
            c = "#e9e8e3"
        else:
            c = RAMPE[debut + sum(x >= s for s in seuils)]
        corps += f'<path d="{p["d"]}" fill="{c}" stroke="#fff" stroke-width="1.2"/>'
    bornes = [None, *seuils, None]
    leg = ""
    for i in range(len(seuils) + 1):
        a, b = bornes[i], bornes[i + 1]
        t = f"moins de {nb(b, d)}" if a is None else f"{nb(a, d)} et plus" if b is None else f"{nb(a, d)} à {nb(b, d)}"
        leg += f'<span><i style="background:{RAMPE[debut + i]}"></i>{t}</span>'
    return (f'<figure><svg viewBox="0 0 {LARGEUR} {hauteur}" role="img" aria-label="{titre}">{corps}</svg>'
            f'<div class="legende">{leg}</div><figcaption>{titre}</figcaption></figure>')


def fig_barres(lignes: list[tuple[str, float]], norme: float, titre: str, coupure: int | None = None) -> str:
    """Barres horizontales triées ; `coupure` insère une séparation entre les premières et les dernières."""
    h, g, d_ = 17, 92, 40
    largeur = 350
    maxi = max(max(x for _, x in lignes), norme) * 1.03
    X = lambda x: g + x / maxi * (largeur - g - d_)  # noqa: E731
    y, corps, etiquettes = 4, "", ""
    for i, (nom, x) in enumerate(lignes):
        if coupure is not None and i == coupure:
            corps += f'<text x="{g}" y="{y + 11}" font-size="11" fill="{MUET}">…</text>'
            y += h
        corps += (f'<text x="{g - 6}" y="{y + 11}" font-size="11" text-anchor="end" fill="{ENCRE}">{nom}</text>'
                  f'<path d="M{g},{y + 2}h{X(x) - g - 3:.1f}a3,3 0 0 1 3,3v6a3,3 0 0 1 -3,3h-{X(x) - g - 3:.1f}z" fill="{BLEU}"/>')
        # valeur écrite après le trait de norme, avec un liseré blanc, pour rester lisible quand elle le croise
        etiquettes += (f'<text x="{X(x) + 5:.1f}" y="{y + 11}" font-size="11" fill="{ENCRE}" stroke="#fff" stroke-width="3" '
                       f'paint-order="stroke">{nb(x, 1)}</text>')
        y += h
    corps += (f'<line x1="{X(norme):.1f}" x2="{X(norme):.1f}" y1="0" y2="{y}" stroke="{ENCRE}" stroke-width="1.5"/>'
              f'<text x="{X(norme):.1f}" y="{y + 12}" font-size="10.5" text-anchor="middle" fill="{ENCRE}">norme : {nb(norme)}</text>')
    corps += etiquettes
    return f'<figure><svg viewBox="0 0 {largeur} {y + 16}" role="img" aria-label="{titre}">{corps}</svg><figcaption>{titre}</figcaption></figure>'


def fig_serie(obs: pd.Series, central: pd.Series, reouv: pd.Series, titre: str) -> str:
    """Série nationale observée (index = année de début) et deux scénarios."""
    L, H, g, d_, hh, b = 720, 250, 58, 132, 10, 26
    x0, x1 = int(obs.index.min()), int(central.index.max())
    ymax = max(obs.max(), central.max(), reouv.max()) * 1.06
    X = lambda a: g + (a - x0) / (x1 - x0) * (L - g - d_)  # noqa: E731
    Y = lambda v: H - b - v / ymax * (H - hh - b)  # noqa: E731
    chemin = lambda s: "M" + "L".join(f"{X(a):.1f},{Y(v):.1f}" for a, v in s.items())  # noqa: E731
    corps = ""
    pas = 500_000
    for v in range(0, int(ymax) + 1, pas):
        corps += (f'<line x1="{g}" x2="{L - d_}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{GRILLE}"/>'
                  f'<text x="{g - 6}" y="{Y(v) + 4:.1f}" font-size="11" text-anchor="end" fill="{MUET}">{nb(v / 1e6, 1)} M</text>')
    for a in range(x0, x1 + 1):
        if ((a - x0) % 4 == 0 and x1 - a >= 3) or a == x1:
            corps += f'<text x="{X(a):.1f}" y="{H - 8}" font-size="11" text-anchor="middle" fill="{MUET}">{a}-{str(a + 1)[2:]}</text>'
    dernier = obs.index.max()
    c2 = pd.concat([obs.loc[[dernier]], central])
    r2 = pd.concat([obs.loc[[dernier]], reouv])
    creux = obs.loc[2018:].idxmin()
    corps += (f'<path d="{chemin(obs)}" fill="none" stroke="{BLEU}" stroke-width="2"/>'
              f'<path d="{chemin(c2)}" fill="none" stroke="{BLEU}" stroke-width="2" stroke-dasharray="5 4"/>'
              f'<path d="{chemin(r2)}" fill="none" stroke="{ORANGE}" stroke-width="2" stroke-dasharray="5 4"/>'
              f'<circle cx="{X(dernier):.1f}" cy="{Y(obs[dernier]):.1f}" r="4" fill="{BLEU}" stroke="#fff" stroke-width="2"/>'
              f'<text x="{X(x1) + 6:.1f}" y="{Y(reouv.iloc[-1]) - 2:.1f}" font-size="11" fill="{ENCRE}">Réouverture : {nb(reouv.iloc[-1] / 1e6, 2)} M</text>'
              f'<text x="{X(x1) + 6:.1f}" y="{Y(central.iloc[-1]) + 12:.1f}" font-size="11" fill="{ENCRE}">Central : {nb(central.iloc[-1] / 1e6, 2)} M</text>'
              f'<text x="{X(creux):.1f}" y="{Y(obs[creux]) + 16:.1f}" font-size="11" text-anchor="middle" fill="{ENCRE}">{creux}-{str(creux + 1)[2:]} : {nb(obs[creux] / 1e6, 2)} M</text>')
    leg = (f'<span><i class="trait" style="border-color:{BLEU}"></i>Observé</span>'
           f'<span><i class="trait" style="border-color:{BLEU};border-top-style:dashed"></i>Scénario central</span>'
           f'<span><i class="trait" style="border-color:{ORANGE};border-top-style:dashed"></i>Réouverture des écoles</span>')
    return f'<figure><svg viewBox="0 0 {L} {H}" role="img" aria-label="{titre}">{corps}</svg><div class="legende">{leg}</div><figcaption>{titre}</figcaption></figure>'


def fig_points(lignes: list[tuple[str, float, float, float]], norme: float, titre: str) -> str:
    """Pour chaque province : ratio sans moyens (gris), proportionnelle (orange), optimisée (bleu)."""
    h, g, d_, largeur = 17, 118, 20, 520
    tous = [x for l in lignes for x in l[1:]] + [norme]
    mini, maxi = min(tous) - 3, max(tous) + 3
    X = lambda x: g + (x - mini) / (maxi - mini) * (largeur - g - d_)  # noqa: E731
    y, corps = 16, ""
    for v in range(int(math.ceil(mini / 10) * 10), int(maxi) + 1, 10):
        corps += (f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="14" y2="{16 + h * len(lignes)}" stroke="{GRILLE}"/>'
                  f'<text x="{X(v):.1f}" y="10" font-size="10.5" text-anchor="middle" fill="{MUET}">{v}</text>')
    corps += f'<line x1="{X(norme):.1f}" x2="{X(norme):.1f}" y1="14" y2="{16 + h * len(lignes)}" stroke="{ENCRE}" stroke-width="1.5"/>'
    for nom, r0, rp, ro in lignes:
        cy = y + 8
        corps += (f'<text x="{g - 6}" y="{y + 12}" font-size="11" text-anchor="end" fill="{ENCRE}">{nom}</text>'
                  f'<line x1="{X(min(r0, ro)):.1f}" x2="{X(max(r0, ro)):.1f}" y1="{cy}" y2="{cy}" stroke="{GRIS}" stroke-width="2"/>'
                  f'<circle cx="{X(r0):.1f}" cy="{cy}" r="4.5" fill="{GRIS}" stroke="#fff" stroke-width="1.5"/>'
                  f'<circle cx="{X(rp):.1f}" cy="{cy}" r="4.5" fill="{ORANGE}" stroke="#fff" stroke-width="1.5"/>'
                  f'<circle cx="{X(ro):.1f}" cy="{cy}" r="4.5" fill="{BLEU}" stroke="#fff" stroke-width="1.5"/>')
        y += h
    leg = (f'<span><i style="background:{BLEU}"></i>Optimisée</span><span><i style="background:{ORANGE}"></i>Proportionnelle</span>'
           f'<span><i style="background:{GRIS}"></i>Sans moyens nouveaux</span><span>Trait vertical : norme de {nb(norme)}</span>')
    return f'<figure><svg viewBox="0 0 {largeur} {y + 4}" role="img" aria-label="{titre}">{corps}</svg><div class="legende">{leg}</div><figcaption>{titre}</figcaption></figure>'


def table(entetes: list[str], lignes: list[list[str]], gauche: int = 1) -> str:
    th = "".join(f'<th class="{"g" if i < gauche else ""}">{e}</th>' for i, e in enumerate(entetes))
    tr = "".join("<tr>" + "".join(f'<td class="{"g" if i < gauche else ""}">{c}</td>' for i, c in enumerate(l)) + "</tr>" for l in lignes)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def navigateur() -> str | None:
    for n in NAVIGATEURS:
        if Path(n).exists():
            return n
    return shutil.which("msedge") or shutil.which("chromium") or shutil.which("google-chrome")


def _attendre_fichier(chemin: Path, delai: float = 60) -> bool:
    """Sous Windows, le navigateur peut rendre la main avant d'avoir fini d'écrire : attendre une taille stable."""
    fin, taille = time.time() + delai, -1
    while time.time() < fin:
        if chemin.exists() and chemin.stat().st_size > 0 and chemin.stat().st_size == taille:
            return True
        taille = chemin.stat().st_size if chemin.exists() else -1
        time.sleep(1)
    return chemin.exists() and chemin.stat().st_size > 0


def capture(vue: str, hauteur: int) -> str:
    """Capture d'une vue du tableau de bord, renvoyée sous forme d'image incorporée (vide si pas de navigateur)."""
    nav = navigateur()
    if not nav or not TDB.exists():
        return ""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        png = Path(tmp) / "vue.png"
        subprocess.run([nav, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={tmp}/profil",
                        "--window-size=1320," + str(hauteur), f"--screenshot={png}", TDB.as_uri() + f"#vue={vue}"],
                       check=False, capture_output=True, timeout=120)
        if not _attendre_fichier(png):
            print(f"ATTENTION : capture de la vue « {vue} » impossible, figure omise")
            return ""
        return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()


def capture_site(vue: str, hauteur: int, largeur: int = 1360, attente_s: float = 12) -> str:
    """Capture d'une vue de l'application en ligne (vide si pas de navigateur ou de réseau).

    La carte (MapLibre) se dessine en WebGL après le chargement de la page : le navigateur est piloté par son
    protocole de débogage pour attendre réellement la fin du rendu (rendu logiciel SwiftShader, sans carte graphique)."""
    import asyncio
    import json
    import urllib.request

    nav, adresse = navigateur(), config()["service"].get("adresse_publique")
    if not nav or not adresse:
        return ""
    try:
        import websockets
    except ImportError:
        print("ATTENTION : module websockets absent, captures du site omises")
        return ""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        proc = subprocess.Popen([nav, "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                 "--hide-scrollbars", "--remote-debugging-port=0", f"--user-data-dir={tmp}/profil",
                                 f"--window-size={largeur},{hauteur}", f"{adresse}/?sans-visite#{vue}"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port_f = Path(tmp) / "profil" / "DevToolsActivePort"
            fin = time.time() + 30
            while not port_f.exists() and time.time() < fin:
                time.sleep(0.3)
            port = port_f.read_text().split()[0]
            pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())
            ws_url = next(p_["webSocketDebuggerUrl"] for p_ in pages if p_.get("type") == "page")

            async def prendre() -> str:
                async with websockets.connect(ws_url, max_size=50 * 2 ** 20) as ws:
                    await asyncio.sleep(attente_s)
                    await ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
                    while True:
                        m = json.loads(await ws.recv())
                        if m.get("id") == 1:
                            return m["result"]["data"]

            return "data:image/png;base64," + asyncio.run(prendre())
        except Exception as e:  # réseau, navigateur : la figure est omise, le document reste produit
            print(f"ATTENTION : capture de la vue en ligne « {vue} » impossible ({e}), figure omise")
            return ""
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _redeploiement(cfg: dict, t: pd.DataFrame) -> dict:
    """Redéployer avant de recruter : 1 000 recrues + redéploiement, contre des recrues seules, mêmes salles."""
    from dcb.optimisation import donnees_probleme, evaluer, optimiser
    pv = _lire("prevision_effectifs.csv")
    d = donnees_probleme(t, pv, cfg)
    m, n0 = cfg["optimisation"]["salles_a_construire"], 1000
    avec, _ = optimiser(d, cfg, n0, m, redeploiement=10 ** 5)
    r = int(avec["redeployes_sortants"].sum())
    seules, _ = optimiser(d, cfg, n0 + r, m)
    sans, _ = optimiser(d, cfg, n0, m)
    e_avec, e_seules, e_sans = evaluer(avec, cfg), evaluer(seules, cfg), evaluer(sans, cfg)
    return {"recrues": n0, "redeployes": r, "provinces_source": int((avec["redeployes_sortants"] > 0).sum()),
            "surnombre_sans": e_sans["eleves_au_dela_norme_maitre"], "surnombre_avec": e_avec["eleves_au_dela_norme_maitre"],
            "surnombre_recrues": e_seules["eleves_au_dela_norme_maitre"],
            "economie": r * cfg["optimisation"]["cout_enseignant_fcfa"]}


def _ecoles_presumees(cfg: dict, t: pd.DataFrame) -> tuple[int, int]:
    """Écoles de l'annuaire absentes d'OSM, et combien ont été placées (le placement s'arrête quand plus aucun
    enfant n'est éloigné)."""
    from dcb import territoire
    from dcb.carte_scolaire import SITES
    f = RACINE / "data" / "interim" / "ecoles_presumees.csv"
    if not f.exists() or not SITES.exists():
        return 0, 0
    sites = pd.read_csv(SITES, sep=";", encoding="utf-8")
    anc = territoire.charger().decoupage("annuaires_2017_2025").set_index("pcode_commune")["province"]
    off = t[(t["annee_scolaire"] == cfg["annee_reference"]) & (t["statut"] == "total")].set_index("province")["ecoles"]
    osm = sites["pcode_commune"].map(anc).value_counts()
    manque = int((off - osm.reindex(off.index).fillna(0)).clip(lower=0).sum())
    return manque, len(pd.read_csv(f, sep=";", encoding="utf-8"))


# ---------------------------------------------------------------- faits chiffrés
def faits() -> dict:
    cfg = config()
    ref, hor, cible = cfg["annee_reference"], cfg["annee_horizon"], cfg["statut_cible"]
    nm, ns = cfg["normes"]["eleves_par_maitre"], cfg["normes"]["eleves_par_salle"]
    t = _lire("province_annee.csv")
    f: dict = {"cfg": cfg, "ref": ref, "hor": hor, "nm": nm, "ns": ns}
    an = t[t["annee_scolaire"] == ref]
    for s in ("public", "prive", "total"):
        g = an[an["statut"] == s]
        f[s] = {k: g[k].sum() for k in ("ecoles", "salles", "maitres", "eleves")}
    c = an[an["statut"] == cible].set_index("province")
    f["c"] = c
    f["ratio_m"], f["ratio_s"] = c["eleves"].sum() / c["maitres"].sum(), c["eleves"].sum() / c["salles"].sum()
    f["au_dessus"] = int((c["eleves_par_maitre"] > nm).sum())
    tri = c["eleves_par_maitre"].sort_values(ascending=False)
    f["tri"] = tri
    f["precaires"], f["mauvais"] = c["murs_paille_banco"].sum(), c["murs_mauvais_etat"].sum()
    f["sous_moitie_pic"] = sorted(c.index[c["part_du_pic"] < 0.5])
    f["manquants_ref"] = (c["maitres_manquants"].sum(), c["salles_manquantes"].sum())
    nat = t[t["statut"] == "total"].groupby("annee_scolaire")[["eleves", "maitres", "salles", "ecoles"]].sum()
    f["nat"] = nat
    ind, bilan = indice_besoin(t, cfg)
    f["indice"], f["robustesse"] = ind, bilan
    s = _lire("serie_effectifs_province.csv")
    s["debut"] = s["annee_scolaire"].str[:4].astype(int)
    f["serie_nat"] = s.groupby("debut")["eleves"].sum()
    f["serie_nb_annees"] = s["debut"].nunique()
    pv = _lire("prevision_effectifs.csv")
    pv["debut"] = pv["annee_scolaire"].str[:4].astype(int)
    f["prev_nat"] = {sc: g.groupby("debut")["eleves_prevus"].sum() for sc, g in pv.groupby("scenario")}
    f["groupes"] = pv.drop_duplicates("province")["groupe"].value_counts().to_dict()
    grp = pv.drop_duplicates("province").set_index("province")["groupe"]
    tot = an[an["statut"] == "total"].set_index("province")["eleves"]
    f["part_eleves_stables"] = tot[grp.reindex(tot.index) == "stable"].sum() / tot.sum()
    fi = _lire("prevision_fiabilite.csv")
    f["fiab"] = fi[fi["perimetre"] == "cas_communs"]
    f["retenue"] = {g: d.loc[d["retenue"], "methode"].iloc[0] for g, d in f["fiab"][f["fiab"]["groupe"] != "ensemble"].groupby("groupe")}
    al = _lire("allocation.csv")
    f["alloc"] = al
    f["bilan"] = _lire("allocation_bilan.csv").set_index("methode")
    sb = _lire("scenarios_bilan.csv")
    f["scen"] = sb
    # besoins à l'horizon, par hypothèse de demande
    sa = _lire("scenarios_allocation.csv")
    f["besoins"] = {}
    for dem, g in sa[sa["methode"] == "optimisee"].drop_duplicates(["demande", "province"]).groupby("demande"):
        e = g["eleves_horizon"]
        f["besoins"][dem] = {"eleves": e.sum(), "maitres": (((e / nm).apply(math.ceil) - g["maitres"]).clip(lower=0)).sum(),
                             "salles": (((e / ns).apply(math.ceil) - g["salles"]).clip(lower=0)).sum()}
    r = pd.read_csv(RACINE / "outputs" / "controles" / "rapprochement_annuaires_principal.csv", sep=";")
    f["rappro"] = (int((r["ecart"] == 0).sum()), len(r), r[r["ecart"] != 0])
    f["retro"] = _lire("retrospectif_bilan.csv")
    f["redep"] = _redeploiement(cfg, t)
    f["presumees"] = _ecoles_presumees(cfg, t)
    from dcb.lecture import nombre_de_tests
    f["nb_tests"] = nombre_de_tests()
    return f


# ---------------------------------------------------------------- document
CSS = """
@page { size: A4; margin: 16mm 17mm 17mm 17mm;
  @bottom-left { content: "Yennenga · Documentation de la solution · Défi 3"; font: 7.5pt "Segoe UI", sans-serif; color: #7b827d; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 7.5pt "Segoe UI", sans-serif; color: #7b827d; } }
@page :first { margin: 0; @bottom-left { content: none; } @bottom-right { content: none; } }
* { box-sizing: border-box; }
body { font: 10.3pt/1.42 "Segoe UI", system-ui, -apple-system, Arial, sans-serif; color: #0b0b0b; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 4pt; line-height: 1.2; }
h2 { font-size: 13.5pt; margin: 16pt 0 5pt; padding-top: 5pt; border-top: 2px solid #1f5c4a; color: #16422f; break-after: avoid; }
h2.saut { break-before: page; margin-top: 0; }
h3 { font-size: 10.8pt; margin: 9pt 0 3pt; break-after: avoid; }
p { margin: 0 0 6pt; } ul, ol { margin: 0 0 6pt; padding-left: 16pt; } li { margin: 1.5pt 0; }
.chapeau { font-size: 11pt; color: #52514e; margin-bottom: 8pt; }
.cles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7pt; margin: 8pt 0 10pt; }
.cle { border: 1px solid #c3c2b7; border-radius: 5pt; padding: 6pt 8pt; }
.cle b { display: block; font-size: 15pt; line-height: 1.15; color: #1f5c4a; } .cle span { font-size: 8.8pt; color: #52514e; }
table { border-collapse: collapse; width: 100%; font-size: 9.2pt; margin: 4pt 0 8pt; break-inside: auto; } thead { display: table-header-group; } tr { break-inside: avoid; }
th, td { padding: 2.2pt 5pt; border-bottom: 1px solid #e1e0d9; text-align: right; font-variant-numeric: tabular-nums; vertical-align: top; }
th { color: #52514e; font-weight: 600; border-bottom: 1px solid #898781; }
th.g, td.g { text-align: left; }
figure { margin: 6pt 0 8pt; break-inside: avoid; } figure svg, figure img { display: block; width: 100%; height: auto; }
figure img { border: 1px solid #e1e0d9; border-radius: 4pt; max-height: 115mm; width: auto; max-width: 100%; margin: 0 auto; }
figcaption { font-size: 8.8pt; color: #52514e; margin-top: 3pt; }
.legende { display: flex; gap: 10pt; flex-wrap: wrap; font-size: 8.8pt; color: #52514e; margin-top: 3pt; }
.legende i { display: inline-block; width: 9pt; height: 9pt; border-radius: 2pt; margin-right: 3pt; vertical-align: -1pt; }
.legende .trait { width: 14pt; height: 0; border-top: 2px solid; border-radius: 0; vertical-align: 3pt; }
.deux { display: grid; grid-template-columns: 1fr 1fr; gap: 12pt; align-items: start; }
.encadre { border-left: 3px solid #e0a82e; background: #f6f4ec; padding: 6pt 9pt; margin: 6pt 0 8pt; break-inside: avoid; }
.petit { font-size: 9pt; color: #52514e; }
code { font-family: Consolas, monospace; font-size: 9.2pt; }
pre { background: #f4f4f1; padding: 6pt 8pt; border-radius: 4pt; font: 9pt/1.35 Consolas, monospace; margin: 4pt 0 8pt; white-space: pre-wrap; }
.saut { break-before: page; }
.garde { height: 296mm; display: flex; flex-direction: column; overflow: hidden; break-after: page; }
.garde-haut { background: #1f5c4a; color: #fff; padding: 30mm 22mm 16mm; flex: 0 0 auto; }
.garde-sur { font-size: 10pt; letter-spacing: .06em; text-transform: uppercase; color: #f2c14e; margin: 14pt 0 6pt; font-weight: 600; }
.garde-titre { font-size: 44pt; margin: 0; line-height: 1.05; color: #fff; }
.garde-filet { width: 70mm; height: 3pt; background: #f2c14e; border-radius: 2pt; margin: 9pt 0 12pt; }
.garde-sous { font-size: 15pt; line-height: 1.3; margin: 0 0 6pt; color: #fff; font-weight: 600; }
.garde-texte { font-size: 11pt; color: #d9e6df; margin: 0 0 12pt; }
.garde-lien { font-size: 10.5pt; margin: 0; color: #fff; } .garde-lien a { color: #f2c14e; text-decoration: none; font-weight: 600; }
.garde-bas { background: #f7f5ef; padding: 12mm 22mm 10mm; flex: 1 1 auto; display: flex; flex-direction: column; }
.sommaire h2 { border: 0; margin: 0 0 6pt; padding: 0; font-size: 12pt; }
.sommaire ol { list-style: none; padding: 0; margin: 0; }
.sommaire li { display: flex; align-items: baseline; gap: 6pt; margin: 0; padding: 4.5pt 0; border-bottom: 1px solid #e1ded2; font-size: 11pt; }
.sommaire li a { color: #0b0b0b; text-decoration: none; } .sommaire li::after { content: ""; flex: 1; order: 1; }
.sommaire li span { order: 2; color: #1f5c4a; font-weight: 600; font-variant-numeric: tabular-nums; }
.garde-pied { margin-top: auto; font-size: 9pt; color: #52514e; padding-top: 8pt; }
.glossaire td:first-child { font-weight: 600; white-space: nowrap; }
.glossaire td { font-size: 8.8pt; }
"""

SOMMAIRE = [("s1", "1. Yennenga en une page"), ("s2", "2. Les données"), ("s3", "3. La préparation des données"),
            ("s4", "4. La méthode"), ("s5", "5. Les résultats"), ("s6", "6. L'outil : usage, coût et mise en place"),
            ("s7", "7. Reproduire les résultats"), ("s8", "8. Glossaire")]

GLOSSAIRE = [
    ("Élèves par maître", "Élèves du public divisés par le nombre de maîtres chargés de cours. Norme nationale : 50."),
    ("Élèves en surnombre", "Élèves au-delà de ce que la norme permet avec les maîtres en place : un élève de trop dans une classe surchargée."),
    ("Indice de besoin", "Classement des provinces qui combine la surcharge des classes et l'état des salles ; sa solidité est testée en faisant varier les poids."),
    ("Salle précaire", "Salle aux murs en paille ou en banco (terre crue)."),
    ("Province en choc / stable", "En choc : effectif tombé de plus de 20 % d'une année sur l'autre depuis 2019 (insécurité, fermetures). Stable : les autres."),
    ("Prévision de référence", "Effectif supposé inchangé. Une méthode n'est retenue que si elle fait mieux qu'elle sur le passé."),
    ("Croissance amortie", "Prolonge la croissance récente en la réduisant de moitié chaque année ; retenue pour les provinces stables."),
    ("Marge d'incertitude", "Fourchette dans laquelle sont tombées 8 prévisions sur 10 lors du test sur le passé."),
    ("Répartition proportionnelle", "Règle simple : les moyens partagés au prorata des élèves attendus."),
    ("Au prorata des besoins", "Règle simple : les moyens partagés au prorata des enseignants et salles manquants."),
    ("Répartition optimisée", "Plan calculé par programmation linéaire en nombres entiers : il soulage d'abord les classes les plus chargées, sous les contraintes du décideur."),
    ("Prouvé optimal", "Le solveur (CBC) démontre qu'aucun autre plan ne fait mieux selon le critère retenu."),
    ("Indice de Gini", "Mesure de l'inégalité entre provinces, de 0 (toutes au même ratio) à 1."),
    ("Rouvrir d'abord", "Là où plus de 20 % des écoles ont fermé, on ne construit pas : on envoie les enseignants avec des salles d'écoles fermées à rouvrir."),
    ("Redéploiement", "Mutation d'enseignants en poste depuis une province qui restera à la norme vers une province surchargée."),
    ("Test sur le passé", "Se placer à une date passée avec l'information de l'époque et comparer le plan de l'outil à ce qui s'est réellement passé."),
    ("Lot", "Fichier de données importé dans l'outil, daté et signé ; le retirer rétablit la version précédente."),
    ("Découpage territorial", "Regroupement des communes en provinces et régions : celui des annuaires (13 régions, 45 provinces) et celui de 2025 (17 régions, 47 provinces)."),
    ("Sigles", "DGESS : direction générale des études et des statistiques sectorielles (éducation) ; INSD : institut national de la statistique ; ESU : éducation en situation d'urgence ; COD-AB : limites administratives de référence (OCHA) ; OSM : OpenStreetMap ; PDI : personnes déplacées internes."),
]

NOMS_METHODES = {"naive": "Référence : effectif inchangé", "tendance_lineaire": "Tendance linéaire",
                 "croissance_amortie": "Croissance amortie", "demographique": "Population de 6 à 11 ans projetée (INSD)"}


def _table_fiabilite(f: dict, groupe: str) -> str:
    d = f["fiab"][f["fiab"]["groupe"] == groupe]
    p = d.pivot(index="methode", columns="horizon", values="wape")
    lignes = []
    for m in ("naive", "tendance_lineaire", "croissance_amortie", "demographique"):
        nom = NOMS_METHODES[m] + (" — <b>retenue</b>" if f["retenue"][groupe] == m else "")
        lignes.append([nom, *[nb(100 * x, 1) for x in p.loc[m]]])
    return table(["Méthode", *[f"{h} an{'s' if h > 1 else ''}" for h in p.columns]], lignes)


def html(f: dict, pages: dict | None = None) -> str:
    cfg, ref, hor, nm, ns = f["cfg"], f["ref"], f["hor"], f["nm"], f["ns"]
    opt = cfg["optimisation"]
    c, tri, B = f["c"], f["tri"], f["bilan"]
    pub, tot = f["public"], f["total"]
    o, p, r, bb = B.loc["optimisee"], B.loc["proportionnelle"], B.loc["sans_moyens_nouveaux"], B.loc["besoins"]
    gain = 1 - o["eleves_au_dela_norme_maitre"] / p["eleves_au_dela_norme_maitre"]
    # la province la plus chargée avant le plan et ce qu'elle devient selon chaque façon de répartir
    alloc = _lire("allocation.csv").assign(avant=lambda x: x["eleves_horizon"] / x["maitres"].where(x["maitres"] > 0))
    p_pire = alloc[alloc["methode"] == "optimisee"].sort_values("avant").iloc[-1]["province"]
    pire_apres = alloc[alloc["province"] == p_pire].set_index("methode")["ratio_maitre_apres"]
    cout_md = (o["salles_attribuees"] * opt["cout_salle_fcfa"] + o["enseignants_attribues"] * opt["cout_enseignant_fcfa"] * opt.get("annees_budget", 1)) / 1e9
    bes = f["besoins"]["tendance"]
    besr = f["besoins"]["reouverture"]
    N, M = opt["enseignants_a_repartir"], opt["salles_a_construire"]
    nat = f["nat"]
    creux = nat["eleves"].idxmin()
    ident, total_cmp, ecarts = f["rappro"]
    rob = f["robustesse"]
    ind = f["indice"]
    stable, choc = f["groupes"].get("stable", 0), f["groupes"].get("choc", 0)
    fs = f["fiab"][(f["fiab"]["groupe"] == "stable")].pivot(index="methode", columns="horizon", values="wape")
    fc = f["fiab"][(f["fiab"]["groupe"] == "choc")].pivot(index="methode", columns="horizon", values="wape")
    hmax = int(fs.columns.max())

    # figures
    carte = fig_carte(c["eleves_par_maitre"].where(c["maitres"] > 0).to_dict(),
                      f"Figure 1 — Élèves par maître, primaire public, {ref}. Norme nationale : {nm}.", 1)
    tete, queue = tri.head(12), tri.tail(5)
    barres = fig_barres([(joli(k), v) for k, v in pd.concat([tete, queue]).items()], nm,
                        f"Figure 2 — Les 12 provinces les plus chargées et les 5 moins chargées (élèves par maître, public, {ref}).", coupure=12)
    serie = fig_serie(f["serie_nat"], f["prev_nat"]["tendance"], f["prev_nat"]["reouverture"],
                      f"Figure 3 — Élèves du primaire (public et privé), {int(f['serie_nat'].index.min())}-{str(int(f['serie_nat'].index.min()) + 1)[2:]} à {hor} : observé et deux scénarios.")
    al = f["alloc"]
    ao = al[al["methode"] == "optimisee"].set_index("province")
    ap = al[al["methode"] == "proportionnelle"].set_index("province")
    a0 = al[al["methode"] == "sans_moyens_nouveaux"].set_index("province")
    ordre = a0["ratio_maitre_apres"].sort_values(ascending=False).head(16).index
    points = fig_points([(joli(k), a0.loc[k, "ratio_maitre_apres"], ap.loc[k, "ratio_maitre_apres"], ao.loc[k, "ratio_maitre_apres"]) for k in ordre],
                        nm, f"Figure 4 — Élèves par maître en {hor} dans les 16 provinces les plus chargées, selon la répartition de {nb(N)} enseignants et {nb(M)} salles.")
    img_rep = capture_site("repartition", 900)
    img_carte = capture_site("carte", 820)
    adresse = cfg["service"].get("adresse_publique", "")
    ro = f["retro"]
    ro_o, ro_r = ro[ro["methode"] == "optimisee"].set_index("origine"), ro[ro["methode"] == "reelle"].set_index("origine")
    t_retro = table(["Période", "Moyens ajoutés (hausses nettes)", "Répartition réelle", "Au prorata des élèves", "Au prorata des besoins", "Optimisée", "Écart avec la réalité"],
                    [[f"{k[:4]}-{k[7:]} → {ro_o.loc[k, 'fin'][:4]}-{ro_o.loc[k, 'fin'][7:]}",
                      f"{nb(ro_o.loc[k, 'enseignants_disponibles'])} enseignants, {nb(ro_o.loc[k, 'salles_disponibles'])} salles",
                      *[nb(ro[(ro["origine"] == k) & (ro["methode"] == m_)]["eleves_au_dela_norme_maitre"].iloc[0]) for m_ in ("reelle", "proportionnelle", "besoins")],
                      f"<b>{nb(ro_o.loc[k, 'eleves_au_dela_norme_maitre'])}</b>", f"<b>−{nb(-100 * ro_o.loc[k, 'ecart_vs_reelle'], 0)} %</b>"]
                     for k in ro_o.index], gauche=2)
    retro0 = ro_o.index[0]
    ro_b = ro[ro["methode"] == "besoins"].set_index("origine")
    gain_b = [1 - ro_o.loc[k, "eleves_au_dela_norme_maitre"] / ro_b.loc[k, "eleves_au_dela_norme_maitre"] for k in ro_o.index]
    rd = f["redep"]
    manque_ec, placees_ec = f["presumees"]
    rouv = ao[ao["salles_rouvertes"] > 0] if "salles_rouvertes" in ao else ao.iloc[0:0]

    # tableaux
    t_nat = table(["Année scolaire", "Écoles", "Salles", "Maîtres", "Élèves", "Élèves par maître"],
                  [[a, nb(x["ecoles"]), nb(x["salles"]), nb(x["maitres"]), nb(x["eleves"]), nb(x["eleves"] / x["maitres"], 1)] for a, x in nat.iterrows()])
    t_ind = table(["Rang", "Province", "Région", "Élèves par maître", "Élèves par salle", "Paille ou banco", "Mauvais état", "Rang selon les poids"],
                  [[str(x["rang"]), joli(x["province"]), joli(x["region"]), nb(x["eleves_par_maitre"], 1), nb(x["eleves_par_salle"], 1),
                    nb(100 * x["part_salles_precaires"], 1) + " %", nb(100 * x["part_salles_mauvais_etat"], 1) + " %",
                    f"{x['rang_p05']}ᵉ à {x['rang_p95']}ᵉ"] for _, x in ind.head(10).iterrows()], gauche=3)
    top_alloc = ao.sort_values(["enseignants_attribues", "salles_attribuees"], ascending=False).head(10)
    t_alloc = table(["Province", f"Élèves {hor}", "Maîtres actuels", "Enseignants attribués", "Salles attribuées", "Élèves par maître après",
                     "Proportionnelle : enseignants", "Proportionnelle : élèves par maître"],
                    [[joli(k), nb(x["eleves_horizon"]), nb(x["maitres"]), f"<b>{nb(x['enseignants_attribues'])}</b>", f"<b>{nb(x['salles_attribuees'])}</b>",
                      nb(x["ratio_maitre_apres"], 1), nb(ap.loc[k, "enseignants_attribues"]), nb(ap.loc[k, "ratio_maitre_apres"], 1)]
                     for k, x in top_alloc.iterrows()])
    sc = f["scen"][(f["scen"]["demande"] == opt["scenario_demande"])]
    piv = sc.pivot_table(index=["enseignants_disponibles", "salles_disponibles"], columns="methode",
                         values=["pire_ratio_eleves_maitre", "gini_ratio_maitre", "enseignants_attribues"])
    choix = [(n_, m_) for n_, m_ in [(1000, 500), (2000, 1000), (3000, 1500), (4000, 2500), (6000, 4000)] if (n_, m_) in piv.index]
    t_scen = table(["Enseignants disponibles", "Salles à construire", "Enseignants utilisés",
                    "Province la plus chargée : proportionnelle", "… besoins", "… optimisée", "Gini : proportionnelle", "… optimisée"],
                   [[nb(n_), nb(m_), nb(piv.loc[(n_, m_), ("enseignants_attribues", "optimisee")]),
                     nb(piv.loc[(n_, m_), ("pire_ratio_eleves_maitre", "proportionnelle")], 0),
                     nb(piv.loc[(n_, m_), ("pire_ratio_eleves_maitre", "besoins")], 0),
                     f"<b>{nb(piv.loc[(n_, m_), ('pire_ratio_eleves_maitre', 'optimisee')], 0)}</b>",
                     nb(piv.loc[(n_, m_), ("gini_ratio_maitre", "proportionnelle")], 3),
                     f"<b>{nb(piv.loc[(n_, m_), ('gini_ratio_maitre', 'optimisee')], 3)}</b>"]
                    for n_, m_ in choix], gauche=0)
    ecart_txt = "; ".join(f"{joli(x['entite'])} {x['annee_scolaire']} : {nb(abs(x['ecart']))} élèves" for _, x in ecarts.iterrows()
                          if x["entite"] != "NATIONAL") or "aucun"
    pp = _lire("post_primaire_region.csv")
    ppa = sorted(pp["annee_scolaire"].unique())
    ppr, ppp = ppa[-1], ppa[0]
    ppc = pp[pp["annee_scolaire"] == ppr].set_index("region")
    ppn, ppn1 = ppc.loc["BURKINA FASO"], pp[pp["annee_scolaire"] == ppp].set_index("region").loc["BURKINA FASO"]
    ppg = ppc.drop("BURKINA FASO")
    cpp = cfg["post_primaire"]
    npp = cpp["norme_eleves_par_classe"]
    au6 = ppg[ppg["eleves_par_classe_6e"] > npp].sort_values("eleves_par_classe_6e", ascending=False)
    pertes = ppg[ppg["signal_perte_etablissements"] == True].sort_values("evolution_etablissements_2019")  # noqa: E712
    sans_place = ppg.sort_values("part_eleves_sans_place", ascending=False).head(3)
    ctrl_pp = pd.read_csv(RACINE / "outputs" / "controles" / "post_primaire_controles.csv", sep=";")
    ctrl_ok = int((ctrl_pp["ok"] == True).sum())  # noqa: E712
    n_ctrl = int(ctrl_pp["ok"].notna().sum())
    ref_places = ctrl_pp.loc[ctrl_pp["controle"].str.contains("référence"), "valeur"].iloc[0]
    imp_places = ctrl_pp.loc[ctrl_pp["controle"].str.contains("imprimés"), "valeur"].iloc[0]
    cor_places = ctrl_pp.loc[ctrl_pp["controle"].str.contains("corrigés"), "valeur"].iloc[0]
    noms_signaux = {"signal_6e_au_dessus_norme": "6ᵉ", "signal_places_manquantes": "places", "signal_perte_etablissements": "établissements"}
    ordre_pp = ppg.sort_values(["nombre_signaux", "eleves_par_classe_6e"], ascending=False)
    t_pp = table(["Région", "Élèves du post-primaire", "Élèves par classe en 6ᵉ", "Élèves par classe, post-primaire", "Sans place assise",
                  "Établissements 2019-20 → " + ppr, "Signaux"],
                 [[joli(k), nb(x["eleves_pp"]), (f"<b>{nb(x['eleves_par_classe_6e'])}</b>" if x["eleves_par_classe_6e"] > npp else nb(x["eleves_par_classe_6e"])),
                   nb(x["eleves_par_classe_pp"]), nb(100 * x["part_eleves_sans_place"], 1) + " %",
                   f"{nb(x['etablissements_2019'])} → {nb(x['etablissements'])} ({'+' if x['evolution_etablissements_2019'] >= 0 else '−'}{nb(abs(100 * x['evolution_etablissements_2019']), 0)} %)",
                   ", ".join(v for k2, v in noms_signaux.items() if x[k2] == True) or "—"]  # noqa: E712
                  for k, x in ordre_pp.iterrows()])
    from dcb.optimisation import paliers as _paliers
    pal = _paliers(opt)
    k15 = sum(1 for mult, _ in pal if mult <= 1.5 + 1e-9)
    ao_tri = ao.sort_values(["enseignants_attribues", "salles_attribuees"], ascending=False)
    tete_ou = ao_tri.head(7)
    part_tete = tete_ou["enseignants_attribues"].sum() / max(ao["enseignants_attribues"].sum(), 1)
    ou_liste = ", ".join(f"{joli(k)} (+{nb(x['enseignants_attribues'])} enseignants, +{nb(x['salles_attribuees'])} salles)" for k, x in tete_ou.iterrows())
    pire_prov = ao["ratio_maitre_apres"].idxmax()
    so = f["scen"][f["scen"]["methode"] == "optimisee"]
    n_optimaux, duree_max = int((so["statut_solveur"] == "Optimal").sum()), float(so["duree_s"].max())
    ml = _lire("prevision_essai_ml.csv")
    mlt = ml[ml["periode"] == "toutes_origines"].pivot(index="methode", columns="horizon", values="wape")
    mlr = ml[ml["periode"] != "toutes_origines"].pivot(index="methode", columns="horizon", values="wape")
    ml_cas = int(ml[(ml["periode"] == "toutes_origines") & (ml["methode"] == "naive")]["cas"].sum())
    ml_h = int(mlt.columns.max())
    ml_periode_recente = str(ml.loc[ml["periode"] != "toutes_origines", "periode"].iloc[0]).split("_")[1]
    ml_retenu = bool(ml.loc[ml["methode"].str.startswith("ml_"), "bat_la_reference"].any())
    bud = _lire("scenarios_budget.csv")
    pb = bud.pivot_table(index="budget_fcfa", columns="methode", values=["enseignants_attribues", "salles_attribuees", "pire_ratio_eleves_maitre", "gini_ratio_maitre"])
    t_budget = table(["Budget", "Enseignants recrutés", "Salles construites", "Province la plus chargée : proportionnelle", "… besoins", "… optimisée", "Gini : optimisée"],
                     [[f"{nb(b / 1e9)} Md FCFA", nb(pb.loc[b, ("enseignants_attribues", "optimisee")]), nb(pb.loc[b, ("salles_attribuees", "optimisee")]),
                       nb(pb.loc[b, ("pire_ratio_eleves_maitre", "proportionnelle")], 0), nb(pb.loc[b, ("pire_ratio_eleves_maitre", "besoins")], 0),
                       f"<b>{nb(pb.loc[b, ('pire_ratio_eleves_maitre', 'optimisee')], 0)}</b>", nb(pb.loc[b, ("gini_ratio_maitre", "optimisee")], 3)]
                      for b in pb.index], gauche=0)
    bud_ok = int((bud.loc[bud["methode"] == "optimisee", "statut_solveur"] == "Optimal").sum())
    sens = _lire("sensibilite.csv")
    LIB_HYP = {"seuil_acces_construction": "Seuil de construction non programmée", "norme_eleves_par_maitre": "Norme d'élèves par maître",
               "paliers": "Forme de la pénalité", "cout_enseignant_budget": "Coût d'un poste (budget seul)"}
    ps = sens.pivot_table(index=["hypothese", "valeur"], columns="methode", sort=False,
                          values=["pire_ratio_eleves_maitre", "gini_ratio_maitre", "enseignants_attribues"])
    t_sens = table(["Hypothèse", "Valeur", "Enseignants utilisés", "Plus chargée : proportionnelle", "… besoins", "… optimisée", "Gini : besoins", "… optimisée"],
                   [[LIB_HYP.get(h, h), v.replace(".", ","), nb(x[("enseignants_attribues", "optimisee")]),
                     nb(x[("pire_ratio_eleves_maitre", "proportionnelle")], 0), nb(x[("pire_ratio_eleves_maitre", "besoins")], 0),
                     nb(x[("pire_ratio_eleves_maitre", "optimisee")], 0), nb(x[("gini_ratio_maitre", "besoins")], 3),
                     nb(x[("gini_ratio_maitre", "optimisee")], 3)] for (h, v), x in ps.iterrows()], gauche=2)
    o_pire_ok = int((ps[("pire_ratio_eleves_maitre", "optimisee")] <= ps[[("pire_ratio_eleves_maitre", "proportionnelle"), ("pire_ratio_eleves_maitre", "besoins")]].min(axis=1) + 1e-9).sum())
    o_gini_ok = ps[("gini_ratio_maitre", "optimisee")] <= ps[[("gini_ratio_maitre", "proportionnelle"), ("gini_ratio_maitre", "besoins")]].min(axis=1) + 1e-9
    gini_exceptions = [f"{LIB_HYP.get(h, h).lower()} : {v}" for (h, v) in ps.index[~o_gini_ok]]
    duree_budget = float(bud.loc[bud["methode"] == "optimisee", "duree_s"].max())
    t_engag = table(["Annoncé dans la note d'intention", "Livré"], [
        ["Tableau de bord interactif : cartes, classement des priorités, simulateur, sans compétence technique", "Oui, et au-delà : application en ligne avec calcul en direct, visite guidée, exports ; plus un tableau de bord autonome sans connexion"],
        ["Primaire", "Oui : 45 provinces, 8 années, besoins en " + hor[:4] + " et répartition"],
        ["Post-primaire", "En partie : diagnostic par région ; pas de répartition chiffrée, faute de données par province"],
        ["Secondaire", "Non : les mêmes tableaux de bord régionaux le permettraient, avec le même module"],
        ["Échelle commune ou école", "Répartition des postes à la province (seule maille où maîtres et salles sont publiés) ; carte scolaire et accès à l'école à la commune ; sites à 1 km"],
        ["Prévision par régression démographique", "Testée, non retenue : moins bonne que la croissance amortie au-delà de deux ans"],
        ["Gradient boosting « si les séries le permettent »", "Testé, non retenu : ne bat pas la référence"],
        ["Marges d'incertitude", "Oui : par province et par horizon"],
        ["Optimisation de N enseignants et M salles sous contraintes de budget, de capacité et d'accessibilité", "Oui, avec en plus trois scénarios où seul le budget contraint"],
        ["Provinces au-dessus du seuil, avant et après", "Oui (communes : voir l'échelle)"],
        ["Écart entre provinces mieux et moins bien dotées", "Oui : province la plus chargée, indice de Gini"],
        ["Élèves en classes conformes", "Approché : part des élèves dans une province à la norme"],
        ["Salles précaires", "Diagnostic seulement : la répartition ne distingue pas le remplacement des salles en paille ou banco"],
        ["Précision de la prévision", "Oui : erreur mesurée sur le passé, méthode par méthode"],
        ["Temps de production d'un plan", f"{nb(duree_max, 1)} s au plus pour un plan à moyens fixés, {nb(duree_budget, 0)} s au plus sous budget"],
        ["En plus de la note", "Test sur le passé ; redéploiement ; règle commune construire ou rouvrir ; mise à jour annuelle et découpage évolutif ; mise en ligne"],
    ], gauche=2)
    cs = _lire("carte_scolaire_commune.csv")
    ac = _lire("acces_ecole_commune.csv")
    sp = _lire("sites_proposes.csv")
    imp = config()["implantation"]
    e_h = cs[f"enfants_6_11_{hor[:4]}"].sum()
    loin_b, loin_h = ac["eloignes_borne_basse"].sum(), ac["eloignes_borne_haute"].sum()
    n_cons = int((sp["recommandation"] == "construire").sum())
    sp_prov = sp.groupby(["province", "recommandation"]).agg(sites=("rang", "size"), enfants=("enfants_rapproches", "sum"),
                                                            fermees=("part_ecoles_fermees_province", "first")).reset_index()
    sp_prov = sp_prov.sort_values("enfants", ascending=False).head(8)
    t_sites = table(["Province (2025)", "Sites", "Enfants rapprochés", "Écoles fermées dans la province", "Recommandation"],
                    [[r.province, nb(r.sites), nb(r.enfants), f"{nb(100 * r.fermees, 0)} %", r.recommandation]
                     for r in sp_prov.itertuples()], gauche=1)
    sortis_o = r["eleves_au_dela_norme_maitre"] - o["eleves_au_dela_norme_maitre"]
    sortis_p = r["eleves_au_dela_norme_maitre"] - p["eleves_au_dela_norme_maitre"]
    gain_argent = sortis_o / sortis_p - 1 if sortis_p else 0
    retro_gain = -100 * ro_o.loc[retro0, "ecart_vs_reelle"]
    fig = lambda src, leg: f'<figure><img src="{src}" alt=""><figcaption>{leg}</figcaption></figure>' if src else ""  # noqa: E731

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Défi 3 — Documentation de la solution</title><style>{CSS}</style></head><body>

<section class="garde">
<div class="garde-haut">
<svg viewBox="0 0 32 32" width="64" height="64"><rect width="32" height="32" rx="7" fill="#f7f5ef"/><path d="M8 22V12l8-4 8 4v10" fill="none" stroke="#1f5c4a" stroke-width="2.6"/><rect x="13" y="16" width="6" height="6" fill="#e0a82e"/></svg>
<p class="garde-sur">Data Challenge Burkina 2026 · Défi 3</p>
<h1 class="garde-titre">Yennenga</h1>
<div class="garde-filet"></div>
<p class="garde-sous">Où affecter les enseignants, où construire ou rouvrir des classes ?</p>
<p class="garde-texte">Un outil d'aide à la décision pour répartir les enseignants et les salles de classe du primaire, province par province, jusqu'à la rentrée {hor[:4]}.</p>
<p class="garde-lien">Application en ligne, sans installation : <a href="{adresse}">{adresse.removeprefix("https://")}</a></p>
</div>
<div class="garde-bas">
<nav class="sommaire"><h2>Sommaire</h2><ol>
{"".join(f'<li><a href="#{a}">{t}</a><span>{(pages or {}).get(a, "")}</span></li>' for a, t in SOMMAIRE)}
</ol></nav>
<p class="garde-pied">Documentation de la solution · équipe Yennenga · novembre 2026. Défi 3 : optimisation de la répartition des infrastructures et du personnel enseignant. Données {ref} ; un tableau de bord autonome, utilisable sans connexion, est aussi déposé.</p>
</div>
</section>

<h2 id="s1">1. Yennenga en une page</h2>
<p>Le pays compte {nb(tot['eleves'])} élèves au primaire en {ref}, dont {nb(pub['eleves'])} dans le public. En moyenne, la dotation du public est proche de la norme nationale de {nm} élèves par enseignant ({nb(f['ratio_m'], 1)}). Mais cette moyenne masque des écarts de un à trois entre provinces : {nb(tri.iloc[0], 0)} élèves par maître dans le {joli(tri.index[0])}, {nb(tri.iloc[-1], 0)} dans le {joli(tri.index[-1])}. La question n'est donc pas seulement « combien de moyens ? », mais « où les mettre ? ». <b>Yennenga y répond : avec les moyens de l'année, il calcule où affecter les enseignants et où construire ou rouvrir des classes pour soulager d'abord les élèves les plus mal lotis.</b></p>
<div class="cles">
<div class="cle"><b>{nb(sortis_o)}</b><span>élèves sortis des classes surchargées avec {nb(N)} enseignants et {nb(M)} salles, contre {nb(sortis_p)} en partageant les mêmes moyens selon le nombre d'élèves</span></div>
<div class="cle"><b>+{nb(100 * gain_argent, 0)} %</b><span>pour le même argent : {nb(sortis_o / cout_md, 0)} élèves sortis de la surcharge par milliard de FCFA, contre {nb(sortis_p / cout_md, 0)}</span></div>
<div class="cle"><b>{nb(pire_apres['sans_moyens_nouveaux'], 0)} → {nb(pire_apres['optimisee'], 0)}</b><span>élèves par maître au {joli(p_pire)}, la province la plus chargée, à la rentrée {hor[:4]} (norme : {nm})</span></div>
<div class="cle"><b>−{nb(retro_gain, 0)} %</b><span>d'élèves en surnombre : placé en {retro0[:4]} avec l'information de l'époque, l'outil aurait mieux réparti les moyens que la répartition réellement observée</span></div>
</div>
{table(["", "Ce que l'outil fait", "Pour qui"], [
    ["<b>Comprendre</b>", "Une carte de la région à la commune : surcharge des classes, état des salles, priorités et leur solidité, enfants loin d'une école, filles pour 100 garçons, public et privé, sur huit années.", "Cabinet, DGESS, directions régionales"],
    ["<b>Décider</b>", "Le décideur fixe ses moyens ou son budget et ses exigences (planchers, plafonds, redéploiements) ; le plan optimal par province est calculé en quelques secondes, comparé aux règles simples, exporté en Excel ou imprimé en fiche de décision.", "Ministre, cabinet, finances"],
    ["<b>Vérifier</b>", "Chaque résultat se rejoue : test sur le passé, plan prouvé optimal par le solveur, totaux contrôlés avec les publications, hypothèses modifiables.", "DGESS, partenaires techniques et financiers"],
    ["<b>Mettre à jour</b>", "Chaque année, un technicien dépose l'annuaire dans un gabarit : l'outil le contrôle et recalcule tout. Le découpage de 2025 (17 régions) est déjà intégré.", "Technicien de la DGESS"],
], gauche=3)}
<div class="encadre"><b>Pourquoi Yennenga plutôt qu'un tableau de répartition classique ?</b><ul style="margin:3pt 0 0">
<li><b>Le même argent va là où il compte</b> : les moyens vont d'abord aux provinces les plus chargées, et l'outil choisit entre recruter et construire quand on lui donne un budget.</li>
<li><b>Un enseignant n'est utile qu'avec une salle</b> : là où plus de {nb(100 * cfg['implantation']['seuil_fermeture_rouvrir'], 0)} % des écoles ont fermé, il ne construit pas, il envoie les enseignants avec {nb(rouv['salles_rouvertes'].sum())} salles d'écoles fermées à rouvrir.</li>
<li><b>Il respecte les choix du décideur</b> : exigences par province ou région, redéploiements, scénarios d'effectifs pour les provinces en crise.</li>
<li><b>Il est fait pour le terrain</b> : en ligne sans installation, utilisable sur connexion lente et même hors ligne, sur téléphone ; un assistant répond aux questions en français, sans service payant.</li></ul></div>
<p>Le défi attendait des <b>ratios par province</b>, les <b>besoins à l'horizon 2030</b> et un <b>outil d'aide à l'implantation</b>. Les sections 2 à 5 détaillent les données, la méthode et les résultats ; la section 6 présente l'outil, ce qu'il coûte et sa mise en place.</p>
<p class="petit">Écart par rapport à la note d'intention : la répartition des postes est calculée à l'échelle de la province, parce que les données disponibles ne décrivent enseignants et salles qu'à cette maille (ce repli était prévu dans la note) ; la carte scolaire et l'accès à l'école descendent à la commune. Pour le post-primaire, les publications récentes ne descendent qu'à la région : il fait l'objet d'un diagnostic régional ({ppp} et {ppr}), sans répartition chiffrée (section 5.6).</p>

<h2 id="s2">2. Les données</h2>
<h3>Sources utilisées</h3>
{table(["Source", "Producteur", "Ce qu'on en tire", "Couverture"], [
    ["Fichier principal du challenge (préscolaire et primaire)", "DGESS / MENA", "Élèves par région et sexe, écoles par région et statut : référence pour contrôler les totaux", "13 régions, 2015-2016 à 2024-2025"],
    ["Annuaires statistiques de l'enseignement primaire (8 volumes)", "DGESS", "Écoles, salles, groupes pédagogiques, maîtres chargés de cours, élèves, par province et statut ; nature et état des murs ; historique des effectifs", f"45 provinces, {nat.index[0]} à {ref} ; historique depuis {int(f['serie_nat'].index.min())}-{int(f['serie_nat'].index.min()) + 1}"],
    ["Projections démographiques 2020-2035", "INSD", "Population de 6 à 11 ans par province", "45 provinces, 16 années"],
    ["Limites administratives (COD-AB)", "OCHA", "Contours des provinces ; passage au découpage de 2025", "47 provinces, 17 régions"],
    ["Tableau de bord de l'enseignement primaire 2023-2024", "DGESS", f"Norme nationale de {nm} élèves par enseignant (page 37)", "—"],
    ["Tableaux de bord de l'enseignement post-primaire et secondaire (2 volumes)", "DGESS", f"Élèves, établissements, salles, places assises, élèves par classe, enseignants, équipements ; norme de {npp} élèves par classe (page 47 du volume {ppr})", f"13 régions, {ppp} et {ppr} ; établissements et salles depuis 2019-2020"],
], gauche=4)}
<p>Le fichier principal ne contient ni les enseignants ni les salles de classe du primaire. Ces deux grandeurs, indispensables au défi, viennent des annuaires du Data Pack. Un même tableau de synthèse y figure, à l'identique, dans les huit volumes : c'est lui qui fournit le cœur de l'analyse.</p>
<h3>Échelle et période</h3>
<p>L'unité d'analyse est la <b>province</b> : c'est la seule maille où élèves, maîtres et salles sont disponibles ensemble et sur plusieurs années. Les calculs portent sur les 45 provinces du découpage des annuaires ; une table de correspondance donne pour chacune la ou les provinces et la région du découpage de 2025 (deux provinces, le Soum et la Tapoa, ont été scindées). Les affectations de l'État portant sur le secteur public, la répartition est calculée sur le public ; le privé reste visible dans les tables.</p>
<p>Les effectifs reculent jusqu'en {creux} ({nb(nat.loc[creux, 'eleves'])} élèves, {nb(nat.loc[creux, 'ecoles'])} écoles ouvertes), puis remontent. En {ref}, {len(f['sous_moitie_pic'])} provinces scolarisent encore moins de la moitié de leur maximum historique : {", ".join(joli(x) for x in f['sous_moitie_pic'])}.</p>

<h2 id="s3">3. La préparation des données</h2>
<p>Toutes les opérations sont faites par le code, sans retouche à la main ; elles sont détaillées dans le journal de nettoyage déposé à l'étape 02.</p>
<h3>Contenus sans rapport avec les données</h3>
<p>Les fichiers fournis contiennent des textes qui ne sont pas des données et qui s'adressent à des outils automatiques. Un examen systématique (contenu brut du classeur, styles des cellules, toutes les colonnes des CSV) en a trouvé 18 dans le classeur principal — 3 collés à la suite d'un intitulé d'année dans un en-tête, 15 dans des cellules en police blanche de taille 1 placées sous les tableaux — et 521 dans une colonne des CSV du Data Pack que le guide ne mentionne pas. Aucun n'a été suivi ni recopié. La parade est dans le code de lecture : l'année est extraite des en-têtes par un motif, chaque tableau est borné à ses lignes chiffrées, la colonne parasite est supprimée à la lecture.</p>
<p><b>Pièges de structure</b> : numérotation des annuaires instable (chaque tableau est repéré par son titre), libellés variables des provinces (un référentiel unique), lignes de total et sous-totaux intercalés, cinq écritures de l'année scolaire, nombres à espaces et virgule, cellules fusionnées : tout est traité par des fonctions uniques, testées.</p>
<h3>Contrôles : les totaux tombent-ils juste ?</h3>
{table(["Contrôle", "Résultat"], [
    ["Public + privé = total, pour chaque province, 8 années", "Aucun écart"],
    ["Somme des provinces = total de la région = total national (écoles, salles, groupes, maîtres, élèves), 8 années", "Aucun écart"],
    [f"Annuaires comparés au fichier principal : élèves et écoles, 13 régions et national, 8 années ({total_cmp} comparaisons)", f"{ident} identiques. Écart : {ecart_txt}"],
    ["Historique des effectifs : garçons + filles = total ; dernière année = tableau de synthèse", "Vérifié ; une province illisible dans un volume, reprise des volumes suivants"],
    ["Murs : somme des provinces = région = national ; nombre de salles = tableau de synthèse", "Aucun écart sur les sommes ; salles identiques 7 années sur 8 (écart de 2 % au plus en 2018-2019)"],
    ["Population de 6 à 11 ans : 45 provinces × 16 années", "Complet"],
    [f"Post-primaire : somme des régions = national, garçons + filles = total, valeurs {ppr} moins variation annoncée = valeurs {ppp} ({n_ctrl} contrôles)", f"{ctrl_ok} réussis, aucun écart"],
], gauche=2)}
<h3>Décisions prises sur les données</h3>
<ul>
<li><b>Komandjoari, 2022-2023</b> : absente de l'annuaire alors que les totaux de sa région tombent juste sans elle. Elle est enregistrée avec zéro école ouverte, et non comme valeur manquante.</li>
<li><b>Effectifs révisés</b> : sept provinces ont un effectif 2018-2019 revu à la hausse dans les volumes suivants. Pour la série longue, la publication la plus récente fait foi ; les ratios restent calculés sur les chiffres d'une même publication.</li>
<li><b>Places assises du post-primaire, {ppr}</b> : dans le tableau imprimé, les libellés des quatre régions du Centre sont décalés (la ligne « Centre-Est » porte les chiffres du Centre-Ouest, etc.). Avec les libellés imprimés, les élèves de ces régions varieraient d'au moins {nb(100 * imp_places, 0)} % en un an, contre {nb(100 * ref_places, 0)} % au plus ailleurs ; après correction, de {nb(100 * cor_places, 0)} % au plus. Le commentaire du même document, qui situe le plus fort déficit au Centre-Nord, le confirme. Les libellés sont rétablis par le code.</li>
<li><b>Précarité des salles</b> mesurée par les murs (paille, banco), disponibles huit années ; les toitures ne sont lues que sur six.</li>
</ul>

<h2 id="s4">4. La méthode</h2>
<h3>4.1 Indicateurs et indice de besoin</h3>
<p>Pour chaque province et chaque année : élèves par maître, élèves par salle, part des salles en paille ou banco, part des salles en mauvais état, et effectif rapporté au maximum historique de la province (pour repérer les provinces en crise). L'<b>indice de besoin</b> combine les quatre premiers. Chaque indicateur est converti en rang (de la mieux dotée à la plus en difficulté) ; travailler sur les rangs évite qu'une valeur extrême écrase les autres. Les indicateurs qui disent la même chose sont regroupés, pour ne pas compter double : la <b>surcharge</b> (élèves par maître et par salle, corrélation de rang {nb(rob['correlation_surcharge'], 2)}) et l'<b>état du bâti</b> (salles en paille ou banco, salles en mauvais état, corrélation {nb(rob['correlation_bati'], 2)}). Chaque dimension est la moyenne de ses rangs ; l'indice les pondère ({nb(100 * cfg['indice']['ponderations']['surcharge'] / sum(cfg['indice']['ponderations'].values()))} % pour la surcharge, {nb(100 * cfg['indice']['ponderations']['bati'] / sum(cfg['indice']['ponderations'].values()))} % pour le bâti).</p>
<p>Un classement dépend des poids choisis. Pour savoir ce qui est solide, il est rejoué {nb(cfg['indice']['tirages_robustesse'])} fois avec un poids de la surcharge tiré au hasard entre {nb(100 * cfg['indice']['robustesse']['plage_poids_premiere_dimension'][0])} % et {nb(100 * cfg['indice']['robustesse']['plage_poids_premiere_dimension'][1])} %. Chaque province reçoit une fourchette de rangs, affichée dans l'outil. Son rang est dit sensible si elle change de tiers de priorité (rangs 1 à {rob['taille_tiers']}, {rob['taille_tiers'] + 1} à {2 * rob['taille_tiers']}, au-delà) dans plus de {nb(100 * cfg['indice']['robustesse']['seuil_changement_tiers'])} % des tirages.</p>
<h3>4.2 Prévision des effectifs</h3>
<p>Quatre méthodes simples sont mises en concurrence : effectif inchangé (la référence), tendance linéaire, croissance récente amortie de moitié chaque année, et population de 6 à 11 ans projetée par l'INSD à taux de scolarisation constant. Le test consiste à se placer à une année passée, à prévoir les années suivantes et à comparer au réalisé, pour toutes les provinces et toutes les années de départ possibles. <b>Une méthode n'est retenue que si elle fait mieux que la référence.</b> L'erreur est mesurée par la somme des écarts absolus rapportée à la somme des effectifs réalisés.</p>
<p>Les provinces sont évaluées en deux groupes, car elles ne se prévoient pas de la même façon : celles dont l'effectif a chuté de plus de {nb(100 * cfg['prevision']['choc_seuil_baisse'])} % d'une année sur l'autre depuis {cfg['prevision']['choc_depuis']} ({choc} provinces, dites « en choc »), et les autres ({stable} provinces, « stables »). Les marges d'incertitude sont tirées des erreurs observées dans ce test : pour chaque horizon, la fourchette dans laquelle sont tombées 8 prévisions sur 10. Mesurée sur les cas qui servent à la construire, cette couverture est optimiste ; pour les provinces stables, elle suppose aussi qu'aucune école ne ferme.</p>
<p>Pour les provinces en choc, un second scénario, « réouverture des écoles », suppose le rattrapage progressif de {nb(100 * cfg['prevision']['part_rattrapage_reouverture'])} % de l'écart au maximum historique d'ici {hor}. Il n'ôte pas d'élèves aux provinces d'accueil quand les déplacés rentrent : c'est une borne haute des besoins.</p>
<h3>4.3 Répartition optimisée</h3>
<p>Le problème est écrit comme un programme linéaire en nombres entiers, résolu par un solveur libre (CBC).</p>
<ul>
<li><b>Décisions</b> : le nombre d'enseignants et le nombre de salles attribués à chaque province.</li>
<li><b>Objectif</b> : réduire le nombre d'élèves en surnombre par rapport aux normes à l'horizon {hor}, avec une pénalité qui augmente quand la surcharge s'aggrave. La pénalité, découpée en {len(pal)} paliers fins, croît comme le carré de la surcharge : un élève à 1,5 fois la norme compte {k15} fois plus qu'un élève juste au-dessus. Les moyens vont ainsi d'abord aux provinces les plus chargées. Un second calcul départage les plans de même pénalité au profit des provinces les plus chargées avant répartition : le plan est unique et ne dépend pas de l'ordre des données.</li>
<li><b>Contraintes</b> : le nombre d'enseignants et de salles disponibles, et un budget si on le fixe ; un enseignant nouveau doit disposer d'une salle, libre, construite ou rouverte. Pas de construction là où l'effectif est tombé sous {nb(100 * opt['seuil_acces_construction'])} % du maximum historique (accès difficile, à confirmer avec les services de l'éducation en situation d'urgence), ni là où plus de {nb(100 * cfg['implantation']['seuil_fermeture_rouvrir'], 0)} % des écoles ont fermé : on y rouvre d'abord, et les salles perdues depuis le maximum 2017-2025 accueillent les enseignants envoyés avec la réouverture. C'est la même règle que la carte des sites (section 5.7).</li>
<li><b>Options du décideur</b>, dans l'application : planchers et plafonds par province ou par région ; redéploiement d'enseignants en poste, qui ne quittent qu'une province restant à la norme ; report d'élèves du privé vers le public ; budget seul, avec un coût de salle « salle seule » ou « complexe de 3 salles tout compris ».</li>
<li><b>Comparaison</b> avec deux règles simples, à moyens égaux : au prorata des élèves attendus (la plus naturelle, qui ignore salles et accès), et au prorata des besoins, c'est-à-dire des enseignants et salles manquants, soumise aux mêmes règles que l'optimisation.</li>
</ul>
<p>{sc.groupby(['enseignants_disponibles', 'salles_disponibles']).ngroups * f['scen']['demande'].nunique()} scénarios sont résolus à l'avance (moyens disponibles × hypothèse sur les effectifs) ; {n_optimaux} sur {len(so)} sont prouvés optimaux par le solveur, chacun en {nb(duree_max, 1)} s au plus. Le simulateur de l'outil les affiche instantanément.</p>
<h3>4.4 Hypothèses</h3>
{table(["Hypothèse", "Valeur", "Origine"], [
    ["Norme d'élèves par maître", nb(nm), "Norme nationale citée par la DGESS"],
    ["Norme d'élèves par salle", nb(ns), "Posée égale à la précédente : une classe par maître"],
    ["Coût d'une salle de classe", f"{nb(opt['cout_salle_fcfa'] / 1e6, 1)} millions de FCFA (de {nb(opt['cout_salle_plage_fcfa'][0] / 1e6, 1)} à {nb(opt['cout_salle_plage_fcfa'][1] / 1e6, 1)})", "Médiane de 5 marchés communaux d'écoles primaires en 2025 (<a href='https://www.dgcmef.gov.bf/sites/default/files/2025-09/Quotidien%20N%C2%B04226.pdf'>Quotidien des marchés publics n° 4226</a>, DGCMEF) ; mobilier non précisé"],
    ["Coût d'un poste d'enseignant", f"{nb(opt['cout_enseignant_fcfa'] / 1e6, 1)} millions de FCFA par an", "Enseignant débutant en zone rurale, salaire et indemnités hors cotisations employeur (présentation de la coordination nationale EPT, Journée mondiale des enseignants, 6 octobre 2023, p. 6). Un poste nouveau est pourvu par un recrutement : on retient donc le coût d'un débutant. Fourchette de 1,8 (ville) à 4,0 millions (coût moyen d'un enseignant en 2019, tous ordres : masse salariale de 357,1 milliards pour 89 105 enseignants, Stratégie nationale sur la question enseignante, MENAPLN, 2020, p. 10-11)"],
    ["Coût d'une salle en complexe", f"{nb(opt['cout_salle_complexe_fcfa'] / 1e6, 1)} millions de FCFA par salle (variante)", "Complexe de 3 salles avec bureau, magasin, latrines et 75 tables-bancs : 50 millions (bilan 2024 de la gratuité, déclaration officielle rapportée par la presse)"],
    ["Construction non programmée", f"effectif sous {nb(100 * opt['seuil_acces_construction'])} % du maximum historique, ou plus de {nb(100 * cfg['implantation']['seuil_fermeture_rouvrir'], 0)} % d'écoles fermées", "Règles simples, faute de liste officielle exploitable des zones"],
    ["Salles à rouvrir", "salles perdues depuis le maximum 2017-2025", "Elles logent les enseignants envoyés avec la réouverture ; non comptées dans le ratio élèves par salle ; remise en état non chiffrée"],
    ["Part du public dans chaque province", f"celle de {ref}", "Simplification"],
    ["Post-primaire : norme d'élèves par classe", nb(npp), "Norme nationale citée par la DGESS"],
    ["Post-primaire : seuils des signaux", f"{nb(100 * cpp['seuil_part_sans_place'])} % d'élèves sans place ; {nb(100 * cpp['seuil_perte_etablissements'])} % d'établissements perdus", "Seuils de lecture, à ajuster"],
], gauche=3)}
<p>Toutes ces valeurs sont dans un fichier de paramètres : les modifier puis relancer une commande suffit à tout recalculer.</p>

<h2 id="s5">5. Les résultats</h2>
<h3>5.1 Diagnostic : des écarts de un à trois</h3>
<div class="deux">{carte}{barres}</div>
<p>Dans le public, {f['au_dessus']} provinces sur {len(c)} dépassent la norme de {nm} élèves par maître. Les plus chargées sont de deux sortes : des provinces à fort défi sécuritaire, où les écoles restées ouvertes accueillent des élèves déplacés et où des enseignants ont pu partir ({", ".join(joli(x) for x in tri.index[:4])}), et les deux grandes villes ({joli('KADIOGO')} : {nb(tri['KADIOGO'], 0)} ; {joli('HOUET')} : {nb(tri['HOUET'], 0)}). À l'opposé, les quatre provinces du Sud-Ouest sont sous la norme ({nb(c.loc[c['region'] == 'SUD-OUEST', 'eleves_par_maitre'].max(), 0)} élèves par maître au plus). Le public compte {nb(f['precaires'])} salles en paille ou en banco et {nb(f['mauvais'])} salles aux murs en mauvais état.</p>
<h3>5.2 Priorités : un classement dont on connaît la solidité</h3>
<p>Sur {nb(cfg['indice']['tirages_robustesse'])} jeux de poids, le classement reste proche de celui de base (corrélation de rang médiane : {nb(rob['spearman_median'], 2)}) et {nb(100 * rob['part_top10_conservee'])} % des dix premières provinces restent parmi les dix premières. Les quatre provinces du Sahel occupent les quatre premiers rangs ; dans 9 tirages sur 10, {joli(ind.iloc[0]['province'])} reste entre le {ind.iloc[0]['rang_p05']}ᵉʳ et le {ind.iloc[0]['rang_p95']}ᵉ rang. {rob['provinces_instables']} provinces ont un rang sensible, toutes proches d'une limite de tiers : {", ".join(joli(x) for x in ind.loc[ind['rang_instable'], 'province'])}. Pour le {joli('KADIOGO')}, très chargé mais aux bâtiments en dur, la priorité dépend du poids donné à l'état des salles : l'outil le signale. Classement complet et fourchettes de rang : vue Carte de l'outil.</p>

<h3>5.3 Prévision : fiable là où la situation est stable</h3>
{serie}
<div class="deux">
<div><p><b>{stable} provinces stables</b> ({nb(100 * f['part_eleves_stables'])} % des élèves). Erreur en %, selon l'horizon :</p>{_table_fiabilite(f, 'stable')}</div>
<div><p><b>{choc} provinces en choc.</b> Erreur en %, selon l'horizon :</p>{_table_fiabilite(f, 'choc')}</div>
</div>
<p>Dans les provinces stables, la croissance amortie se trompe de {nb(100 * fs.loc['croissance_amortie', 1], 1)} % à un an et de {nb(100 * fs.loc['croissance_amortie', hmax], 1)} % à {hmax} ans, contre {nb(100 * fs.loc['naive', hmax], 1)} % pour la référence : elle est retenue. Dans les provinces en choc, <b>aucune méthode ne fait mieux que la référence</b> (erreur de {nb(100 * fc.loc['naive', 1], 0)} % dès la première année) : les fermetures et réouvertures d'écoles ne se déduisent pas du passé. L'effectif y est donc maintenu dans le scénario central, et le scénario « réouverture » encadre l'autre possibilité.</p>
<p>La projection démographique, que la note d'intention envisageait comme socle, a été testée loyalement : elle est la meilleure à un et deux ans dans les provinces stables, mais moins bonne à partir de trois ans, et nettement moins bonne que la référence dans les provinces en choc. Les projections de population datent d'avant les déplacements ; à l'échelle de la province, elles ne suffisent pas.</p>
<p><b>Apprentissage automatique : {'retenu' if ml_retenu else 'testé, non retenu'}.</b> Deux modèles globaux (régression ridge, gradient boosting) ont été testés dans le même protocole, sur les mêmes {nb(ml_cas)} cas : le gradient boosting se trompe de {nb(100 * mlt.loc['ml_gradient_boosting', ml_h], 1)} % à {ml_h} ans, contre {nb(100 * mlt.loc['naive', ml_h], 1)} % pour la référence. Il prolonge les tendances passées et n'anticipe pas les fermetures d'écoles. {'' if ml_retenu else "L'essai est livré avec le code."}</p>
<h3>5.4 Besoins à la rentrée {hor[:4]}</h3>
{table(["Hypothèse sur les effectifs", f"Élèves du public en {hor}", "Enseignants manquants", "Salles manquantes", "Coût indicatif des salles"], [
    ["Scénario central", nb(bes['eleves']), nb(bes['maitres']), nb(bes['salles']), f"{nb(bes['salles'] * opt['cout_salle_fcfa'] / 1e9, 1)} milliards de FCFA (de {nb(bes['salles'] * opt['cout_salle_plage_fcfa'][0] / 1e9, 0)} à {nb(bes['salles'] * opt['cout_salle_plage_fcfa'][1] / 1e9, 0)})"],
    ["Réouverture des écoles (borne haute)", nb(besr['eleves']), nb(besr['maitres']), nb(besr['salles']), f"{nb(besr['salles'] * opt['cout_salle_fcfa'] / 1e9, 1)} milliards de FCFA (de {nb(besr['salles'] * opt['cout_salle_plage_fcfa'][0] / 1e9, 0)} à {nb(besr['salles'] * opt['cout_salle_plage_fcfa'][1] / 1e9, 0)})"],
])}
<p>« Manquants » signifie : ce qu'il faudrait ajouter pour que chaque province respecte la norme, sans rien retirer aux provinces mieux dotées. En {ref}, il manque déjà {nb(f['manquants_ref'][0])} enseignants et {nb(f['manquants_ref'][1])} salles selon ce calcul.</p>

<h3>5.5 Répartition : ce que l'optimisation apporte</h3>
<p>Exemple : {nb(N)} enseignants et {nb(M)} salles à répartir, scénario central. Les trois règles disposent des mêmes moyens.</p>
{table(["", "Sans moyens nouveaux", "Proportionnelle aux élèves", "Au prorata des besoins", "Optimisée"], [
    ["Enseignants effectivement affectés", "0", nb(p['enseignants_attribues']), nb(bb['enseignants_attribues']), nb(o['enseignants_attribues'])],
    [f"Élèves en surnombre (norme de {nm} par maître)", nb(r['eleves_au_dela_norme_maitre']), nb(p['eleves_au_dela_norme_maitre']), nb(bb['eleves_au_dela_norme_maitre']), nb(o['eleves_au_dela_norme_maitre'])],
    ["Élèves par maître dans la province la plus chargée", nb(r['pire_ratio_eleves_maitre'], 0), nb(p['pire_ratio_eleves_maitre'], 0), nb(bb['pire_ratio_eleves_maitre'], 0), f"<b>{nb(o['pire_ratio_eleves_maitre'], 0)}</b>"],
    ["Inégalité entre provinces (indice de Gini, 0 = égalité)", nb(r['gini_ratio_maitre'], 3), nb(p['gini_ratio_maitre'], 3), nb(bb['gini_ratio_maitre'], 3), f"<b>{nb(o['gini_ratio_maitre'], 3)}</b>"],
    ["Provinces au-dessus de la norme", nb(r['provinces_au_dessus_norme_maitre']), f"<b>{nb(p['provinces_au_dessus_norme_maitre'])}</b>", nb(bb['provinces_au_dessus_norme_maitre']), nb(o['provinces_au_dessus_norme_maitre'])],
    ["Élèves dans une province à la norme", nb(100 * r['part_eleves_province_conforme'], 0) + " %", f"<b>{nb(100 * p['part_eleves_province_conforme'], 0)} %</b>", nb(100 * bb['part_eleves_province_conforme'], 0) + " %", nb(100 * o['part_eleves_province_conforme'], 0) + " %"],
])}
<p><b>Ce que l'optimisation apporte, et ce qu'elle n'apporte pas.</b> Toute règle qui place les enseignants là où ils manquent réduit autant le nombre d'élèves en surnombre : {nb(bb['eleves_au_dela_norme_maitre'])} avec une règle simple au prorata des besoins comme avec l'optimisation, contre {nb(p['eleves_au_dela_norme_maitre'])} avec la répartition proportionnelle, qui donne des enseignants à des provinces déjà sous la norme. {(f"Pour la province la plus chargée, l'optimisation et la règle des besoins font jeu égal ({nb(o['pire_ratio_eleves_maitre'], 0)} élèves par maître, contre {nb(p['pire_ratio_eleves_maitre'], 0)} en proportionnelle) : cette province ne peut recevoir d'enseignants qu'à hauteur de ses salles libres (voir plus bas). L'apport propre de l'optimisation est l'équité entre toutes les autres : elle sert d'abord les plus chargées et réduit l'inégalité entre provinces (Gini de {nb(o['gini_ratio_maitre'], 3)} contre {nb(bb['gini_ratio_maitre'], 3)} et {nb(p['gini_ratio_maitre'], 3)}).") if round(o['pire_ratio_eleves_maitre']) >= round(bb['pire_ratio_eleves_maitre']) else (f"L'apport propre de l'optimisation est l'équité : elle ramène la province la plus chargée à {nb(o['pire_ratio_eleves_maitre'], 0)} élèves par maître (contre {nb(bb['pire_ratio_eleves_maitre'], 0)} et {nb(p['pire_ratio_eleves_maitre'], 0)}) et réduit l'inégalité entre provinces (Gini de {nb(o['gini_ratio_maitre'], 3)} contre {nb(bb['gini_ratio_maitre'], 3)} et {nb(p['gini_ratio_maitre'], 3)}).")} En contrepartie, elle laisse {nb(o['provinces_au_dessus_norme_maitre'])} provinces légèrement au-dessus de la norme, contre {nb(p['provinces_au_dessus_norme_maitre'])} avec la proportionnelle : au lieu d'achever la mise à la norme de provinces déjà proches, elle soulage les plus surchargées. La plus chargée restante, {joli(pire_prov)} ({nb(ao.loc[pire_prov, 'ratio_maitre_apres'], 0)}), est une province où la construction n'est pas programmée{'' if not ao.loc[pire_prov, 'construction_possible'] else ' (à vérifier)'} : elle ne reçoit d'enseignants qu'à hauteur de ses salles libres. {(f"À budget serré, la différence se voit aussi sur la province la plus chargée : avec {nb(pb.index.min() / 1e9, 0)} milliards de FCFA, {nb(pb.loc[pb.index.min(), ('pire_ratio_eleves_maitre', 'optimisee')], 0)} élèves par maître avec l'optimisation, contre {nb(pb.loc[pb.index.min(), ('pire_ratio_eleves_maitre', 'besoins')], 0)} avec la règle des besoins appliquée au même partage entre postes et salles.") if ('pire_ratio_eleves_maitre', 'besoins') in pb.columns and pb.loc[pb.index.min(), ('pire_ratio_eleves_maitre', 'besoins')] - pb.loc[pb.index.min(), ('pire_ratio_eleves_maitre', 'optimisee')] >= 5 else ""}</p>
{points}
<p><b>Les salles commandent.</b> {f"Sur les {nb(N)} enseignants, {nb(N - o['enseignants_attribues'])} ne peuvent pas être affectés utilement, faute de salle." if N > o['enseignants_attribues'] else f"Les {nb(N)} enseignants trouvent une salle, mais {nb(rouv['salles_rouvertes'].sum())} de ces salles sont des salles d'écoles fermées, à rouvrir dans {len(rouv)} provinces où l'on ne construit pas."} Construire ou rouvrir en même temps que l'on recrute conditionne donc l'effet des recrutements.</p>
<p><b>Redéployer avant de recruter.</b> Dans {rd['provinces_source']} provinces, il y aura en {hor[:4]} plus d'enseignants que la norme n'en demande. Avec {nb(rd['recrues'])} recrues et {nb(M)} salles, autoriser jusqu'à {nb(rd['redeployes'])} redéploiements depuis ces provinces ramène les élèves en surnombre de {nb(rd['surnombre_sans'])} à {nb(rd['surnombre_avec'])}, soit autant que {nb(rd['recrues'] + rd['redeployes'])} recrues ({nb(rd['surnombre_recrues'])}) : environ {nb(rd['economie'] / 1e9, 1)} milliards de FCFA de postes par an. Le calcul ignore le coût et l'acceptabilité d'une mutation ; c'est une option du simulateur, pas le plan de référence.</p>
<p><b>Sous contrainte de budget seule</b>, le nombre d'enseignants et de salles est laissé libre : l'optimisation arbitre entre recruter (un poste coûte {nb(opt['cout_enseignant_fcfa'] / 1e6, 1)} millions de FCFA par an, compté sur {opt['annees_budget']} ans) et construire (une salle coûte {nb(opt['cout_salle_fcfa'] / 1e6, 1)} millions, une fois). Les règles simples reçoivent les mêmes enseignants et salles que l'optimisation. {bud_ok} scénarios sur {len(pb)} sont prouvés optimaux ; le détail est dans le fichier des scénarios déposé et se rejoue dans la vue Répartition.</p>
<p><b>Sensibilité aux hypothèses.</b> Une hypothèse varie à la fois, les autres gardent leur valeur de référence. Dans {o_pire_ok} variantes sur {len(ps)}, la répartition optimisée laisse la province la plus chargée au plus aussi chargée que la meilleure des deux règles simples ; dans {int(o_gini_ok.sum())}, elle a aussi l'inégalité entre provinces la plus faible{(' (exception : ' + ', '.join(gini_exceptions) + ', ce qui justifie la pénalité par paliers fins)') if gini_exceptions else ''}. Une norme plus exigeante, comme les 40 élèves par maître du plan sectoriel 2017-2030, ne change pas le classement des règles. Le détail des variantes est dans le fichier des scénarios déposé.</p>

<h3>5.6 Post-primaire : un diagnostic régional</h3>
<p>En {ppr}, le post-primaire scolarise {nb(ppn['eleves_pp'])} élèves ({'+' if ppn['eleves_pp'] >= ppn1['eleves_pp'] else '−'}{nb(abs(100 * (ppn['eleves_pp'] / ppn1['eleves_pp'] - 1)), 1)} % en un an). Trois constats ressortent.</p>
<ul>
<li><b>La pression est à l'entrée du cycle.</b> Une classe de 6ᵉ du public général compte en moyenne {nb(ppn['eleves_par_classe_6e'])} élèves, sous la norme de {npp}, mais {len(au6)} régions la dépassent : {", ".join(f"{joli(k)} ({nb(v)})" for k, v in au6['eleves_par_classe_6e'].items())}. Le ratio baisse ensuite jusqu'en 3ᵉ ({nb(ppn['eleves_par_classe_3e'])} au niveau national) : les salles manquent en 6ᵉ.</li>
<li><b>Les régions touchées par l'insécurité ont perdu leurs établissements.</b> Le pays compte {nb(ppn['etablissements_2019'] - ppn['etablissements'])} établissements de moins qu'en 2019-2020 (−{nb(abs(100 * ppn['evolution_etablissements_2019']), 1)} %), mais la perte se concentre : {", ".join(f"{joli(k)} −{nb(abs(100 * v), 0)} %" for k, v in pertes['evolution_etablissements_2019'].items())}. Les ratios modérés de ces régions décrivent les établissements restés ouverts, pas les élèves qui n'y ont plus accès.</li>
<li><b>Le manque de places assises est d'abord un problème de répartition.</b> {nb(ppn['deficit_places'])} élèves du public général n'ont pas de place assise ({nb(100 * ppn['part_eleves_sans_place'], 1)} %), alors que {nb(ppn['excedent_places'])} places sont libres dans d'autres établissements ; dans {nb(((ppg['deficit_places'] > 0) & (ppg['excedent_places'] > 0)).sum())} régions sur {len(ppg)}, des établissements en manquent pendant que d'autres en ont en trop. Le solde est un excédent de {nb(ppn['excedent_net_places'])} places : une partie du déficit pourrait être résorbée en transférant des tables-bancs, ce qu'il faut vérifier au regard des distances entre établissements. Les régions les plus touchées : {", ".join(f"{joli(k)} ({nb(100 * v, 1)} %)" for k, v in sans_place['part_eleves_sans_place'].items())}.</li>
</ul>
<p class="petit">Tableau par région : fichier du diagnostic post-primaire déposé. Champ : élèves par classe et places assises, public général ; établissements, post-primaire et secondaire, public et privé. Les enseignants ne sont publiés que pour le post-primaire et le secondaire ensemble, hors vacataires, alors que le privé repose largement sur eux : un ratio d'élèves par enseignant ne serait pas comparable entre régions, il n'est pas utilisé. Faute de données par province, le post-primaire ne fait pas l'objet d'une répartition chiffrée.</p>

<h3>5.7 Accès à l'école : où sont les enfants loin d'une école ?</h3>
<p>À la commune, le recensement de 2019 donne les enfants de 6 à 11 ans ; leur nombre en {hor[:4]} est obtenu en répartissant la projection INSD de chaque province entre ses communes selon leur part de 2019 (méthode des poids relatifs de l'INSD) : {nb(e_h)} enfants, total égal à la projection officielle. À l'intérieur de chaque commune, la grille de 100 m de WorldPop ({hor[:4]}) situe les enfants, ses totaux étant recalés sur ceux de l'INSD. Les écoles géolocalisées viennent d'OpenStreetMap, qui n'en recense qu'environ un tiers : la part d'enfants à plus de {imp['rayon_km']} km d'une école est donc donnée par deux estimations. Avec les seules écoles cartographiées : {nb(loin_h)} enfants ({nb(100 * loin_h / e_h, 1)} %). En ajoutant dans chaque province les écoles de l'annuaire absentes d'OSM ({nb(manque_ec)}), placées là où elles rapprochent le plus d'enfants (estimation favorable ; {nb(placees_ec)} suffisent à rapprocher tous les enfants qui pouvaient l'être) : {nb(loin_b)} enfants ({nb(100 * loin_b / e_h, 1)} %). La réalité est probablement entre les deux ; la liste officielle des écoles géolocalisées, chargée dans l'outil, la donnerait exactement.</p>
<p><b>Où ouvrir une école ?</b> Un algorithme de couverture maximale choisit, maille de 1 km par maille, le site qui rapproche le plus d'enfants restés éloignés même dans l'hypothèse favorable, tant qu'un site en rapproche au moins {imp['seuil_enfants_site']} (trois classes), hors provinces à l'accès trop dégradé. Il retient {len(sp)} sites pour {nb(sp['enfants_rapproches'].sum())} enfants. Le constat principal est ailleurs : <b>{len(sp) - n_cons} de ces sites sont dans des provinces qui ont perdu plus de {nb(100 * imp['seuil_fermeture_rouvrir'], 0)} % de leurs écoles ouvertes</b> depuis leur maximum de 2017-2025. Là, l'éloignement vient des fermetures : la réponse est de rouvrir ou de délocaliser, pas de construire, et la répartition (section 5.5) n'y programme aucune salle neuve. Seuls {n_cons} sites relèvent d'un vrai manque d'écoles.</p>
<h3>5.8 Test sur le passé : l'outil aurait-il fait mieux ?</h3>
<p>On se place en {retro0[:4]}, avec la seule information de l'époque (effectifs, maîtres et salles ; part du pic et écoles fermées calculées sur les seules années connues à cette date ; effectif inchangé comme prévision). Les recrutements ne sont pas publiés et le solde national est négatif, à cause des fermetures : les moyens à répartir sont les hausses nettes réellement observées province par province. Les quatre répartitions de ces mêmes moyens sont jugées sur les élèves réellement inscrits en fin de période (élèves au-delà de la norme de {nm} par maître).</p>
{t_retro}
<p>Sur les deux périodes, l'outil fait mieux que la répartition effective, et mieux que les deux règles simples. Face à la règle au prorata des besoins, l'écart est plus faible ({" et ".join(f"−{nb(100 * g, 0)} %" for g in gain_b)}) : l'essentiel du gain vient du ciblage des provinces en manque. L'outil est jugé ici sur son propre critère. Limites : ce sont des hausses nettes, pas des recrutements ; les baisses sont neutralisées de la même façon dans toutes les répartitions.</p>
<p class="petit">Les sites proposés, avec leurs coordonnées et la recommandation construire ou rouvrir, sont sur la carte de l'outil et dans le fichier des sites proposés.</p>

<h2 id="s6">6. L'outil : usage, coût et mise en place</h2>
<p>L'outil est une application web, en ligne à l'adresse <a href="{adresse}">{adresse.removeprefix("https://")}</a>. Elle s'ouvre dans un navigateur, sans installation ni compte, et une visite guidée la présente à la première ouverture. Cinq vues :</p>
<ul>
<li><b>Accueil</b> : le résultat central et le test sur le passé.</li>
<li><b>Carte</b> : de la région à la province puis à la commune, avec les indicateurs, les priorités, l'accès à l'école et les sites où construire ou rouvrir. Un curseur remonte les années ; la fiche compare public et privé ; chaque chiffre a son aide « ? ».</li>
<li><b>Répartition</b> : le décideur fixe ses moyens ou son budget, ses planchers et plafonds par province ou par région, un redéploiement, un report d'élèves du privé vers le public, et le serveur calcule le plan optimal en direct (quelques secondes en général, {nb(duree_max, 0)} s au plus pour un plan à moyens fixés), comparé aux règles simples. Le plan s'exporte en classeur Excel (fiche, plan, comparaison, hypothèses) et s'imprime en fiche de décision avec visa.</li>
<li><b>Données</b> : un technicien télécharge le gabarit de l'année, le fait contrôler, puis l'importe ; chaque import est un lot daté, signé et réversible.</li>
<li><b>Méthode</b> : sources, hypothèses, limites.</li>
</ul>
<div class="deux">{fig(img_rep, "Figure 5 — Répartition en direct : moyens, contraintes, plan optimal comparé aux règles simples, exports.")}{fig(img_carte, "Figure 6 — Carte : de la province à la commune, accès à l'école et sites proposés.")}</div>
<h3>Pensée pour durer et pour être installée</h3>
<ul>
<li><b>Mise à jour annuelle sans programmation.</b> Chaque fichier importé est contrôlé : territoires inconnus, doublons, valeurs négatives, fichier incomplet, variations anormales. Il peut être retiré, et l'année revient alors à la version précédente.</li>
<li><b>Découpage territorial évolutif.</b> La commune est l'unité stable ; provinces et régions sont des regroupements datés. Le découpage de 2025 (17 régions, 47 provinces) est déjà décrit, et une province créée, renommée ou scindée se déclare sans toucher au code.</li>
<li><b>Installation.</b> Un conteneur Docker, un script de déploiement, un script de sauvegarde, une route de surveillance, un guide d'installation et d'exploitation. Le code est protégé par le droit d'auteur (tous droits réservés, fichier LICENSE) ; son utilisation par l'administration se convient avec l'auteur.</li>
<li><b>Connexions lentes.</b> Environ 90 ko pour ouvrir l'outil. Sur connexion lente, un mode léger remplace les cartes par des listes (environ 130 ko). Après la première visite, l'outil s'ouvre même sans réseau ; seul le calcul d'un plan en demande (5 ko).</li>
<li><b>Filles.</b> Filles pour 100 garçons inscrits, par province et par année (annuaires) : sur la carte, dans les fiches et dans l'assistant.</li>
<li><b>Mise en service.</b> Un technicien de la DGESS met à jour l'outil chaque année (une journée de formation) ; pilote avec deux régions, puis extension ; un serveur modeste, sans abonnement (détail : page Méthode et guide d'exploitation).</li>
<li><b>« Poser une question ».</b> Un assistant reconnaît la question (province, commune, classement, plan avec des moyens donnés, sens d'un terme) et répond avec les chiffres et les calculs de l'outil ; un plan proposé s'ouvre dans la Répartition. Sans IA générative ni service extérieur : gratuit, immédiat, aucune donnée ne quitte le serveur.</li>
</ul>
<h3>Ce que coûte la solution</h3>
<ul>
<li><b>Aucune licence à payer pour les outils.</b> Yennenga est bâti uniquement sur des logiciels libres et gratuits : Python, pandas, GeoPandas, PuLP et le solveur CBC pour les calculs ; FastAPI et SQLite pour le serveur ; React et MapLibre pour l'interface ; Docker pour l'installation. Les cartes utilisent nos propres contours : aucun service de cartographie payant.</li>
<li><b>Aucun abonnement ni service d'IA payant.</b> L'assistant « Poser une question » fonctionne par règles, sur le serveur : il ne coûte rien à l'usage et aucune donnée ne sort.</li>
<li><b>Hébergement modeste.</b> Un petit serveur suffit (celui de la démonstration : 2 cœurs, 8 Go de mémoire, partagés avec d'autres applications) ; l'outil peut aussi tourner sur un serveur du ministère, en intranet.</li>
<li><b>Mise à jour annuelle.</b> Le seul coût récurrent est le temps d'un technicien de la DGESS : une journée de formation, puis le report des chiffres de l'annuaire dans le gabarit, une fois par an.</li>
<li>Les conditions d'utilisation de Yennenga lui-même se conviennent avec son auteur (fichier LICENSE).</li>
</ul>
<h3>Feuille de route de mise en place</h3>
<p>Une proposition, à ajuster avec le ministère. L'outil fonctionne déjà : la mise en place porte sur la validation des hypothèses, l'installation et l'appropriation.</p>
{table(["Étape", "Quand", "Ce qui est fait", "Qui", "Résultat attendu"], [
    ["1. Cadrage", "Mois 1", "Valider les normes, les coûts unitaires d'un poste et d'une salle, la règle d'accès et la liste des zones où l'on rouvre plutôt que construire ; désigner un référent à la DGESS.", "DGESS, finances, éducation en situation d'urgence", "Hypothèses officielles inscrites dans le fichier de paramètres"],
    ["2. Installation et formation", "Mois 2", "Installer l'outil sur un serveur du ministère (conteneur Docker, une journée) avec sa sauvegarde ; former un technicien (une journée) ; importer l'annuaire le plus récent et, si elle existe, la liste officielle des écoles géolocalisées.", "Service informatique, DGESS", "Outil à jour, accessible en intranet et en ligne"],
    ["3. Pilote", "Une rentrée scolaire", "Deux régions utilisent les plans et les fiches province ; on compare le plan de l'outil aux décisions prises et on recueille les remarques des utilisateurs.", "DGESS, deux directions régionales", "Élèves en surnombre évités, appropriation mesurée"],
    ["4. Généralisation", "Année 2", "Toutes les régions ; le plan national accompagne l'arbitrage budgétaire des recrutements et des constructions ; extension au post-primaire dès que ses données sont publiées par province.", "Cabinet, DGESS, ressources humaines, finances", "Un plan annuel produit par l'outil"],
    ["5. Cycle annuel", "Chaque année", "Annuaire publié → import contrôlé (une journée) → plans et scénarios → arbitrage budgétaire → affectations et marchés de construction → bilan à la rentrée suivante.", "DGESS, ressources humaines, finances", "Décisions tracées et comparables d'une année à l'autre"],
], gauche=5)}
<p class="petit">Conditions de réussite : un annuaire publié à temps par province ; une liste des zones à accès difficile tenue à jour avec les services de l'éducation en situation d'urgence ; un référent formé à la DGESS ; un accord avec l'auteur pour l'utilisation et la maintenance.</p>
<h3>Limites et suites</h3>
<ul>
<li>Les annuaires décrivent les écoles ouvertes. En zone d'insécurité, les ratios portent sur les élèves et les maîtres encore présents ; les enfants déscolarisés n'y figurent pas.</li>
<li>La répartition des enseignants s'arrête à la province : enseignants et salles ne sont publiés qu'à cette maille. L'implantation descend à la commune et au site ; la liste officielle des écoles géolocalisées la rendrait exacte.</li>
<li>Les salles à rouvrir supposent que les bâtiments des écoles fermées sont récupérables ; leur remise en état n'est pas chiffrée. Le redéploiement ignore le coût et l'acceptabilité des mutations.</li>
<li>L'estimation favorable de l'accès à l'école compte comme ouvertes des écoles qu'OpenStreetMap recense alors qu'elles sont peut-être fermées.</li>
<li>Les marges d'incertitude sont calculées province par province ; elles sont larges dans les provinces en choc et leur somme n'est pas une marge nationale.</li>
<li>Les coûts unitaires et la règle d'accessibilité sont des hypothèses, à remplacer par les valeurs des services compétents.</li>
<li>La répartition optimisée s'appliquera telle quelle au post-primaire dès que ses données seront publiées par province.</li>
<li>Conçu pour le défi 3, l'outil repose sur un socle générique : données par commune versées chaque année et contrôlées, carte, indice de besoin pondéré, calcul de la meilleure répartition sous budget et exigences. Il peut être paramétré pour d'autres questions, à condition d'y verser les données correspondantes : risque de décrochage (défi 1), écarts filles-garçons et villes-campagnes (défi 2), ou, hors de l'école, répartition des soignants ou des points d'eau. Ces usages ne sont pas réalisés ici.</li>
</ul>

<h2 id="s7">7. Reproduire les résultats</h2>
<p>Tout résultat s'obtient par une commande à partir des fichiers d'origine ; les chiffres de ce document sont lus dans les sorties de la chaîne, et le document lui-même est produit par le code.</p>
<pre>pip install -r requirements.txt
# Windows (PowerShell)
$env:PYTHONPATH = "src"
python -m dcb.pipeline         # des fichiers bruts aux résultats, quelques minutes
python -m pytest -q            # {f['nb_tests']} tests des calculs
cd interface; npm ci; npm run build; cd ..   # interface de l'application
python -m uvicorn dcb.service:app --port 8000  # application sur http://localhost:8000
python -m dcb.documentation    # ce document (Edge ou Chrome requis pour le PDF)
python -m dcb.depot            # fichiers de dépôt et contrôle
# Linux, macOS : préfixer chaque commande par PYTHONPATH=src</pre>
<p>Le classeur principal se place dans <code>data/raw/</code>, le Data Pack décompressé dans <code>data/external/datapack/</code>, les grilles WorldPop dans <code>data/external/worldpop/</code> (sans elles, la chaîne saute l'accès à l'école et le signale). La mise en ligne (Docker), la mise à jour annuelle et la sauvegarde sont décrites dans le guide d'installation et d'exploitation, joint au code. Outils : Python 3.13, pandas, GeoPandas, PuLP et le solveur CBC, tous libres. Le code est organisé en un module par étape (lecture, extraction, contrôles, référentiel territorial, entrepôt, indicateurs, indice, démographie, prévision, optimisation, scénarios, test rétrospectif, carte scolaire, implantation, post-primaire, tableau de bord, service en ligne) ; les paramètres sont dans <code>config.yaml</code> ; des tests automatiques couvrent la lecture des nombres, le référentiel des provinces, les méthodes de prévision, la répartition sur un cas vérifiable à la main, et l'égalité des totaux avec les publications.</p>
<h2 id="s8">8. Glossaire</h2>
{table(["Terme", "Sens"], [[t, d] for t, d in GLOSSAIRE], gauche=2).replace("<table>", '<table class="glossaire">', 1)}
</body></html>"""


def generer() -> None:
    f = faits()
    DOCS.mkdir(exist_ok=True)
    source = DOCS / "documentation.html"
    source.write_text(html(f), encoding="utf-8")
    print(f"{source.relative_to(RACINE)} : {source.stat().st_size / 1024:.0f} ko")
    nav = navigateur()
    if not nav:
        print("Aucun navigateur Chromium trouvé : ouvrir le fichier HTML et l'imprimer en PDF (A4, sans en-tête ni pied).")
        return
    pdf = DOCS / "documentation.pdf"

    def imprimer() -> bool:
        pdf.unlink(missing_ok=True)  # ne jamais relire une version précédente
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            subprocess.run([nav, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp}/profil", "--no-pdf-header-footer",
                            f"--print-to-pdf={pdf}", source.as_uri()], check=False, capture_output=True, timeout=180)
            _attendre_fichier(pdf)
        return pdf.exists()

    if not imprimer():
        print("La conversion en PDF a échoué.")
        return
    from pypdf import PdfReader

    serre = lambda x: "".join(x.split()).replace("’", "'")  # noqa: E731
    textes = [serre(pg.extract_text() or "") for pg in PdfReader(str(pdf)).pages]
    pages = {}
    for a, t in SOMMAIRE:
        cle = serre(t)[:22]
        pages[a] = next((i + 1 for i, x in enumerate(textes) if i > 0 and cle in x), "")
    source.write_text(html(f, pages), encoding="utf-8")
    if not imprimer():
        print("La conversion en PDF a échoué.")
        return
    print("sommaire :", pages)
    lecteur = PdfReader(str(pdf))
    pages = len(lecteur.pages)
    print(f"{pdf.relative_to(RACINE)} : {pages} pages, {pdf.stat().st_size / 1024:.0f} ko ; métadonnées : {dict(lecteur.metadata or {})}")
    if pages > 15:
        print(f"ATTENTION : {pages} pages, la limite est de 15")


if __name__ == "__main__":
    generer()
