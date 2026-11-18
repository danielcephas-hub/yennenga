# Interface Yennenga

Application web (React, TypeScript, Vite, MapLibre GL) servie par `dcb.service`. Elle ne fait aucun calcul propre : elle lit les fichiers produits par la chaîne (`outputs/web/`, via `/api/donnees/…`) et demande les répartitions au service (`/api/repartir`).

```
npm ci            # dépendances (versions figées par package-lock.json)
npm run dev       # développement : http://localhost:5173, les appels /api vont au service local (port 8000)
npm run build     # production : interface/dist, servie par le service
```

Vues :

| Fichier | Vue |
|---|---|
| `VueAccueil.tsx` | accueil |
| `VueCarte.tsx` | carte de la province à la commune |
| `VueRepartition.tsx` | répartition en direct |
| `VueDonnees.tsx` | gestion des données (gabarits, contrôle, import) |
| `VueMethode.tsx` | méthode et limites |
| `Visite.tsx` | visite guidée |
