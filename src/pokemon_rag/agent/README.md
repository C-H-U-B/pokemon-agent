# Agent Pokémon ADK

Ce package ajoute une couche d'orchestration indépendante du graphe et du client
MCP existants. Il contient un seul agent, `agent.py:root_agent`, qui demande au
modèle de répondre en français.

Le parcours est : utilisateur → agent ADK → LiteLLM → API compatible OpenAI du
serveur configuré → modèle. Par défaut, il s'agit de LM Studio
(`http://localhost:1234/v1`) avec `qwen/qwen3-vl-8b` ; `LLM_BASE_URL`, `LLM_MODEL`
et `LLM_API_KEY` les remplacent (voir `config.py`). Le préfixe `openai/` du nom
LiteLLM indique le protocole utilisé. L'agent reporte ces valeurs dans
`OPENAI_API_BASE` et `OPENAI_API_KEY` avec `setdefault` : des valeurs déjà
présentes dans l'environnement sont conservées, vérifier qu'elles ciblent bien
le serveur voulu avant toute exécution.

L'agent unique dispose désormais de `McpToolset`, qui démarre le serveur Pokémon
en stdio avec le même interpréteur Python. Le filtre expose les douze outils :
`pokemon_evolutions`, `pokemon_level_up_moves`, `pokemon_move_learning_methods`,
`pokemon_machine_moves`, `pokemon_types`, `pokemon_pokedex_identity`,
`pokemon_signature_moves`, `pokemon_base_stats`, `pokemon_particularities`,
`pokemon_rag_search`, `pokemon_search` et `pokemon_moves`. Ils réutilisent SQLite ou le
RAG existant. Les instructions demandent de choisir l'outil adapté et permettent
au modèle de réessayer avec un outil compatible après un refus du guard.
Ce sont des instructions au modèle, sans politique déterministe de reprise.
Ce parcours n'applique pas le grounding du graphe ; il partage avec le client
MCP la règle de justification des filtres (`without_unjustified_filters`). Le
graphe et le client restent disponibles comme première version, non maintenue.

