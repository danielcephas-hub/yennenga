"""Application en ligne : calcule une répartition à la demande, avec les contraintes du décideur.

Le service lit les tables produites par la chaîne (data/processed) et appelle le même code que le reste
du projet (dcb.optimisation) : un plan obtenu en ligne est identique à celui de la ligne de commande.

Usage : PYTHONPATH=src python -m uvicorn dcb.service:app --port 8000   (après dcb.pipeline)
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from typing import Literal

import pandas as pd
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from dcb.indicateurs import SORTIE, config
from dcb.lecture import RACINE
from dcb.optimisation import comparer, donnees_probleme, mouvements

TABLEAU_DE_BORD = RACINE / "outputs" / "tableau_de_bord" / "tableau_de_bord.html"
WEB = RACINE / "outputs" / "web"
INTERFACE = RACINE / "interface" / "dist"
FICHIERS_WEB = {"meta", "provinces", "provinces_annees", "ecoles", "communes", "sites", "geo_communes", "geo_provinces_2025", "geo_regions_2025",
                "geo_provinces_annuaires"}
TAILLE_MAX_IMPORT = 5 * 1024 * 1024
COLONNES_DETAIL = ["province", "region", "eleves_horizon", "maitres", "salles", "enseignants_attribues",
                   "salles_attribuees", "ratio_maitre_apres", "ratio_salle_apres", "construction_possible",
                   "acces_construction", "rouvrir_d_abord", "part_ecoles_fermees", "salles_a_rouvrir", "salles_rouvertes",
                   "solde_redeploiement", "motif"]

app = FastAPI(title="Répartition des enseignants et des salles de classe", docs_url="/api/docs", redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# au plus N calculs simultanés par processus : au-delà, on répond « réessayez » plutôt que d'épuiser la machine
_CALCULS = threading.BoundedSemaphore(int(os.environ.get("DCB_CALCULS_SIMULTANES", "2")))
LIGNES_MAX_IMPORT = 50_000
ENTETES_SECURITE = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin",
                    "X-Frame-Options": "SAMEORIGIN", "Permissions-Policy": "geolocation=(), camera=(), microphone=()"}


@app.middleware("http")
async def _entetes(request: Request, appel):
    reponse = await appel(request)
    for k, v in ENTETES_SECURITE.items():
        reponse.headers.setdefault(k, v)
    return reponse

CHAMPS = {"enseignants": "enseignants à répartir", "salles": "salles à construire", "budget_fcfa": "budget",
          "min_enseignants": "plancher d'enseignants", "max_enseignants": "plafond d'enseignants",
          "min_salles": "plancher de salles", "max_salles": "plafond de salles", "eleves_par_maitre": "norme",
          "redeploiement": "enseignants redéployés"}


@app.exception_handler(RequestValidationError)
async def _erreur_lisible(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Une phrase en français par champ refusé, au lieu du détail technique de la validation."""
    phrases = []
    for e in exc.errors():
        loc = [str(x) for x in e.get("loc", []) if x != "body"]
        champ = CHAMPS.get(loc[-1], loc[-1]) if loc else "demande"
        lieu = f" ({loc[-2]})" if len(loc) >= 3 else ""
        if e.get("type") == "greater_than_equal":
            raison = "doit être positif ou nul"
        elif e.get("type") == "greater_than":
            raison = "doit être strictement positif"
        elif e.get("type", "").endswith("_parsing") or e.get("type", "").endswith("_type"):
            raison = "doit être un nombre"
        else:
            raison = "valeur refusée"
        phrases.append(f"{champ}{lieu} : {raison}")
    return JSONResponse(status_code=422, content={"detail": " ; ".join(phrases) or "demande invalide"})


class Bornes(BaseModel):
    min_enseignants: int | None = Field(None, ge=0)
    max_enseignants: int | None = Field(None, ge=0)
    min_salles: int | None = Field(None, ge=0)
    max_salles: int | None = Field(None, ge=0)


