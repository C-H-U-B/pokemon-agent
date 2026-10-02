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
en stdio avec le même interpréteur Python. Le filtre expose les dix outils :
`pokemon_evolutions`, `pokemon_level_up_moves`, `pokemon_move_learning_methods`,
`pokemon_machine_moves`, `pokemon_types`, `pokemon_pokedex_identity`,
`pokemon_signature_moves`, `pokemon_rag_search`, `pokemon_search` et
`pokemon_moves`. Ils réutilisent SQLite ou le
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
Un numéro national explicite reconnu exige `pokemon_search` : le guard rétablit
`pokedex_number` si le modèle le modifie et refuse un autre outil en indiquant
l'appel requis. `pokemon_pokedex_identity` reste destiné au numéro d'un Pokémon
déjà nommé. Les numéros régionaux ou multiples reconnus sont refusés, sans SQLite
dans le guard. La protection porte sur l'appel d'outil, pas sur le texte final.
Les nouveaux outils acceptent jeux, formes et niveaux ; le guard conserve leurs
filtres et impose `level-up` avec des bornes de niveau. Les instructions dirigent
les recherches croisées et comptages vers `pokemon_search`, le movepool filtré
vers `pokemon_moves`, et exigent le signalement d'une liste partielle ou d'un
catalogue incomplet. Les talents sont reportés. Voir les
[contrats structurés](../structured/README.md#recherche-pokémon-et-movepool-filtrable-via-mcp).
Les questions d'apparence, comportement, habitat, origine ou histoire sont
orientées par les instructions vers `pokemon_rag_search`, avec la question
complète et le Pokémon ciblé. Des types ou une identité Pokédex ne sont pas des
preuves de description physique. L'agent doit s'en tenir aux passages retrouvés,
citer leurs sources et signaler une description indisponible s'ils ne suffisent
pas. Ce choix reste réalisé par le modèle, sans routage déterministe ajouté au guard.

Les instructions de réponse privilégient les champs français des outils et
les noms français des jeux, sans traductions anglaises ajoutées sauf demande
explicite. Les identifiants internes restent disponibles pour les appels.
Pour une liste structurée, elles exigent la reprise des seuls noms français
retournés, sans ajout de Pokémon ni complétion d'une page tronquée de mémoire.
Les générations, classifications et exemples de capacités non demandés sont
exclus. Une recherche Pokémon n'atteste aucun nom de capacité : ces noms
nécessitent un résultat de movepool approprié si la question les demande.
La limite de couverture reste signalée brièvement, sans énumérer les formes
manquantes sauf demande. Ces consignes restent une protection par prompt,
sans validation déterministe de la réponse finale ; leur respect par Qwen
doit être vérifié manuellement.
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
avec une réduction supplémentaire des résultats destinés au modèle.

## Budget de contexte

`context_budget.py` retire la copie textuelle des données MCP structurées et
borne chaque résultat destiné à ADK à 3000 octets UTF-8. Les listes sont
réduites avec un signalement explicite et leurs totaux conservés. Un résultat
indivisible trop grand devient une erreur, jamais une absence de données.
Cette adaptation ne change pas les réponses de l'API MCP.
Pour un classement trop volumineux, elle retire d'abord les noms anglais et
identifiants internes répétés, en conservant noms français, formes et valeurs.
Cela permet aux top 10 de la base locale de conserver leurs dix lignes.

Avant chaque appel, les descriptions d'outils sont abrégées sans modifier
leurs paramètres et la sortie est limitée à 1024 tokens. Les annotations de
titres des schémas sont retirées ; enums, bornes, propriétés, valeurs par défaut
et descriptions d'arguments sont conservées. Au-delà de 12000 octets
d'instructions, messages et schémas sérialisés, ou après quatre appels
dans la même invocation, le callback renvoie une abstention locale. Il ne
supprime aucune contrainte utilisateur. Ce budget en octets est conservateur
pour la fenêtre de 16384 tokens ; ce n'est pas un comptage exact du tokeniseur.

Les classements utilisent `pokemon_search` avec les filtres demandés,
`sort_by`, `sort_order` et `limit`. Un superlatif singulier utilise
`best_only=true` et doit signaler les ex aequo ; un top N conserve
`best_only=false`. Toutes les Méga utilisent `form_category="mega"`.
Les six statistiques et leur total sont classés en SQL, sans modificateurs
de combat ni calcul du modèle. Les enums et descriptions des nouveaux
arguments restent dans le schéma après l'abrègement des descriptions d'outils.

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
Le test de découverte ADK vérifie exactement le catalogue des dix outils.
Les événements de function call des E2E ne prouvent pas à eux seuls les arguments
corrigés envoyés au serveur ; cette correction est vérifiée par les tests du guard.
