# Scripts et données locales

Exécuter les scripts depuis la racine, avec le paquet installé dans `langgraph-agent`. Les chemins des ressources sont centralisés dans [config.py](../src/pokemon_rag/config.py).

| Dossier | Rôle |
| --- | --- |
| `pokeapi/` | Télécharger les CSV, construire la base PokéAPI puis la base unifiée avec le tableur |
| `pokepedia/` | Télécharger, nettoyer et indexer les pages dans Chroma |
| `batch/` | Exécuter le vrai graphe, ou l'agent ADK avec `--agent`, sur un fichier de questions |
| `use_gemini.ps1` | Pointer un terminal PowerShell vers le modèle distant de la démo |
| `observability/` | Analyser les traces enregistrées |

Les données et index générés sont locaux. Leur absence ne se corrige pas en lançant automatiquement une reconstruction : le constructeur SQLite et l'ingestion peuvent remplacer les ressources existantes. Une modification du routeur, des tests ou de la documentation n'exige pas de reconstruire les données.

Les scripts de construction sont des outils de préparation, pas une étape de démarrage quotidien. Vérifier leurs destinations et préserver les ressources actives avant une reconstruction volontaire : `build_pokeapi_db.py` et `build_pokemon_db.py` suppriment la base avant de la reconstruire et ne la valident qu'à la fin, et `ingest.py` supprime la collection avant de la remplir. Une interruption laisse une ressource partielle ; copier la base ou l'index avant de lancer. Nommer la copie `<fichier>.avant-<motif>` (`data/pokemon.db.avant-second-lot`) ou, pour le classeur, `pokedex_particularites.<date>.xlsx` : ces deux formes sont ignorées par Git, donc `git add -A` ne les embarque pas.

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

Avec `--agent`, le même lot passe par l'agent ADK, sur le parcours de l'interface Web et avec le
modèle des variables `LLM_*` ; chaque question écrit sa trace dans `traces/web_traces.jsonl`
(appels d'outils, réponse, temps, tokens), où se lit le résultat :

```powershell
conda run -n langgraph-agent python scripts/batch/run_questions.py scripts/batch/questions_agent_risks.txt --agent
```

`questions_agent_risks.txt` regroupe des questions ciblées : chacune est précédée, en commentaire,
de l'erreur qu'elle cherche. Y ajouter une question avec son erreur anticipée plutôt que de
rejouer une liste entière.

### Modèle distant de la démo (payant)

La démo hébergée utilise Gemini par son API compatible OpenAI. `. scripts/use_gemini.ps1` (avec le
point) pose `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` et `LLM_MAX_OUTPUT_TOKENS=2048` dans le
terminal ; sans lui, tout vise le modèle local. La clé n'entre jamais dans le dépôt ni dans une
commande : le script la lit dans la variable d'environnement utilisateur `GEMINI_API_KEY`.

Chaque question posée à ce modèle est facturée sur un crédit prépayé (environ un demi-centime,
mesuré le 8 octobre 2026). Ne demander que des exécutions ciblées, en annonçant leur nombre et ce
qu'elles tranchent ; une vérification sans modèle (sonde du guard, rejeu de traces, test à modèle
simulé) passe avant. Un résultat obtenu avec le modèle local ne vaut pas pour le modèle distant,
et inversement.

Le batch doit être lancé par l'utilisateur, pas par un agent. Demander sa sortie
terminal et les traces du lot pour interpréter les erreurs. L'analyse de traces
existantes, sans inférence, est décrite dans [Performance](../docs/PERFORMANCE.md).