class Demande(BaseModel):
    enseignants: int | None = Field(None, ge=0, description="Enseignants à répartir (défaut : config.yaml)")
    salles: int | None = Field(None, ge=0, description="Salles à construire (défaut : config.yaml)")
    budget_fcfa: float | None = Field(None, gt=0, description="Plafond de budget ; absent = pas de plafond")
    budget_seul: bool = Field(False, description="Vrai : seul le budget limite, le modèle choisit enseignants et salles")
    scenario: str = "tendance"
    eleves_par_maitre: int | None = None
    redeploiement: int = Field(0, ge=0, description="Enseignants en poste que l'on accepte de déplacer (0 = aucun)")
    cout_salle: Literal["salle", "complexe"] = Field("salle", description="salle seule (marchés communaux 2025) "
                                                     "ou complexe de 3 salles tout compris (standard ministériel)")
    recul_prive: float = Field(0, ge=0, le=100, description="Part (en %) des élèves du privé qui passent dans le public "
                                                            "d'ici l'horizon ; 0 = part du privé stable")
    provinces: dict[str, Bornes] = {}
    regions: dict[str, Bornes] = {}


@lru_cache(maxsize=1)
def _tables() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    return (config(), pd.read_csv(SORTIE / "province_annee.csv", sep=";", encoding="utf-8"),
            pd.read_csv(SORTIE / "prevision_effectifs.csv", sep=";", encoding="utf-8"))


@lru_cache(maxsize=1)
def _centres() -> dict[str, tuple[float, float]]:
    """Centre de population de chaque province des annuaires (communes pondérées par leur population)."""
    import json
    f = WEB / "communes.json"
    if not f.exists():
        return {}
    c = pd.DataFrame(json.loads(f.read_text(encoding="utf-8")))
    c = c.dropna(subset=["lat", "lon", "population_2019"])
    w = c["population_2019"]
    g = c.assign(wlat=c["lat"] * w, wlon=c["lon"] * w, w=w).groupby("province_ancienne")[["wlat", "wlon", "w"]].sum()
    return {p: (r.wlat / r.w, r.wlon / r.w) for p, r in g.iterrows() if r.w > 0}


