# Agent Pokémon ADK

Ce package ajoute une couche d'orchestration indépendante du graphe et du client
MCP existants. Il contient un seul agent, `agent.py:root_agent`, qui demande au
modèle de répondre en français.

Le parcours est : utilisateur → agent ADK → LiteLLM → API compatible OpenAI de
LM Studio (`http://localhost:1234/v1`) → `qwen/qwen3-vl-8b` local. Le préfixe
`openai/` du nom LiteLLM indique le protocole utilisé. L'agent définit par défaut
`OPENAI_API_BASE` et la clé factice `OPENAI_API_KEY=lm-studio` avec `setdefault`.
Des valeurs déjà présentes sont conservées : vérifier qu'elles ciblent bien
LM Studio avant toute exécution.

L'agent unique dispose désormais de `McpToolset`, qui démarre le serveur Pokémon
en stdio avec le même interpréteur Python. Le filtre expose les huit outils :
`pokemon_evolutions`, `pokemon_level_up_moves`, `pokemon_move_learning_methods`,
`pokemon_machine_moves`, `pokemon_types`, `pokemon_pokedex_identity`,
`pokemon_signature_moves` et `pokemon_rag_search`. Ils réutilisent SQLite ou le
RAG existant. Les instructions demandent de choisir l'outil adapté et permettent
au modèle de réessayer avec un outil compatible après un refus du guard.
Ce sont des instructions au modèle, sans politique déterministe de reprise.
Ce parcours n'applique ni le grounding du graphe ni la réconciliation des
contraintes du client MCP existant. Ces deux parcours restent disponibles.

Le callback `before_tool_callback` applique le guard de `tool_guard.py` aux
contraintes reconnues de niveaux, de jeux et de formes régionales. Il rétablit
les arguments pour les outils compatibles et bloque les outils incompatibles,
les jeux inconnus ou ambigus et les niveaux ambigus ou invalides. Sans message
utilisateur, il laisse passer l’appel. La reconnaissance des formes conserve
les limites de l’extracteur commun, notamment pour les formes multiples.
Le guard ne modifie pas le catalogue d'outils de l'agent.
Les questions d'apparence, comportement, habitat, origine ou histoire sont
orientées par les instructions vers `pokemon_rag_search`, avec la question
complète et le Pokémon ciblé. Des types ou une identité Pokédex ne sont pas des
preuves de description physique. L'agent doit s'en tenir aux passages retrouvés,
citer leurs sources et signaler une description indisponible s'ils ne suffisent
pas. Ce choix reste réalisé par le modèle, sans routage déterministe ajouté au guard.

Les instructions de réponse privilégient les champs français des outils et
les noms français des jeux, sans traductions anglaises ajoutées sauf demande
explicite. Les identifiants internes restent disponibles pour les appels.
Les outils de capacités renvoient aussi `name_en` ; les groupes de versions
restent des identifiants techniques, sans table de traductions dans la base actuelle.

Après une erreur, une entrée manquante ou un résultat vide, l'agent est instruit
de rechercher via un autre outil approprié si les contraintes le permettent,
puis de signaler une information indisponible si aucune source ne répond.
Il ne doit pas compléter de mémoire. Cette règle relève de l'instruction au
modèle, pas d'un grounding déterministe ; son respect réel nécessite une
validation manuelle avec Qwen.
Pour les CT sans jeu précisé, le moteur réduit le résultat au groupe de versions
le plus récent avec des données locales de CT. L'agent est instruit de préciser
le jeu retenu en français. Cela évite de transmettre toutes les générations,
sans garantir qu'un résultat volumineux ou un historique long tiendra dans le contexte.

## Utilisation manuelle

L'[interface Web Gradio](../web/README.md) réutilise ce même `root_agent` et
conserve uniquement l'historique affiché ; les questions utilisent des sessions
ADK indépendantes sans mémoire des échanges précédents. Elle présente l'activité
et ne remplace ni MCP ni le guard. Son lancement et ses exemples sont décrits
dans le guide Web.

Dans l'environnement Conda `langgraph-agent`, installer le projet avec
`pip install -e .`. Les versions déclarées sont `google-adk==2.10.0` et
`litellm==1.103.2`. LM Studio doit déjà servir `qwen/qwen3-vl-8b` sur le port 1234.
Configurer sa fenêtre de contexte à **16384 tokens** : le contexte de 8192
utilisé auparavant s'est révélé insuffisant avec les huit schémas MCP.
Ce réglage est effectué dans LM Studio, pas dans le code de l'agent.
Les outils structurés nécessitent `pokemon.db` ; la recherche nécessite aussi
le corpus, Chroma et les modèles locaux déjà préparés. Ne pas reconstruire ces
ressources pour lancer l'agent lorsqu'elles sont disponibles.

Depuis la racine du dépôt :

```powershell
conda activate langgraph-agent
adk run src/pokemon_rag/agent
```

Cette commande interactive est réservée à l'utilisateur : envoyer une question
appelle réellement Qwen. Vérifier une réponse en français et transmettre la
sortie ou l'erreur pour valider le parcours complet. Importer ou construire
l'agent ne constitue pas une validation de l'inférence.

Le smoke test existant est également réservé à une exécution manuelle, dans
le même environnement avec LM Studio et Qwen disponibles :

```powershell
python -m pytest tests/long/test_adk_agent.py -q -p no:cacheprovider
```

Ces tests portent les marqueurs `llm`, `long` et `models` et utilisent
`asyncio.run` sans plugin pytest asynchrone. Ils vérifient le témoin `ADK_OK`
et le routage vers les outils de types, d'identité Pokédex, de CT avec version
et de capacités par niveau avec intervalle, avec la base locale disponible.
`tests/long/test_adk_tool_calling.py` isole le function calling avec un outil
Python sans MCP. Transmettre la sortie pytest ; ces contrôles techniques ne
garantissent pas la qualité factuelle des réponses Pokémon.

Les tests `tests/integration/test_adk_mcp_toolset.py` et
`tests/integration/test_mcp_stdio.py` découvrent les outils sans appeler de LLM
ni exécuter de recherche. Le serveur importe le module RAG uniquement lors
d'un appel à `pokemon_rag_search`, pour ne pas retarder l'initialisation MCP.
Le test de découverte ADK vérifie exactement le catalogue des huit outils.
Les événements de function call des E2E ne prouvent pas à eux seuls les arguments
corrigés envoyés au serveur ; cette correction est vérifiée par les tests du guard.
