# Performance : faits et méthode de mesure

## Comportements confirmés dans le code

| Composant | Coût et portée actuels |
| --- | --- |
| Routeur et parseur | Chemin rapide déterministe, puis LLM si le cas n'est pas reconnu ; une requête structurée ne garantit pas zéro appel LLM |
| Retrieval | Initialisation différée, une fois après succès par processus : deux modèles, corpus chargé par lots de 500, index de sections et BM25 en mémoire |
| Recherche vectorielle | Embeddings des documents calculés à l'ingestion ; embedding de la question à chaque recherche |
| BM25 | Scores calculés sur le corpus complet avant filtrage des indices du Pokémon ; le scope limite les résultats, pas ce calcul initial |
| Sections et reranking | Plusieurs évaluations CrossEncoder possibles ; désactiver le reranking principal ne supprime pas le sélecteur de section |
| Client MCP | Le terminal et `open_client` partagent serveur, catalogue et ressources RAG entre questions ; deux appels LLM par question réussie. La fonction ponctuelle `ask` démarre encore un serveur par appel |
| Ingestion | Relit et découpe les documents, recalcule leurs embeddings, remplace la collection Chroma ; pas une mise à jour incrémentale |

La configuration, les points d'entrée et les frontières sont dans
[ARCHITECTURE.md](../ARCHITECTURE.md). Ces observations n'établissent pas à elles
seules quel composant domine la latence sur une machine donnée.

## Règles à préserver

Ne pas initialiser la recherche à l'import d'un module. Ne pas reconstruire une
base ou un index pour accélérer un test applicatif. Garder la représentation
d'embedding cohérente entre ingestion et recherche avant de modifier le modèle.
Préserver les limites de reprise, les scopes et les validations lors d'une optimisation.

Les tentatives instrumentées sont cumulées dans `observability/metrics.py`.
Les tokens concernent la génération, le grounding et la régénération ; ce n'est
pas une comptabilité complète des tokens du routeur ou du parseur. Une consommation
inconnue reste inconnue. Le débit est calculé sur la durée totale des appels,
traitement du prompt compris ; les débits individuels ne s'additionnent pas.

## Mesurer avant de conclure

Comparer avant/après sur les mêmes questions, données, modèles et paramètres.
Distinguer premier appel à froid, appels suivants dans le même processus et appels
MCP redémarrant un serveur. Relever latence, mémoire, nombre de reprises, volumes
de contexte et exactitude ; un gain obtenu en perdant une contrainte n'est pas valide.

L'analyse de traces existantes est sans inférence :

```powershell
conda run -n langgraph-agent python scripts/observability/analyze_traces.py traces/graph_traces.jsonl --top 5
```

Le graphe enregistre les traces dans `traces/graph_traces.jsonl`. Le client MCP
n'émet pas ces traces ; celles de l'interface Web (`traces/web_traces.jsonl`)
ont un autre format, que l'analyseur refuse. Leur absence n'autorise pas l'agent à lancer un benchmark
LLM : fournir la commande à l'utilisateur et attendre ses résultats, conformément
au [guide des tests](../tests/README.md).

## Pistes à mesurer, non implémentées

Un cache des catalogues de noms pourrait éviter certaines lectures SQL répétées
du routeur et du parseur. Une recherche BM25 limitée en amont pourrait réduire le
travail sur le corpus, mais changerait potentiellement ses statistiques et son classement.
Mesurer ces pistes avant de les retenir ; aucune amélioration chiffrée n'est établie ici.

## Comparer les sessions MCP

Le script [benchmark_mcp_sessions.py](../benchmarks/benchmark_mcp_sessions.py)
compare les appels ponctuels et les questions dans une session partagée.
Lancer ce fichier depuis l'IDE avec l'interpréteur Conda `langgraph-agent`.
LM Studio, Qwen, la base et l'index local doivent être disponibles.
Ce script appelle réellement le LLM : son exécution revient à l'utilisateur.

Par défaut, il pose deux fois la même question documentaire par mode, affiche
une progression avec ETA et enregistre les réponses et durées dans un rapport
horodaté `traces/mcp-sessions-*.json`. Le rapport partiel est conservé en cas
d'erreur ; aucun rapport existant n'est écrasé.

Les totaux incluent l'ouverture et la fermeture des sessions. Dans le mode
partagé, l'ouverture est aussi mesurée séparément et la première question
inclut le chargement RAG. Les caches système et le préchauffage du LLM peuvent
influencer les résultats : l'option `--reverse` inverse l'ordre des modes.
`--questions` change le nombre de questions par mode et `--help` décrit les options
sans inférence. Transmettre le rapport JSON et les erreurs éventuelles.
Le gain réel reste à mesurer ; ce script ne juge pas la fidélité des réponses.

Les scripts longs emploient déjà notamment `tqdm`. Conserver une progression
compréhensible avec compteur et ETA lorsque pertinente ; dans un serveur MCP,
les diagnostics doivent aller sur stderr, jamais sur le canal protocolaire stdout.