Le callback `before_tool_callback` applique le guard de `tool_guard.py` aux
contraintes reconnues de niveaux, de puissance, de jeux, de formes, de catégorie
et type de capacité, de types de Pokémon, de génération et de classification. Il rétablit
les arguments pour les outils compatibles et bloque les outils incompatibles,
les jeux inconnus ou ambigus et les niveaux ambigus ou invalides. Sans message
utilisateur, il laisse passer l’appel. La reconnaissance des formes conserve
les limites de l’extracteur commun ; plusieurs régions ou formes reconnues
sont refusées au lieu de devenir une absence de forme.
Le guard ne modifie pas le catalogue d'outils de l'agent.
Pour les outils structurés, il charge les alias via le moteur SQLite puis
restaure une espèce explicitement nommée et sa forme reconnue. Il refuse
plusieurs cibles au lieu d'en choisir une ; sans mention reconnue, il n'ajoute
aucun Pokémon. `pokemon_search` ne filtre pas par nom : pour un numéro national
d'une espèce nommée, le refus indique `pokemon_pokedex_identity` et les arguments
requis. Qwen reste responsable du choix et de la reprise de l'outil.
Une recherche ciblée portant déjà un numéro peut être conservée hors de cette
intention d'identité : le guard vérifie le numéro via l'identité de l'espèce
nommée et le restaure si nécessaire, sans calcul de statistiques.
Un numéro national explicite reconnu exige `pokemon_search` : le guard rétablit
`pokedex_number` si le modèle le modifie et refuse un autre outil en indiquant
l'appel requis. `pokemon_pokedex_identity` reste destiné au numéro d'un Pokémon
déjà nommé. Les numéros régionaux ou multiples reconnus sont refusés, sans SQLite
dans le guard. Le guard protège l'appel d'outil ; le texte final n'est contrôlé
que pour les listes entièrement transmises (voir le budget de contexte).
Les nouveaux outils acceptent jeux, formes et niveaux ; le guard conserve leurs
filtres et impose `level-up` avec des bornes de niveau. Les instructions donnent
la convention de direction : Pokémon nommé vers un outil prenant `pokemon`,
propriétés ou numéro sans nom vers `pokemon_search`. Elles exigent le
signalement d'une liste partielle ou d'un catalogue incomplet. Le choix entre
`pokemon_moves` et les outils spécialisés est porté par leurs descriptions.
Voir les
[contrats structurés](../structured/README.md#recherche-pokémon-et-movepool-filtrable-via-mcp).
Pour un classement reconnu, le guard restaure statistique, ordre, mode de
superlatif ou top N et catégorie Méga. Il retire les types inventés et conserve
les types demandés, sans comparer de valeurs. La reconnaissance et ses limites
sont décrites dans les [contraintes](../constraints/README.md).
Une liste simple désactive un `best_only` inventé. Pour `pokemon_moves` et
`pokemon_search`, un `learning_method` proposé alors que la question ne nomme
aucune méthode d'apprentissage est retiré : il réduirait le résultat sans que
l'utilisateur l'ait demandé. Dès qu'un mot de méthode apparaît, la proposition
du modèle est conservée telle quelle ; une formulation implicite hors de ce
vocabulaire peut donc faire retirer un filtre légitime. Les mentions positives de
légendaire et de fabuleux restaurent leurs filtres indépendants ; sans ces mots
dans la question, un filtre légendaire ou fabuleux proposé est retiré. Les cas
négatifs ou alternatifs reconnus restent refusés. Une valeur de remplissage
(`"none"`, `"null"`, chaîne vide…) est retirée de tout argument : Qwen proposait
`talent="none"`, et le moteur refusait toute la recherche. Plus généralement, un
filtre doit être justifié par la question, même avec une valeur valide
(`without_unjustified_filters`, partagé avec le client MCP) : `evolution_stage`
par un mot de stade (« stade », « base », « final », « évolution »…), `talent` par
le mot « talent » ou par sa valeur citée si c'est un vrai talent de la base
(« de type Feu » formait sinon un talent `type_feu`, refusé trois fois de suite), `subgroup` par un sous-groupe reconnu ou le
mot « sous-groupe », `version_group` par un jeu nommé. Sous LM Studio, Qwen
proposait `subgroup="Galar"`, `talent="speed"`, `version_group="ruby"`, ou
`evolution_stage="final"` pour « le fossile le plus rapide », ce qui excluait
Ptéra. Une valeur justifiée mais invalide reste transmise, et le refus du moteur,
dont le texte atteint désormais le modèle, signale la faute de frappe. Sur `pokemon_search` et
`pokemon_moves`, `limit=0` n'est gardé que pour une question de comptage
(« combien », « nombre ») : sur une question de liste, la page vide passait pour
complète et la liste était rédigée de mémoire.
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
manquantes sauf demande. Ces consignes restent une protection par prompt ;
seule l'omission ou la négation d'une ligne d'une liste entièrement transmise est
contrôlée de façon déterministe. Le reste de leur respect par Qwen doit être
vérifié manuellement.
Les outils de capacités renvoient aussi `name_en` ; les groupes de versions
restent des identifiants techniques, sans table de traductions dans la base actuelle.
L'adaptation des résultats ADK masque récursivement les champs `*_en` ou `en` lorsqu'un
champ `*_fr` correspondant est renseigné, sauf demande explicite d'anglais.
Les noms sans traduction française sont conservés ;
les réponses originales du serveur MCP restent inchangées.
Les instructions exigent pour chaque classement le nom français et la valeur
de la statistique, ainsi que le signalement des ex aequo.
Elles interdisent aussi d'écrire un identifiant technique ou un nom de champ,
et de contredire un résultat de mémoire.

`AGENT_INSTRUCTION` ne contient que les règles communes à tous les outils :
faits prouvés, noms français recopiés de la question, contraintes transmises
sans ajout, présentation de la réponse. Les règles propres à un outil ou à un
argument sont dans le catalogue MCP, seul texte proche de l'argument que le
modèle reçoit après abrègement : voir le [guide MCP](../mcp/README.md).
Ces textes orientent la proposition de Qwen sans la garantir ; le guard reste
la protection déterministe.

Un nom rare peut encore être remplacé dans la proposition, par exemple
Gouroutan proposé comme Gourgeist. La question arrive intacte au modèle et
aucun texte du contexte ne contient le nom substitué. Des sondes manuelles à
température 0 montrent que la substitution apparaît avec la liste complète
d'arguments d'un outil, sans qu'un argument en soit seul responsable. Demander
de recopier le nom « tel qu'écrit » ne suffisait pas ; préciser que l'argument
est le nom français recopié de la question l'a supprimée dans ces sondes.
Cette précision est dans l'instruction : la répéter dans la description de
l'argument de chaque outil qui prend un Pokémon dépasserait le budget de requête. Les sondes portent
sur quelques noms et peu d'essais ; le guard continue de réparer ces propositions.

Après une erreur, une entrée manquante ou un résultat vide, l'agent est instruit
de rechercher via un autre outil approprié si les contraintes le permettent,
puis de signaler une information indisponible si aucune source ne répond.
Il ne doit pas compléter de mémoire. Cette règle relève de l'instruction au
modèle, pas d'un grounding déterministe ; son respect réel nécessite une
validation manuelle avec Qwen.

L'extraction précède la comparaison avec la proposition : oubli et contradiction
sont réparés avec la même valeur explicite sur un outil compatible. Les deux
bornes d'un intervalle sont rétablies ensemble, y compris une borne absente,
pour enlever une limite contradictoire inventée. Les types de Pokémon et de
capacités ont des contextes distincts ; une Attaque Spéciale de classement ne
devient pas `damage_class=special`. Les filtres non explicitement reconnus restent
du ressort du modèle, sous réserve des invariants existants des listes/classements
et de la justification des filtres décrite plus haut. Une forme que la question ne
mentionne pas reste conservée : « Shaymin Céleste » désigne une forme sans le mot
« forme ».
Un outil incompatible reçoit une erreur avec `selected_tool` et
`required_arguments` ; le numéro national ajoute `required_tool=pokemon_search`.
Aucun outil n'est changé automatiquement. La proposition n'est modifiée qu'après
validation complète, et reste intacte sur refus. Le guard n'exécute pas de SQL
et ne calcule pas de statistiques ; il conserve les appels au moteur existants
pour le catalogue de noms et la vérification d'une identité nommée.
Pour les CT sans jeu précisé, le moteur réduit le résultat au groupe de versions
le plus récent avec des données locales de CT. L'agent est instruit de préciser
le jeu retenu en français. Cela évite de transmettre toutes les générations,
avec une réduction supplémentaire des résultats destinés au modèle.

## Budget de contexte

Quatre étapes sont distinctes. La **réponse MCP** reste riche et identique pour
tous les clients. L'**adaptation ADK** en retire la copie textuelle. La
**projection** ne garde pour le modèle que les faits utiles à la question. Le
**budget** mesure enfin la requête complète et décide d'une abstention locale.
Les trois dernières vivent dans `context_budget.py` et ne modifient jamais
l'objet reçu du serveur.

La fiche d'un Pokémon nommé est projetée sur les rubriques que la question
désigne, pour trois demandes reconnues par mots : sensibilité à un type
(faiblesses, résistances, immunités), changement de talent (ancien talent et
talents actuels), jeux où le Pokémon est absent. Fiche entière, le modèle
complétait la rubrique demandée par un champ voisin. Hors de ces motifs, ou si
la fiche ne porte aucune des rubriques désignées, elle part entière.

`context_budget.py` retire la copie textuelle des données MCP structurées et
borne chaque résultat destiné à ADK à 3000 octets UTF-8. Les listes sont
réduites avec un signalement explicite et leurs totaux conservés. Un résultat
indivisible trop grand devient une erreur, jamais une absence de données.
Cette adaptation ne change pas les réponses de l'API MCP.
Les recherches Pokémon sont projetées avant le seuil : noms français et valeurs,
numéro national lorsque demandé, comptes, pagination et signal de couverture.
Les types, la génération ou la classification d'une ligne sont transmis quand la
question les nomme et que la recherche ne filtre pas dessus (« les types des
starters ») ; filtrés, leur valeur est commune à toutes les lignes et n'est
transmise que sur demande explicite (« avec leurs types »). Auparavant seuls les
noms arrivaient, la page complète retirait les outils, et le modèle rédigeait le
champ demandé de mémoire.
La liste des exceptions de catalogue et les identifiants techniques sont retirés.
Dans un classement, la valeur de chaque ligne porte le nom français de sa
statistique, par exemple `{"name_fr": "Regieleki", "Vitesse": 200}` : le modèle
n'a pas à relier une clé technique à la question. La réponse MCP garde
`base_stat_value`.
Le movepool filtré de `pokemon_moves` perd ses identifiants techniques et
garde tous les faits de chaque capacité : nom, type, puissance, précision, PP,
catégorie et méthodes, libellées en français pour les quatre méthodes courantes
et pour l'entraînement, seule méthode de Pokémon Champions.
Si la page dépasse le seuil, seuls les faits demandés par la question ou
filtrés par l'appel sont gardés avant toute coupe de lignes ; un movepool
complet tient ainsi par ses noms. La coupe reste signalée par
`context_truncated`, `truncated`, `has_more` et les totaux.
Les movepools perdent leurs IDs et répétitions du jeu unique ; les CT conservent
leur libellé français sans répéter le numéro. Les libellés français des jeux connus
sont ajoutés sans changer l'API MCP. Les seuils restent identiques.

Avant chaque appel, les descriptions d'outils sont abrégées en gardant fermé
le balisage qu'ADK pose autour des textes venus d'un serveur MCP, et la sortie
est limitée à 1024 tokens (`LLM_MAX_OUTPUT_TOKENS`, à relever pour un modèle distant
qui compte sa réflexion dans cette limite). Dans la vue du modèle, les annotations de titres sont
retirées et un argument facultatif décrit comme « type ou null, défaut null »
devient son type simple ; enums, bornes, propriétés, défauts non nuls, arguments
requis et descriptions d'arguments sont conservés. Le schéma MCP n'est pas modifié.
Cette simplification libère de quoi garder le catalogue après un refus du guard,
pour que le modèle puisse réessayer. Au-delà de 13500 octets
d'instructions, messages et schémas sérialisés, ou après quatre appels
dans la même invocation, le callback renvoie une abstention locale. Il ne
supprime aucune contrainte utilisateur. Ce budget en octets est conservateur
pour la fenêtre de 16384 tokens ; ce n'est pas un comptage exact du tokeniseur.

Les classements utilisent `pokemon_search` avec les filtres demandés,
`sort_by`, `sort_order` et `limit`, décrits dans le schéma de l'outil. Un superlatif sans quantité, singulier ou pluriel, utilise
`best_only=true` et doit signaler les ex aequo ; un top N conserve
`best_only=false`. Toutes les Méga utilisent `form_category="mega"`.
Les six statistiques et leur total sont classés en SQL, sans modificateurs
de combat ni calcul du modèle. La taille et le poids se classent de la même façon : le guard
impose `height` pour « le plus grand », « le plus petit » et `weight` pour « le plus lourd »,
« le plus gros », « le plus léger », seulement quand l'adjectif qualifie le Pokémon (« la plus
grande Attaque » reste l'Attaque) ; deux critères dans un même superlatif sont refusés comme ambigus. Les enums et descriptions des nouveaux
arguments restent dans le schéma après l'abrègement des descriptions d'outils.
Une fois une première page structurée complète obtenue, la formulation
reçoit les faits et l'historique sans le catalogue d'outils. Pour un superlatif,
tous les gagnants doivent être présents ; pour un top N, la page demandée suffit.
Les erreurs, les résultats tronqués par ADK et les gagnants manquants conservent
les outils. Le plafond de contexte et le nombre maximal d'appels restent inchangés.
Cela s'applique aussi aux listes simples, aux pages complètes de
`pokemon_moves` et aux réponses complètes des outils d'identité, de types, de
capacités signature, d'évolution et de movepool historiques. Un movepool
indisponible conserve le catalogue.
Chaque abstention locale est journalisée avec sa raison (`request_too_large`
ou `too_many_model_calls`) et les tailles mesurées, et chaque résultat d'outil
avec sa taille MCP et sa taille projetée, sans contenu. Ces lignes passent par
le logger `pokemon_rag.agent.context_budget`.

Une réponse rédigée alors que tous les retours d'outils de la question sont en
erreur (panne ou délai dépassé, refus du guard, résultat inutilisable) est
remplacée par une abstention fixe, journalisée `tool_failure_abstention` : la
consigne interdit déjà de répondre de mémoire, mais le modèle peut l'ignorer.
Une nouvelle tentative d'outil n'est pas bloquée, et un seul résultat valide
suffit à laisser passer la réponse. Le contrôle ne couvre pas une réponse
donnée sans aucun appel d'outil. Le délai d'un appel d'outil est
`MCP_TIMEOUT_SECONDS` dans `config.py` : la première recherche documentaire
charge modèles et corpus, bien au-delà du défaut ADK de 5 secondes.
Une question purement descriptive (« décris », « ressemble », apparence,
habitat, comportement, origine, histoire, sans demande structurée) n'admet que
`pokemon_rag_search` : le guard refuse tout autre outil avec
`documentary_question_requires_search` et désigne la recherche. Si le modèle
rédige sans aucun passage, y compris sans appeler d'outil, sa réponse est
remplacée par la même abstention. La recherche documentaire reste soumise aux
contrôles de contraintes habituels. Une question composée garde ses outils.
Une recherche documentaire vide compte comme l'absence de fait : seule, elle
déclenche la même abstention. Une liste structurée vide reste un fait.
Une réponse qui omet ou nie une ligne d'une liste entièrement transmise
(`pokemon_search` ou `pokemon_moves`, 30 lignes au plus, sans troncature ADK) est
remplacée par la liste construite depuis les données, sans nouvel appel au modèle
(`list_fidelity.py`, journalisé `list_fidelity_replacement`). Qwen retirait le trio
des lacs des légendaires de quatrième génération, même quand le résultat
rappelait « légendaire : oui » (3 fois sur 4) : la preuve ne suffit pas, seule une
vérification de la réponse corrige. Le contrôle est lexical : il voit un nom
absent ou déformé et les négations d'appartenance courantes (« ne sont pas »,
« à tort »), pas toutes les tournures. Les outils sur un Pokémon nommé ne sont
pas contrôlés.
`after_tool_budget` retire `timings` et `execution_time` de la vue du modèle
et les consigne dans l'état de session pour l'interface Web.
Après une recherche documentaire qui a trouvé des passages, le catalogue est
aussi retiré pour la rédaction : catalogue et passages ne tiennent pas ensemble
dans le budget de requête. Une recherche vide ou en erreur le conserve.
Une question qui contient à la fois un mot de description et un fait structuré
(« décris X et donne ses types ») est refusée avant tout appel au modèle, par
un message fixe demandant de poser les deux questions séparément, journalisé
`double_request_refusal` : traitée en un seul échange, elle a donné des types
inventés. La reconnaissance se fait par mots, donc « l'origine du talent de X »
est refusée aussi. Les doubles demandes purement structurées restent traitées.
Pour une double demande que ces mots ne signalent pas (« parle-moi de X et de
ses types »), si aucun outil structuré n'a encore répondu, les outils qui prennent un
Pokémon en argument restent disponibles, sans `pokemon_search` ni
`pokemon_rag_search` : privé de tout outil, le modèle inventait le fait
manquant. Le catalogue est retiré dès que les deux parties sont obtenues.
Une demande composée reconnue ou documentaire conserve le catalogue pour les
autres faits à obtenir ; les champs de ligne explicitement demandés restent
dans la projection de recherche.
Les movepools par niveau et méthodes sans jeu choisissent désormais le dernier
jeu disponible ; une demande historique reconnue conserve `all_versions=true`.
Les faits absents, notamment les niveaux d'évolution, restent inconnus : les
instructions interdisent toute complétion de mémoire. Cette règle n'est pas
un contrôle exhaustif de fidélité de la réponse réelle de Qwen.

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
utilisé auparavant s'est révélé insuffisant, alors avec huit schémas MCP.
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
Le test de découverte ADK vérifie exactement le catalogue des douze outils.

