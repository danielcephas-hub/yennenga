# Sources externes

Une ligne par fichier téléchargé dans `data/external/`.

| Fichier | Source | URL | Date de téléchargement | Licence | Usage |
|---|---|---|---|---|---|
| `datapack/DataPack_DCB_2026/` | Data Pack du challenge (DGESS, INSD, OCHA…) | espace challenge, equation.africadataentry.com | 2026-11-13 | usage réservé au concours | annuaires, tableaux de bord, projections, limites administratives |
| `marches_publics/DGCMEF_Quotidien_4226_2025-09-12.pdf` | DGCMEF, Quotidien des marchés publics n° 4226 du 12 septembre 2025 | https://www.dgcmef.gov.bf/sites/default/files/2025-09/Quotidien%20N%C2%B04226.pdf | 2026-11-15 | publication officielle | coût d'une salle de classe : 5 marchés communaux d'écoles primaires (p. 16, 46, 51, 52, 57), 7,2 à 9,3 M FCFA par salle, médiane 8,6 M |

## Documents de coûts (récupérés le 2026-11-15, `data/external/documents_couts/`)

- `cn_ept_2023_attraction_enseignants.pdf` : T. Traoré (coordonnateur national CN-EPT/BF), *Éléments et mesures d'attraction et de maintien des enseignants au Burkina Faso*, Journée mondiale des enseignants, 6 octobre 2023, Teacher Task Force. URL : https://teachertaskforce.org/sites/default/files/2023-10/06102023_WTD_Global-pathways_Tahirou-Traore.pdf. Page 6 : salaire de base d'un enseignant débutant du primaire (catégorie B1) d'environ 91 103 FCFA par mois ; avec les indemnités (logement, astreinte, spécifique), environ 200 103 FCFA par mois en zone rurale, soit environ 2,40 M FCFA par an, hors cotisations employeur.
- `strategie_nationale_question_enseignante_2020.pdf` : MENAPLN, *Stratégie nationale sur la question enseignante au Burkina Faso* (SNAQUE 2021-2025, validée le 26/11/2020), Planipolis : https://planipolis.iiep.unesco.org/sites/default/files/ressources/burkina_faso_2020_menapln-burkina-faso_strategie-nationale-question-enseignante_fr.pdf. P. 10, tableau 3 : 89 105 enseignants en 2019 (dont 63 369 au primaire). P. 11, tableau 4 : masse salariale 2019 = 357 101 646 milliers FCFA. Soit environ 4,0 M FCFA par enseignant et par an, tous ordres confondus (borne haute retenue).
- `plan_action_snaque_2021_2023.pdf` : plan d'action triennal 2021-2023 de la SNAQUE (Planipolis, même dossier). Coût total de la stratégie 2 584,262 Md FCFA, dont 2 478,676 Md de masse salariale (p. 4).
- `psef_2017_2030_revise_2020.pdf` : PSEF 2017-2030 révisé (novembre 2020), Planipolis : https://planipolis.iiep.unesco.org/sites/default/files/ressources/2020-11-burkina_faso._espoc1_psef_2017-2030_revu_vdef.pdf. Pas de coût unitaire de salle ni de poste explicite trouvé à la lecture automatique.
- `gpe_programme_transformation_2025.pdf` : Banque mondiale / GPE, document d'évaluation de projet (rapport PADHI01062, 2025), globalpartnership.org. Composante 1.1 : 20 complexes scolaires urbains, 400 blocs de trois salles et 40 préscolaires pour 102 M USD (p. 17) : coût global, non ventilable par salle.
- Les cinq documents ont été téléchargés le 2026-11-15 avec le navigateur, depuis les sites indiqués.

## WorldPop (téléchargé le 2026-11-15, `data/external/worldpop/`, avec l'accord de l'utilisateur)

- `bfa_t_05_2030_CN_100m_R2025A_v1.tif` (52 529 441 octets) et `bfa_t_10_2030_CN_100m_R2025A_v1.tif` (52 521 855 octets) : population de 5-9 et 10-14 ans en 2030, deux sexes, grille de 100 m contrainte aux zones bâties, WorldPop Global2 R2025A (université de Southampton). URL : https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/2030/BFA/v1/100m/constrained/. Licence CC BY 4.0 (WorldPop, à citer). Sert uniquement à répartir les enfants à l'intérieur de chaque commune ; les totaux restent ceux de l'INSD.
