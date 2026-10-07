# Scripts et données locales

Exécuter les scripts depuis la racine, avec le paquet installé dans `langgraph-agent`. Les chemins des ressources sont centralisés dans [config.py](../src/pokemon_rag/config.py).

| Dossier | Rôle |
| --- | --- |
| `pokeapi/` | Télécharger les CSV, construire la base PokéAPI puis la base unifiée avec le tableur |
| `pokepedia/` | Télécharger, nettoyer et indexer les pages dans Chroma |
| `batch/` | Exécuter le vrai graphe sur un fichier de questions |
| `observability/` | Analyser les traces enregistrées |

Les données et index générés sont locaux. Leur absence ne se corrige pas en lançant automatiquement une reconstruction : le constructeur SQLite et l'ingestion peuvent remplacer les ressources existantes. Une modification du routeur, des tests ou de la documentation n'exige pas de reconstruire les données.

Les scripts de construction sont des outils de préparation, pas une étape de démarrage quotidien. Vérifier leurs destinations et préserver les ressources actives avant une reconstruction volontaire : `build_pokeapi_db.py` et `build_pokemon_db.py` suppriment la base avant de la reconstruire et ne la valident qu'à la fin, et `ingest.py` supprime la collection avant de la remplir. Une interruption laisse une ressource partielle ; copier la base ou l'index avant de lancer.

## Chaînes de préparation

| Étape | Script canonique | Entrée → sortie |
| --- | --- | --- |
| Données PokéAPI | `pokeapi/download_pokeapi.py` | CSV distants → `data/pokeapi/raw/` |
| Base intermédiaire | `pokeapi/build_pokeapi_db.py` | CSV → `data/pokeapi/pokeapi.db` |
| Base applicative | `pokeapi/build_pokemon_db.py` | Base intermédiaire + `data/pokedex_particularites.xlsx` → `data/pokemon.db` et vue `custom_pokedex` |
| Corpus brut | `pokepedia/download.py` | API Poképédia → `data/pokepedia/raw/` selon la configuration actuelle |
| Nettoyage wiki | `pokepedia/clean.py` | JSON bruts → Markdown dans `data/pokepedia/cleaned/` |
| Index documentaire | `pokepedia/ingest.py` | Markdown → collection `pokemon_documents` dans `chroma_db/` |
| Export pour une release | `pokepedia/export_index.py` | Collection `pokemon_documents` → `dist/chroma_db/` et `dist/chroma_db.tar.gz` ; ne modifie pas `chroma_db/` |

Les deux scripts PokéAPI partagent la même liste de CSV. Le second lot (`type_efficacy`,
`ability_names`, `pokemon_abilities_past`, `pokemon_stats_past`, `pokemon_items`) alimente les
rubriques calculées de la fiche d'un Pokémon nommé : une base construite sans lui reste lisible,
ces rubriques sont seulement omises. Ajouter un CSV demande de l'inscrire dans les deux listes,
de typer ses colonnes numériques (`INTEGER_NAMES`) et d'indexer sa clé de recherche.

Des fichiers locaux anciens peuvent encore être dans `data/raw/` : leur présence
ne change pas les chemins attendus par les scripts actuels. Ne pas déplacer ni
recréer ces données automatiquement pour réconcilier les emplacements.

Ne jamais publier `chroma_db/` tel quel : ce dossier local peut contenir d'autres
collections et les restes d'anciennes ingestions. `export_index.py` recopie la
seule collection du projet dans un index neuf, sans charger de modèle, crée
l'archive et vérifie qu'elle se rouvre avec tous ses fragments.

Le conteneur Web lit l'index depuis un volume Docker, pas depuis `chroma_db/` :
après une réindexation, recopier l'index avec la commande notée dans
`compose.yaml`, sinon le conteneur continue de servir l'ancien.

Le nettoyage interprète le wiki et conserve des titres structurés. L'ingestion
découpe par section, puis par taille si nécessaire ; elle conserve le texte source
et calcule les embeddings sur une représentation enrichie. Les métadonnées
`pokemon`, `source_file`, `section_path` et `section_chunk_number` relient les
fragments au [retrieval](../src/pokemon_rag/rag/README.md).

Modifier la syntaxe wiki dans `clean.py`, le découpage ou la représentation
d'embedding dans `ingest.py`, les relations SQL et le mapping du tableur dans les
constructeurs PokéAPI. Ne pas compenser une perte à l'ingestion par une règle de
routage ou un prompt de réponse. Une modification de format nécessite d'évaluer
la compatibilité des ressources existantes avant une reconstruction explicitement voulue.

## Exécution et observabilité

Pour exécuter un lot existant :

```powershell
conda run -n langgraph-agent python scripts/batch/run_questions.py scripts/batch/questions.txt
```

Le fichier contient une question par ligne ; les lignes vides et les commentaires commençant par `#` sont ignorés. Ce lot utilise les composants réels du graphe et peut appeler LM Studio et écrire des traces. Pour une validation légère, utiliser plutôt [les tests isolés](../tests/README.md).

Le batch doit être lancé par l'utilisateur, pas par un agent. Demander sa sortie
terminal et les traces du lot pour interpréter les erreurs. L'analyse de traces
existantes, sans inférence, est décrite dans [Performance](../docs/PERFORMANCE.md).
