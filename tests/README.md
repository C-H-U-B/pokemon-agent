# Exécution des tests

## Choisir une validation

Lire le test, ses fixtures et ses imports avant de l'exécuter. Un agent ne doit
lancer aucune commande susceptible d'appeler un LLM local ou distant. En cas de
doute, donner à l'utilisateur la commande exacte, ses prérequis, son objectif et
les sorties à transmettre, puis attendre son résultat. Cette règle couvre aussi
les benchmarks, le batch et les appels indirects du routeur ou du parseur.

Commencer par le plus petit ensemble discriminant. Pour un changement purement
documentaire, vérifier d'abord les liens, noms de fichiers et commandes ; la suite
complète n'apporte pas de validation supplémentaire du texte.

Privilégier les invariants, limites, entrées invalides ou ambiguës et interactions
entre composants. Lors d'un bug réel, ajouter une régression qui aurait échoué
avant sa correction. Ne pas recopier l'algorithme dans le test ni considérer une
réponse simplement non vide comme une preuve de justesse. Simuler les frontières
externes pour les erreurs ; réserver les ressources réelles aux contrats qui en dépendent.

Depuis la racine du projet, avec le paquet et les dépendances installés dans
`langgraph-agent`, exemple déterministe ciblé :

```powershell
conda run -n langgraph-agent python -m pytest tests/unit/test_metrics.py -q -p no:cacheprovider
```

Les sélections plus larges ci-dessous sont des commandes disponibles, pas des
certifications d'absence d'inférence. Les deux dernières sont réservées à
l'utilisateur : `models` inclut notamment les E2E MCP également marqués `llm`.

```powershell
conda run -n langgraph-agent python -m pytest -m "not real_data and not llm and not models"
conda run -n langgraph-agent python -m pytest -m "real_data and not models and not llm"
conda run -n langgraph-agent python -m pytest -m models
conda run -n langgraph-agent python -m pytest -m llm
```

La suite légère utilise un catalogue SQLite en mémoire pour le routeur et le
parseur. Elle interdit l'accès aux bases du projet et l'initialisation des modèles
de recherche via ses fixtures. Elle ne bloque pas globalement le réseau ou les
clients LLM : l'isolation de ceux-ci dépend des simulations de chaque test. Un
marqueur manquant pourrait donc laisser passer un appel. Les bibliothèques Python
restent nécessaires. Les tests de résolution sur la vraie base sont dans
`integration/test_name_resolution.py`. Les marqueurs `real_data`, `models` et `llm`
décrivent des prérequis distincts ; `long` reste disponible pour la durée.

| Modification | Premier sous-ensemble à inspecter |
| --- | --- |
| Routage ou parsing | `unit/test_router.py`, `unit/test_query_parser.py`, `unit/test_query_validation.py` |
| Opération Pokédex | `unit/test_pokedex_queries.py`, puis tests d'intégration de données concernés |
| Reprises ou erreurs terminales | `integration/test_graph_retry_policy.py`, `integration/test_graph_errors.py` |
| Retrieval ou grounding | `unit/test_retrieval_logic.py`, `unit/test_grounding_logic.py` |
| Traces et coûts | `unit/test_metrics.py`, `unit/test_tracing.py` |
| Client MCP | `integration/test_mcp_client.py`, puis `long/test_mcp_client_e2e.py` exécuté par l'utilisateur |
| Contraintes MCP | `unit/test_mcp_constraint_preservation.py` : extraction et réconciliation sans LLM |
| Guard ADK | `unit/test_adk_tool_guard.py` : callback et vrais extracteurs, contexte et outils ADK simulés, sans LLM ni serveur MCP |
| Serveur MCP | `integration/test_mcp_server.py` : vrai transport stdio et outil structuré, sans Qwen |
| Résolution de Tonnerre | `integration/test_structured_constraint_preservation.py` : parsing et vraie base |

Les jeux inconnus explicitement mentionnés sont rejetés avant le recours au LLM,
sans supprimer le filtre demandé. Ce comportement et les bornes de niveau
(intersections et intervalles impossibles compris) sont couverts par des tests ordinaires.

## Client MCP : intégration et bout en bout

Pour les contraintes de l'agent ADK, la validation déterministe ciblée est :

```powershell
conda run -n langgraph-agent python -m pytest tests/unit/test_adk_tool_guard.py -q -p no:cacheprovider
```

Elle couvre la restauration et le remplacement des niveaux, groupes de versions
et formes reconnus, les refus d'outils incompatibles et la combinaison jeu/niveaux.
Elle ne valide pas le choix d'outil par Qwen. Les tests ADK réels de function
calling et du parcours MCP restent dans `tests/long`, marqués `llm`, `models`
et `long`, et doivent être exécutés par l'utilisateur.

`integration/test_adk_mcp_toolset.py` vérifie la découverte exacte des huit outils
via le vrai serveur stdio, sans appel d'outil ni LLM. Le test stdio officiel
reste une validation distincte du protocole. Les E2E de `long/test_adk_agent.py`
vérifient le routage vers types, identité, CT avec version et capacités avec
intervalle ; ils nécessitent Qwen local avec un contexte de 16384 tokens et
les données SQLite. Les function calls enregistrés ne suffisent pas à vérifier
les arguments effectivement corrigés par le guard et envoyés au serveur.