Le budget de requête est passé de 12000 à 13500 octets avec les outils
`pokemon_base_stats` et `pokemon_particularities` : le catalogue réel est passé
de 7953 à 9228 octets, et la marge laissée à une reprise après refus du guard
tombait de 1650 à 400 octets. Les traces Web montrent qu'une requête proche de
la limite consomme environ 3000 tokens sur les 16384 du contexte ; la limite
borne surtout le temps de lecture de la requête par le modèle.

Une question nommant un Pokémon et une statistique, proposée à
`pokemon_search`, est refusée en désignant `pokemon_base_stats` et ses
arguments : sans outil désigné, le modèle n'avait aucune issue et répondait de
mémoire. Les deux nouveaux outils reçoivent le Pokémon et la forme de la
question comme les outils de types et d'identité. Un sous-groupe nommé littéralement dans la question (starter, évolution de starter, starter spécial, fossile,
pseudo-légendaire, bébé, Ultra-Chimère, Paradoxe…) est une contrainte reconnue :
le guard le restaure dans `subgroup`, refuse un outil sans ce filtre, et retire
un filtre légendaire ou fabuleux que la question ne mentionne pas. Ces noms
suffisent aussi à reconnaître un classement sans le mot « Pokémon » (« le
fossile le plus rapide »). `evolution_stage` et `talent` ne sont pas extraits
de la question : le guard ne les restaure pas, et les retire quand la question ne
les justifie pas.

