# Scripts et données locales

Exécuter les scripts depuis la racine, avec le paquet installé dans `langgraph-agent`. Les chemins des ressources sont centralisés dans [config.py](../src/pokemon_rag/config.py).

| Dossier | Rôle |
| --- | --- |
| `pokeapi/` | Télécharger les CSV, construire la base PokéAPI puis la base unifiée avec le tableur |
| `pokepedia/` | Télécharger, nettoyer et indexer les pages dans Chroma |
| `batch/` | Exécuter le vrai graphe sur un fichier de questions |
| `observability/` | Analyser les traces enregistrées |

Les données et index générés sont locaux. Leur absence ne se corrige pas en lançant automatiquement une reconstruction : le constructeur SQLite et l'ingestion peuvent remplacer les ressources existantes. Une modification du routeur, des tests ou de la documentation n'exige pas de reconstruire les données.

Les scripts de construction sont des outils de préparation, pas une étape de démarrage quotidien. Vérifier leurs destinations et préserver les ressources actives avant une reconstruction volontaire.

Pour exécuter un lot existant :

```powershell
conda run -n langgraph-agent python scripts/batch/run_questions.py scripts/batch/questions.txt
```

Le fichier contient une question par ligne ; les lignes vides et les commentaires commençant par `#` sont ignorés. Ce lot utilise les composants réels du graphe et peut appeler LM Studio et écrire des traces. Pour une validation légère, utiliser plutôt [les tests isolés](../tests/README.md).
