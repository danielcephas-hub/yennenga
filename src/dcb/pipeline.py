"""Chaîne complète, des fichiers bruts au tableau de bord.

Usage (depuis la racine) : PYTHONPATH=src python -m dcb.pipeline
"""
from __future__ import annotations

import runpy
import sys
import time

ETAPES = [
    ("dcb.extraction", "Extraction des tableaux des annuaires et contrôles internes"),
    ("dcb.ingestion", "Lecture du fichier principal"),
    ("dcb.controles", "Rapprochement annuaires / fichier principal"),
    ("dcb.territoire", "Contrôle du référentiel territorial (communes, découpages)"),
    ("dcb.population_communes", "Population par commune (recensement 2019)"),
    ("dcb.entrepot amorcer", "Entrepôt : données extraites + données ajoutées par les techniciens"),
    ("dcb.carte_scolaire", "Carte scolaire à la commune (enfants 2030, écoles repérées, déplacés)"),
    ("dcb.indicateurs", "Table province × année et indicateurs"),
    ("dcb.indice", "Indice de besoin et robustesse"),
    ("dcb.demographie", "Population de 6 à 11 ans projetée par province"),
    ("dcb.prevision", "Prévision des effectifs et test sur le passé"),
    ("dcb.essai_ml", "Essai d'apprentissage automatique (extension de la note)"),
    ("dcb.optimisation", "Répartition optimisée et comparaison"),
    ("dcb.scenarios", "Grille de scénarios"),
    ("dcb.sensibilite", "Analyses de sensibilité de la répartition"),
    ("dcb.retrospectif", "Test rétrospectif : l'outil face aux répartitions réelles passées"),
    ("dcb.implantation", "Accès à l'école (enfants à plus de 3 km) et sites où construire"),
    ("dcb.post_primaire", "Diagnostic régional du post-primaire"),
    ("dcb.tableau_de_bord", "Tableau de bord autonome (hors ligne)"),
    ("dcb.export_web", "Données de l'application web"),
]

if __name__ == "__main__":
    debut = time.time()
    sautees = []
    for etape, libelle in ETAPES:
        module, *args = etape.split()
        sys.argv = [module, *args]
        print(f"\n{'=' * 78}\n{libelle}  [{module}]\n{'=' * 78}")
        t = time.time()
        try:
            runpy.run_module(module, run_name="__main__")
        except SystemExit as e:  # étape facultative dont les données manquent : on le dit et on continue
            if e.code not in (None, 0):
                print(f"ÉTAPE SAUTÉE : {e.code}")
                sautees.append(f"{module} : {e.code}")
        print(f"-- {time.time() - t:.1f} s")
    if sautees:
        print(f"\nChaîne PARTIELLE exécutée en {time.time() - debut:.0f} s ; étapes sautées :")
        for s in sautees:
            print(f"  - {s}")
        sys.exit(3)
    print(f"\nChaîne complète exécutée en {time.time() - debut:.0f} s")