`integration/test_mcp_client.py` couvre le parcours question → découverte des
outils → sélection → exécution → réponse. Les tests isolés simulent les frontières
MCP et LLM pour vérifier les erreurs, les formats de résultats, l'interface terminal
et la fermeture des contextes. Ils utilisent les objets du SDK MCP installé.
Ils couvrent aussi plusieurs questions dans une seule session, une découverte
unique des outils, les sorties du terminal et la fermeture après erreur ou annulation.
La mesure réelle des sessions successives est décrite dans
[Performance](../docs/PERFORMANCE.md) et doit être exécutée par l'utilisateur.
La première commande sélectionne les tests simulés ; la seconde appelle Qwen
et doit être exécutée par l'utilisateur. Transmettre la sortie pytest et le rapport
JUnit, en distinguant les erreurs techniques des contraintes métier non respectées.

```powershell
python -m pytest tests/integration/test_mcp_client.py -q -p no:cacheprovider
python -m pytest tests/long/test_mcp_client_e2e.py -q -p no:cacheprovider --junitxml=traces/mcp-e2e.xml -o junit_family=legacy
```

Ces commandes supposent l'environnement `langgraph-agent` déjà activé.
Les scénarios réels sont regroupés dans `long/test_mcp_client_e2e.py`.
Ils démarrent le serveur MCP en sous-processus et utilisent les
vrais outils et Qwen. Ils nécessitent le projet installé dans `langgraph-agent`,
un SDK MCP compatible, LM Studio sur `localhost:1234` avec `qwen/qwen3-vl-8b`,
la base `pokemon.db`, le corpus et les modèles de recherche déjà disponibles.
Ils portent les marqueurs `llm`, `real_data`, `models` et `long` et ne reconstruisent
aucune ressource. Une dépendance absente provoque un échec, pas un succès ignoré.
Le sous-processus utilise le cache Hugging Face en mode hors ligne. Les tests
limitent les appels MCP à 120 secondes et les appels LLM à 90 secondes, sans
reprise HTTP automatique ; la configuration du client applicatif reste inchangée.

Ils vérifient les huit outils, les filtres de jeu et de niveau, une forme régionale
et la recherche documentaire globale ou ciblée. Le rapport JUnit conserve la question, l'outil,
ses arguments, son résultat et la réponse pour relecture. Le succès de ces tests
ne garantit pas la fidélité du texte généré : le client n'applique pas le contrôle
de grounding du graphe et aucun LLM juge n'est utilisé ici.

## Contraintes et serveur MCP

Les tests unitaires de contraintes vérifient les filtres restaurés, les refus
et l'intervalle « entre les niveaux 10 et 20 ». Ils appellent la réconciliation
directement : ils ne prouvent pas à eux seuls le comportement complet de `ask`.

```powershell
python -m pytest tests/unit/test_mcp_constraint_preservation.py tests/integration/test_mcp_client.py -q -p no:cacheprovider
python -m pytest tests/integration/test_mcp_server.py -q -p no:cacheprovider
```

Le test serveur nécessite la base locale et le SDK MCP compatible. Il découvre
les huit outils et appelle réellement `pokemon_types`, sans Qwen ni recherche RAG.
Il utilise `asyncio.run` et ne nécessite pas `pytest-asyncio`.

Le test de Tonnerre appelle `query_structured_data`, dont le parseur peut se
replier vers un LLM. Son marqueur `real_data` ne garantit donc pas une exécution
sans modèle. Commande à exécuter par l'utilisateur avec la base locale et, si le
repli est nécessaire, LM Studio configuré pour le parseur :

```powershell
python -m pytest tests/integration/test_structured_constraint_preservation.py -q -p no:cacheprovider
```

Il vérifie le nom français du plan, le groupe Rouge/Bleu et l'identifiant interne
`thunderbolt`. Transmettre la sortie pytest, y compris tout échec de parsing.

Pour les tests simulés du client, le catalogue doit déclarer les propriétés
réellement acceptées : un schéma réduit à `{"type": "object"}` ne suffit plus
au contrôle de compatibilité. Les E2E enregistrent actuellement le choix brut
de `choose_tool`, avant réconciliation ; leurs assertions sur ce choix ne valident
donc pas directement les arguments corrigés envoyés au serveur.

## Évaluation factuelle


Le benchmark suivant appelle un LLM : commande à faire exécuter par l'utilisateur,
qui transmet ensuite le rapport JSON et la sortie terminal. `review_answers.py`
analyse une relecture existante sans appel modèle ; il ne produit pas cette relecture.

```powershell
conda run -n langgraph-agent python benchmarks/benchmark_graph.py --output traces/review-001.json
conda run -n langgraph-agent python benchmarks/review_answers.py traces/review-001.json
```

Le benchmark nécessite les vraies données et LM Studio. Il exporte les réponses
complètes des cas documentés avec une grille de référence dans `answer_references.json`.
Les références proviennent du corpus local consulté et, pour S01, des lignes 17
et 517 de pokemon_evolution. Elles ne sont pas générées à partir des réponses.
Ce premier lot couvre un socle de faits ; ce n'est pas une garantie exhaustive
de correction de tous les profils ou de toutes les données sources.

Relire chaque réponse face à la source indiquée, sans modifier la réponse ou la
référence du rapport. Renseigner les cinq booléens de `review`, le nom du relecteur
et les notes (faits manquants, contradictoires ou ajoutés). Une négation ne valide
pas un fait simplement parce que les mots-clés sont présents. Pour une abstention,
évaluer son adéquation aux sources et au besoin ; une panne technique ne compte
pas automatiquement comme une abstention appropriée.

`review_answers.py` rapporte les nombres de réponses relues, correctes, complètes,
avec affirmations non étayées et d'abstentions pertinentes. Les cas non relus
restent explicitement en attente. Le contrôle structuré compare les évolutions
de S01 et les informations du Pokédex de S05 à S07, indépendamment du verdict du LLM. Le texte
final reste à relire même si les données structurées sont correctes. Aucun second
LLM n'est utilisé comme juge. Les autres cas du benchmark restent des contrôles
de pipeline, sans note factuelle implicite.
