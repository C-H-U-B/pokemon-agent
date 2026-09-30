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

## Chaînes de préparation

| Étape | Script canonique | Entrée → sortie |
| --- | --- | --- |
| Données PokéAPI | `pokeapi/download_pokeapi.py` | CSV distants → `data/pokeapi/raw/` |
| Base intermédiaire | `pokeapi/build_pokeapi_db.py` | CSV → `data/pokeapi/pokeapi.db` |
| Base applicative | `pokeapi/build_pokemon_db.py` | Base intermédiaire + `data/pokedex_particularites.xlsx` → `data/pokemon.db` et vue `custom_pokedex` |
| Corpus brut | `pokepedia/download.py` | API Poképédia → `data/pokepedia/raw/` selon la configuration actuelle |
| Nettoyage wiki | `pokepedia/clean.py` | JSON bruts → Markdown dans `data/pokepedia/cleaned/` |
| Index documentaire | `pokepedia/ingest.py` | Markdown → collection `pokemon_documents` dans `chroma_db/` |

Des fichiers locaux anciens peuvent encore être dans `data/raw/` : leur présence
ne change pas les chemins attendus par les scripts actuels. Ne pas déplacer ni
recréer ces données automatiquement pour réconcilier les emplacements.

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