Quand la question nomme un Pokémon, un mot de catégorie (légendaire, fabuleux
ou sous-groupe) n'est plus un filtre de liste mais une propriété interrogée
(« Mewtwo est-il un légendaire ? »). Seul `pokemon_particularities` est alors
accepté, parce qu'il renvoie le sous-groupe ; tout autre outil est refusé en le
désignant. Auparavant aucun outil n'était accepté. Il en va de même d'un type
(« Pikachu est-il de type Électrik ? », « Rondoudou a-t-il toujours été de type
Fée ? ») : la fiche, qui renvoie les types actuels et l'ancien type, l'accepte
sans l'exiger ; tout autre outil est refusé en la désignant, `pokemon_types`
compris, qui ignore l'historique (le modèle l'inventait à partir des types
actuels). Toute autre contrainte de liste (classement,
génération) reste exigée et maintient le refus. Limite : une question qui nomme
un Pokémon et filtre réellement sur un type ou une catégorie (« Quels Pokémon de
type Fée peuvent battre Dracaufeu ? ») n'a aucun outil pour y répondre ; la
fiche du Pokémon nommé est alors acceptée.

Un type d'attaque suit la même règle à une condition de plus : la question doit
porter un mot de sensibilité (`is_type_matchup_question` : craint, faible à,
faiblesse, résiste, immunisé, sensible, vulnérable). « Ectoplasma craint-il les
attaques de type Normal ? » se lit alors dans la fiche, qui renvoie faiblesses,
résistances et immunités, et `pokemon_moves` est refusé en la désignant. Sans ce
mot (« Quelles attaques de type Feu Dracaufeu apprend-il ? »), avec une
catégorie ou une puissance en plus, ou sans Pokémon nommé, le type d'attaque
reste un filtre exigé. « faible » ne compte que suivi de sa préposition : « la
capacité la plus faible » parle de puissance.
Les événements de function call portent la proposition du modèle : ADK en donne
une copie aux callbacks, que le guard corrige. `after_tool_budget`, appelé même
après un refus du guard, consigne donc les arguments réellement exécutés dans
l'état de session (`tool_timings`, champ `executed_arguments`) ; l'interface Web
les affiche et les écrit dans sa trace. La campagne structurée instrumente les
callbacks pour séparer proposition, arguments exécutés, MCP brut et adaptation ADK.