def _propre(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def repartir(demande: Demande) -> dict:
    cfg0, table, prevision = _tables()
    cfg, srv = copy.deepcopy(cfg0), cfg0["service"]
    opt = cfg["optimisation"]
    if demande.scenario not in set(prevision["scenario"]):
        raise ValueError(f"Évolution des effectifs inconnue : {demande.scenario}.")
    if demande.eleves_par_maitre is not None:
        if demande.eleves_par_maitre not in srv["normes_acceptees"]:
            raise ValueError("Normes acceptées : " + ", ".join(map(str, srv["normes_acceptees"])) + " élèves par enseignant.")
        cfg["normes"] = {"eleves_par_maitre": demande.eleves_par_maitre, "eleves_par_salle": demande.eleves_par_maitre}
    if demande.budget_seul and demande.budget_fcfa is None:
        raise ValueError("Indiquer un budget pour le mode « budget seul ».")
    illimite = 10 ** 6
    n = illimite if demande.budget_seul else (opt["enseignants_a_repartir"] if demande.enseignants is None else demande.enseignants)
    m = illimite if demande.budget_seul else (opt["salles_a_construire"] if demande.salles is None else demande.salles)
    if not demande.budget_seul and (n > srv["enseignants_max"] or m > srv["salles_max"]):
        raise ValueError(f"Au plus {srv['enseignants_max']} enseignants et {srv['salles_max']} salles par calcul.")
    if demande.budget_fcfa is not None and demande.budget_fcfa > srv["budget_max_fcfa"]:
        raise ValueError(f"Budget au-delà du plafond accepté ({srv['budget_max_fcfa'] / 1e9:.0f} milliards de FCFA).")
    opt["temps_limite_s"] = srv["temps_limite_s"]
    if demande.cout_salle == "complexe":
        opt["cout_salle_fcfa"] = opt["cout_salle_complexe_fcfa"]
    contraintes = {"provinces": {k: v.model_dump(exclude_none=True) for k, v in demande.provinces.items()},
                   "regions": {k: v.model_dump(exclude_none=True) for k, v in demande.regions.items()}}
    if demande.recul_prive > srv["recul_prive_max"]:
        raise ValueError(f"Recul du privé : au plus {srv['recul_prive_max']} %.")
    d = donnees_probleme(table, prevision, cfg, demande.scenario, demande.recul_prive / 100)
    if demande.redeploiement > srv["enseignants_max"]:
        raise ValueError(f"Au plus {srv['enseignants_max']} enseignants redéployés.")
    detail, bilan, statut = comparer(d, cfg, n, m, demande.budget_fcfa, contraintes, demande.redeploiement)
    o = bilan.set_index("methode").loc["optimisee"]
    cout_salles = o["salles_attribuees"] * opt["cout_salle_fcfa"]
    salaires_an = o["enseignants_attribues"] * opt["cout_enseignant_fcfa"]
    cout = salaires_an * opt.get("annees_budget", 1) + cout_salles
    po = detail[detail["methode"] == "optimisee"]
    return {
        "statut": statut, "duree_s": float(o["duree_s"]), "horizon": cfg["annee_horizon"], "scenario": demande.scenario,
        "recul_prive": demande.recul_prive, "eleves_horizon_public": int(d["eleves_horizon"].sum()),
        "norme_eleves_par_maitre": cfg["normes"]["eleves_par_maitre"],
        "enseignants_utilises": int(o["enseignants_attribues"]), "salles_utilisees": int(o["salles_attribuees"]),
        "enseignants_redeployes": int(o.get("enseignants_redeployes", 0) or 0),
        "cout_fcfa": float(cout), "cout_salle_fcfa": float(opt["cout_salle_fcfa"]),
        "cout_salles_fcfa": float(cout_salles), "salaires_annuels_fcfa": float(salaires_an),
        "annees_budget": int(opt.get("annees_budget", 1)),
        "mouvements": mouvements(po, _centres()) if demande.redeploiement else [],
        "bilan": _propre(bilan.round(4)),
        "repartitions": {nom: _propre(g[COLONNES_DETAIL].round(2)) for nom, g in detail.groupby("methode", sort=False)},
    }


@app.get("/api/sante")
def sante() -> dict:
    """Pour la surveillance et le HEALTHCHECK du conteneur : les tables de la chaîne sont lisibles."""
    cfg, table, _ = _tables()
    return {"etat": "ok", "annee_reference": cfg["annee_reference"], "provinces": int(table["province"].nunique())}


@app.get("/api/etat")
def etat() -> dict:
    cfg, table, prevision = _tables()
    ref = table[(table["annee_scolaire"] == cfg["annee_reference"]) & (table["statut"] == cfg["statut_cible"])]
    return {"annee_reference": cfg["annee_reference"], "horizon": cfg["annee_horizon"], "provinces": sorted(ref["province"]),
            "regions": sorted(ref["region"].unique()), "scenarios": sorted(prevision["scenario"].unique()),
            "defauts": {"enseignants": cfg["optimisation"]["enseignants_a_repartir"], "salles": cfg["optimisation"]["salles_a_construire"]},
            "limites": {k: cfg["service"][k] for k in ("enseignants_max", "salles_max", "budget_max_fcfa", "normes_acceptees", "recul_prive_max")}}


class Question(BaseModel):
    messages: list[dict] = Field(..., min_length=1, max_length=40, description="[{role: user|assistant, content: texte}]")


@app.get("/api/assistant")
def assistant_etat() -> dict:
    import threading

    from dcb import assistant
    if assistant.disponible() and assistant._plan_type.cache_info().currsize == 0:
        # le plan type sert aux questions « pourquoi » : préparé en arrière-plan dès l'ouverture de la page
        threading.Thread(target=assistant._plan_type, daemon=True).start()
    return {"disponible": assistant.disponible()}


@app.post("/api/assistant")
def assistant_question(q: Question) -> dict:
    """Assistant : reconnaît la question et répond avec les chiffres et les calculs de l'outil (aucun service extérieur)."""
    from dcb import assistant
    try:
        return assistant.repondre(q.messages)
    except assistant.AssistantIndisponible as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/repartir")
def api_repartir(demande: Demande) -> dict:
    # fonction synchrone : FastAPI l'exécute dans un fil séparé, le solveur ne bloque pas les autres demandes
    if not _CALCULS.acquire(timeout=15):
        raise HTTPException(status_code=503, detail="serveur occupé par d'autres calculs : réessayez dans quelques secondes")
    try:
        return repartir(demande)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    finally:
        _CALCULS.release()


@app.post("/api/repartir.xlsx")
def api_repartir_excel(demande: Demande) -> Response:
    """Le même plan, en classeur Excel : fiche de décision, plan par province, comparaison, hypothèses."""
    from dcb.fiche import classeur
    res = api_repartir(demande)
    contenu = classeur(demande.model_dump(), res, _tables()[0])
    nom = f"plan_repartition_{res['enseignants_utilises']}_enseignants_{res['salles_utilisees']}_salles.xlsx"
    return Response(contenu, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@app.get("/api/donnees/{nom}.json")
def donnees(nom: str) -> FileResponse:
    if nom not in FICHIERS_WEB:
        raise HTTPException(status_code=404, detail="fichier inconnu")
    return FileResponse(WEB / f"{nom}.json", media_type="application/json", headers={"Cache-Control": "public, max-age=300"})


# --- entrepôt : consultation libre, import réservé à l'administrateur ----------------------------------------

def _admin(jeton: str | None) -> str:
    """Le jeton d'administration est fixé par la variable d'environnement DCB_JETON_ADMIN (absent = import fermé)."""
    attendu = os.environ.get("DCB_JETON_ADMIN", "")
    if not attendu or not jeton or not hmac.compare_digest(jeton.removeprefix("Bearer ").strip(), attendu):
        raise HTTPException(status_code=401, detail="jeton d'administration requis")
    return "administrateur"


@app.get("/api/entrepot/types")
def types_donnees() -> dict:
    from dcb import entrepot
    return {k: {"libelle": v["libelle"], "niveau": v["niveau"], "source_habituelle": v.get("source_habituelle", ""),
                "variables": {n: s["libelle"] for n, s in v["variables"].items()}}
            for k, v in entrepot.catalogue().items()}


@app.get("/api/entrepot/lots")
def lots() -> list[dict]:
    from dcb import entrepot
    if not entrepot.ENTREPOT.exists():
        return []
    return entrepot.lots().astype(object).where(lambda x: x.notna(), None).to_dict(orient="records")


@app.get("/api/entrepot/gabarit/{type_donnee}/{annee}")
def gabarit(type_donnee: str, annee: str) -> FileResponse:
    from dcb import entrepot
    if type_donnee not in entrepot.catalogue() or not entrepot._ANNEE.match(annee):
        raise HTTPException(status_code=422, detail="type de données ou année inconnus")
    chemin = Path(tempfile.gettempdir()) / f"gabarit_{type_donnee}_{annee}.xlsx"
    entrepot.gabarit(type_donnee, annee, chemin)
    return FileResponse(chemin, filename=chemin.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


async def _fichier_temporaire(fichier: UploadFile) -> tuple[Path, str]:
    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX_IMPORT:
        raise HTTPException(status_code=413, detail="fichier trop volumineux (5 Mo au plus)")
    suffixe = Path(fichier.filename or "").suffix.lower()
    if suffixe not in (".xlsx", ".csv"):
        raise HTTPException(status_code=422, detail="fichier .xlsx ou .csv attendu")
    descripteur, nom = tempfile.mkstemp(suffix=suffixe)
    os.close(descripteur)  # sous Windows, un fichier ouvert ne peut pas être réécrit
    chemin = Path(nom)
    chemin.write_bytes(contenu)
    return chemin, hashlib.sha256(contenu).hexdigest()


def _lire_borne(entrepot, chemin: Path) -> pd.DataFrame:
    df = entrepot.lire_fichier(chemin)
    if len(df) > LIGNES_MAX_IMPORT:
        raise HTTPException(status_code=413, detail=f"fichier trop long ({len(df)} lignes, {LIGNES_MAX_IMPORT} au plus)")
    return df


def _rapport(r) -> dict:
    return {"accepte": r.accepte, "decoupage": r.decoupage, "decoupage_libelle": getattr(r, "decoupage_libelle", ""),
            "lignes": r.lignes, "annees": r.annees, "bloquants": r.bloquants, "avertissements": r.avertissements,
            "apercu": getattr(r, "apercu", [])}


@app.get("/api/entrepot/donnees/{type_donnee}/{annee}")
def donnees_annee(type_donnee: str, annee: str) -> FileResponse:
    """Les données en vigueur d'une année, dans le format du fichier type (pour les relire ou les corriger)."""
    from dcb import entrepot, territoire
    if type_donnee not in entrepot.catalogue() or not entrepot._ANNEE.match(annee or ""):
        raise HTTPException(status_code=404, detail="Type de données ou année inconnus.")
    ref = territoire.charger()
    dec = ref.en_vigueur(entrepot.rentree(annee))
    try:
        t = entrepot.lire(type_donnee, decoupage=dec, ref=ref)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail="Aucune donnée en vigueur pour ce type.") from e
    if annee not in set(t["annee_scolaire"]):
        raise HTTPException(status_code=404, detail=f"Aucune donnée en vigueur pour {annee}.")
    descripteur, nom = tempfile.mkstemp(suffix=".xlsx")
    os.close(descripteur)
    entrepot.gabarit(type_donnee, annee, Path(nom), ref=ref, decoupage=dec, deja=t)
    return FileResponse(nom, filename=f"donnees_{type_donnee}_{annee}.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/entrepot/retirer")
def retirer(lot: int = Form(...), auteur: str = Form(...), authorization: str | None = Header(None)) -> dict:
    """Retire un lot (administrateur) : la version précédente de ses années refait foi ; rien n'est effacé."""
    from dcb import entrepot
    _admin(authorization)
    try:
        entrepot.retirer(lot, auteur[:80])
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Aucun lot en vigueur n° {lot}.") from e
    return {"lot": lot, "statut": "retire",
            "suite": "Lot retiré. Les résultats affichés ne changent qu'après le recalcul par la chaîne (voir le guide d'exploitation)."}


@app.post("/api/entrepot/controler")
async def controler(type_donnee: str = Form(...), fichier: UploadFile = File(...)) -> dict:
    """Contrôle un fichier sans rien enregistrer (ouvert à tous : sert à préparer un import)."""
    from dcb import entrepot
    chemin, _ = await _fichier_temporaire(fichier)
    try:
        r = entrepot.controler_fichier(_lire_borne(entrepot, chemin), type_donnee)
    except HTTPException:
        raise
    except Exception as e:  # fichier illisible
        raise HTTPException(status_code=422, detail=f"Fichier illisible : {e}") from e
    finally:
        chemin.unlink(missing_ok=True)
    return _rapport(r)


@app.post("/api/entrepot/importer")
async def importer(type_donnee: str = Form(...), auteur: str = Form(...), fichier: UploadFile = File(...),
                   authorization: str | None = Header(None)) -> dict:
    from dcb import entrepot
    _admin(authorization)
    chemin, empreinte = await _fichier_temporaire(fichier)
    try:
        r, lot = entrepot.importer_table(_lire_borne(entrepot, chemin), type_donnee, auteur[:80], fichier.filename or "",
                                         empreinte)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Fichier illisible : {e}") from e
    finally:
        chemin.unlink(missing_ok=True)
    return {**_rapport(r), "lot": lot,
            "suite": (f"lot {lot} enregistré dans l'entrepôt. Les résultats affichés ne changent qu'après le recalcul "
                      "par la chaîne (commande « python -m dcb.pipeline » sur le poste de calcul, voir le guide "
                      "d'exploitation)") if lot else ""}


@app.get("/hors-ligne")
def hors_ligne() -> FileResponse:
    """Tableau de bord autonome (un fichier, sans connexion) : mode dégradé."""
    return FileResponse(TABLEAU_DE_BORD, media_type="text/html")


@app.get("/{chemin:path}")
def interface(chemin: str) -> FileResponse:
    """Application (interface compilée) ; à défaut, le tableau de bord autonome."""
    f = (INTERFACE / chemin).resolve()
    if chemin and f.is_file() and INTERFACE.resolve() in f.parents:
        entetes = ({"Cache-Control": "public, max-age=31536000, immutable"} if chemin.startswith("assets/")
                   else {"Cache-Control": "no-cache"} if chemin == "sw.js" else None)  # mise en cache du navigateur : toujours la dernière version
        return FileResponse(f, headers=entetes)
    if chemin.startswith(("assets/", "api/")):
        raise HTTPException(status_code=404, detail="introuvable")
    if (INTERFACE / "index.html").exists():
        return FileResponse(INTERFACE / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})
    return FileResponse(TABLEAU_DE_BORD, media_type="text/html")
