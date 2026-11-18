# Reproduire les résultats

## Prérequis

- Python 3.13 et les dépendances de `requirements.txt` : `pip install -r requirements.txt`.
- Pour l'application en ligne : Node.js 24 (construction de l'interface) ; Docker pour la mise en ligne.
- Navigateur Chrome ou Edge pour produire la documentation PDF.

Installation, mise en ligne, mise à jour annuelle, sauvegarde : voir `docs/guide_installation_exploitation.md`.
Droits : tous droits réservés (`LICENSE`, `NOTICE`). Le code est publié pour l'évaluation du Data Challenge Burkina 2026 ; toute autre réutilisation demande l'autorisation écrite de l'auteur. Les données ne sont pas couvertes.

## Où placer les données

```
data/raw/                       le classeur principal du challenge (.xlsx), seul dans ce dossier
data/external/datapack/DataPack_DCB_2026/   le Data Pack décompressé
data/external/worldpop/         grilles WorldPop 2030 (adresses dans data/external/SOURCES.md)
```

Sans les grilles WorldPop, la chaîne s'exécute mais saute l'accès à l'école ; elle le signale et sort avec le code 3.

Les données ne sont pas incluses dans cette archive.

## Une commande

Depuis la racine du projet :

```
# Windows (PowerShell)
$env:PYTHONPATH = "src"; python -X utf8 -m dcb.pipeline

# Linux, macOS
PYTHONPATH=src python -X utf8 -m dcb.pipeline
```

La chaîne dure environ 10 minutes (580 s mesurées), dont 4 pour les 75 scénarios de répartition. Elle écrit :

| Dossier | Contenu |
|---|---|
| `data/interim/` | tables extraites et nettoyées, avec leurs fichiers d'écarts |
| `data/processed/` | table province × année, indice, prévisions, répartitions, scénarios, post-primaire par région |
| `outputs/controles/` | rapprochement avec le fichier principal, contrôles du post-primaire |
| `outputs/tableau_de_bord/tableau_de_bord.html` | le tableau de bord (un fichier, sans connexion) |
| `outputs/web/` | données de l'application en ligne |

## Application en ligne

```
cd interface && npm ci && npm run build && cd ..
PYTHONPATH=src python -m uvicorn dcb.service:app --port 8000     # http://localhost:8000
```

Mise en ligne sur un serveur : `deploiement/deployer.sh` (Docker derrière un proxy HTTPS), voir le guide.

## Tests

```
PYTHONPATH=src python -m pytest -q        # 74 tests
```

## Modules (`src/dcb/`), dans l'ordre d'exécution

| Module | Rôle |
|---|---|
| `lecture` | lecture des CSV du Data Pack, conversion des nombres |
| `geo` | référentiel des provinces et des régions, correspondance avec le découpage de 2025, contours |
| `extraction` | tableaux des annuaires par province, contrôles de totaux |
| `ingestion` | fichier principal du challenge |
| `controles` | rapprochement annuaires / fichier principal |
| `territoire` | référentiel territorial versionné : communes, découpages datés, passage d'un découpage à l'autre |
| `population_communes` | population et enfants de 6-11 et 12-14 ans par commune (recensement 2019) |
| `entrepot` | entrepôt des données : import contrôlé de nouvelles données, lots datés, retour arrière |
| `indicateurs` | table province × année et indicateurs (lue dans l'entrepôt) |
| `indice` | indice de besoin, test de robustesse |
| `demographie` | population de 6 à 11 ans projetée |
| `prevision` | prévision des effectifs, test sur le passé |
| `optimisation` | répartition en nombres entiers, comparaison à la répartition proportionnelle |
| `scenarios` | grille de scénarios et scénarios « budget seul » |
| `sensibilite` | analyses de sensibilité de la répartition |
| `essai_ml` | essai d'apprentissage automatique pour la prévision (non retenu) |
| `retrospectif` | test sur le passé : l'outil face aux répartitions réelles 2019→2024 et 2018→2023 |
| `carte_scolaire` | enfants de 6-11 ans par commune en 2030, écoles OpenStreetMap, déplacés |
| `implantation` | accès à l'école (grille WorldPop 100 m) et sites où construire ou rouvrir |
| `export_web` | données de l'application en ligne |
| `fiche` | classeur Excel d'un plan (fiche de décision, plan, comparaison, hypothèses) |
| `documentation` | documentation PDF, chiffres lus dans les sorties |
| `service` | application en ligne : répartition à la demande (contraintes, redéploiement, budget), exports, gestion des données |
| `post_primaire` | diagnostic régional du post-primaire (tableaux de bord DGESS), contrôles |
| `tableau_de_bord` | génération du fichier HTML |
| `depot` | fichiers de dépôt et contrôle avant dépôt |

## Ajouter les données d'une nouvelle année (sans toucher au code)

1. Produire le fichier à remplir : `python -m dcb.entrepot gabarit primaire_province 2025-2026` (fichier Excel dans `outputs/gabarits/`, une ligne par province du découpage en vigueur, onglet d'explications).
2. Le remplir depuis l'annuaire de l'année, puis l'importer : `python -m dcb.entrepot importer FICHIER primaire_province NOM_DE_L_AGENT`. Le fichier est contrôlé (territoires connus, valeurs positives, doublons, totaux, variations inhabituelles) ; il est refusé, avec la liste des corrections à faire, tant qu'une anomalie bloquante subsiste.
3. Relancer la chaîne. La nouvelle année est prise en compte partout (indicateurs, prévision, répartition).

Une erreur ? `python -m dcb.entrepot retirer N NOM` retire le lot N ; la version précédente refait foi. Rien n'est effacé.
Les types de données acceptés sont décrits dans `referentiel/types_donnees.yaml` : en ajouter un ne demande pas de programmation.

## Changement de découpage territorial

Les provinces et régions sont des regroupements de communes décrits dans `referentiel/` (communes, découpages datés, rattachements, variantes de noms). Une province créée, scindée ou renommée = un nouveau découpage déclaré dans ces tables (`Referentiel.nouveau_decoupage`). Les données déposées dans un découpage sont relues dans un autre : exactement quand les provinces se regroupent, au prorata de la population des communes quand une province est scindée (valeurs marquées « estimées »). Des tests automatiques vérifient la création et le renommage d'une province.

## Paramètres

Tout est dans `config.yaml` : normes, pondérations de l'indice, moyens à répartir, coûts unitaires, horizon, grille de scénarios. Modifier une valeur puis relancer la commande suffit à tout recalculer.
