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

`ruff check .` signale les erreurs réelles (imports inutilisés, noms indéfinis,
redéfinitions) selon la configuration de `pyproject.toml`. Il n'appelle aucun
modèle. Aucun formatage n'est imposé : ne pas lancer `ruff format` sur le dépôt.

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
marqueur manquant pourrait donc laisser passer un appel. Les fonctions SQL de
`structured/query_engine.py` font exception : ce module n'importe aucun client
LLM, ce que vérifie `unit/test_pokedex_queries.py` dans un interpréteur neuf.
Le repli vers un modèle ne peut venir que de `structured/query_parser.py`. Les bibliothèques Python
restent nécessaires. Les tests de résolution sur la vraie base sont dans
`integration/test_name_resolution.py`. Les marqueurs `real_data`, `models` et `llm`
décrivent des prérequis distincts ; `long` reste disponible pour la durée.

| Modification | Premier sous-ensemble à inspecter |
| --- | --- |
| Routage ou parsing | `unit/test_router.py`, `unit/test_query_parser.py`, `unit/test_query_validation.py` |
| Opération Pokédex | `unit/test_pokedex_queries.py`, puis tests d'intégration de données concernés |
| Rubrique calculée de la fiche (types, talents d'immunité, historique, objets, jeux) | `unit/test_particularity_derived_facts.py`, puis `integration/test_particularity_derived_facts_real_db.py` |
| Reprises ou erreurs terminales | `integration/test_graph_retry_policy.py`, `integration/test_graph_errors.py` |
| Retrieval ou grounding | `unit/test_retrieval_logic.py` (dont nom de scope normalisé, initialisation unique, mesures de l'outil de recherche), `unit/test_grounding_logic.py` |
| Traces et coûts | `unit/test_metrics.py`, `unit/test_tracing.py` |
| Client MCP | `integration/test_mcp_client.py`, puis `long/test_mcp_client_e2e.py` exécuté par l'utilisateur |
| Contraintes MCP | `unit/test_mcp_constraint_preservation.py` : extraction et réconciliation sans LLM |
| Fidélité des listes | `unit/test_list_fidelity.py`, puis `integration/test_adk_stat_rankings.py` (réponse simulée qui omet des lignes, remplacée) |
| Guard ADK | `unit/test_adk_tool_guard.py` : callback et vrais extracteurs, contexte et outils ADK simulés, sans LLM ni serveur MCP |
| Extracteur de contraintes (jeux, formes) | `unit/test_structured_constraint_guard.py`, puis `integration/test_constraint_vocabulary.py` : tous les noms français de la base, aucun ne doit produire de jeu ni de forme |
| Sessions Web | `unit/test_web_request_sessions.py` : runner ADK simulé ; questions indépendantes, historique affiché conservé, suppression des sessions après succès ou erreur ; temps d'outil et tokens du panneau, démarrage anticipé du serveur d'outils |
| Serveur MCP | `integration/test_mcp_server.py` : vrai transport stdio et outil structuré, sans Qwen |
| API HTTP | `unit/test_api.py` : vraie application FastAPI et vraies fonctions d'outils, moteur simulé ; les onze routes structurées, 404 ou 400 sur refus du moteur, 422 hors schéma, 503 pour une base absente |
| Abstentions de l'agent ADK | `unit/test_adk_context_budget.py`, puis `integration/test_adk_stat_rankings.py` (vrai runner, modèle simulé) : réponse sans résultat d'outil exploitable remplacée, catalogue retiré après des passages, mesures hors de la vue du modèle |
| Alias d'espèces du Pokédex | `integration/test_pokedex_species_aliases.py` : vraie base, appels métier/MCP directs sans parseur LLM ; formes par défaut et noms français des capacités |
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

`integration/test_adk_mcp_toolset.py` vérifie la découverte exacte des douze outils
via le vrai serveur stdio, sans appel d'outil ni LLM. Il contrôle aussi le
catalogue tel que le modèle le reçoit après abrègement : premier paragraphe non
coupé, direction annoncée, valeurs fermées exposées, outils cités par
l'instruction existants. Il ne dit rien du choix effectif de Qwen. Sa mesure
de budget ignore le balisage qu'ADK ajoute dans le vrai flux :
`integration/test_adk_stat_rankings.py` vérifie donc, avec le vrai runner et un
modèle simulé, qu'une question longue atteint le modèle sans abstention locale.
Le même fichier vérifie qu'une petite page de `pokemon_moves`, y compris après
réparation par le guard, arrive à la formulation avec tous ses faits, qu'un
movepool complet est listé sans coupe silencieuse et qu'un refus du guard
laisse le catalogue disponible pour la reprise.
`unit/test_adk_context_budget.py` couvre la projection : champs techniques
retirés, faits conservés, réduction aux faits demandés avant toute coupe,
valeur de classement nommée par sa statistique, vue simplifiée des schémas,
balisage ADK fermé et journalisation des abstentions. Le test stdio officiel
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
conda run -n langgraph-agent python -m pytest tests/integration/test_mcp_client.py -q -p no:cacheprovider
conda run -n langgraph-agent python -m pytest tests/long/test_mcp_client_e2e.py -q -p no:cacheprovider --junitxml=traces/mcp-e2e.xml -o junit_family=legacy
```

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

Ils vérifient huit des douze outils (sans `pokemon_search`, `pokemon_moves`,
`pokemon_base_stats` ni `pokemon_particularities`), les filtres de jeu et de niveau, une forme régionale
et la recherche documentaire globale ou ciblée. Le rapport JUnit conserve la question, l'outil,
ses arguments, son résultat et la réponse pour relecture. Le succès de ces tests
ne garantit pas la fidélité du texte généré : le client n'applique pas le contrôle
de grounding du graphe et aucun LLM juge n'est utilisé ici.

## Contraintes et serveur MCP

Les tests unitaires de contraintes vérifient les filtres restaurés, les refus
et l'intervalle « entre les niveaux 10 et 20 ». Ils appellent la réconciliation
directement : ils ne prouvent pas à eux seuls le comportement complet de `ask`.

```powershell
conda run -n langgraph-agent python -m pytest tests/unit/test_mcp_constraint_preservation.py tests/integration/test_mcp_client.py -q -p no:cacheprovider
conda run -n langgraph-agent python -m pytest tests/integration/test_mcp_server.py -q -p no:cacheprovider
```

Le test serveur nécessite la base locale et le SDK MCP compatible. Il découvre
les douze outils et appelle réellement `pokemon_types` pour Pikachu et Nigirigon,
puis vérifie qu'une espèce inexistante produit une erreur MCP, sans Qwen ni recherche RAG.
Il utilise `asyncio.run` et ne nécessite pas `pytest-asyncio`.

`unit/test_particularity_derived_facts.py` couvre les rubriques calculées de la fiche sur une
base en mémoire (produit des types, talents d'immunité, anciens talents et statistiques, objets,
Gigamax, jeux sans ce Pokémon, table absente) ; `integration/test_particularity_derived_facts_real_db.py`
vérifie des faits connus et des invariants sur toutes les lignes de la vraie base, et échoue sur une
base construite avant le second lot de CSV.
`integration/test_pokedex_search_movepool.py` vérifie le moteur avec SQLite réel
et un catalogue temporaire contrôlé : filtres croisés, catégorie indépendante
de la puissance NULL, formes, sélection des versions avant filtrage, absence
d'union historique, déduplication et pagination. Un jeu récent à méthode unique
vérifie qu'une méthode ou des niveaux demandés retiennent le dernier jeu qui les
propose, sans changer de jeu pour un filtre de type ni assouplir un jeu explicite. Les cas `real_data` vérifient
Relicanth, les fabuleux de troisième génération, Frappe Atlas et les formes
d'Arceus sur la base locale, ainsi que la présence au catalogue de toutes les
formes par défaut (Xerneas parmi les légendaires de sixième génération, Mimiqui, Morpeko).
Le test serveur appelle aussi `pokemon_search` et `pokemon_moves` via stdio,
et distingue une erreur de filtre d'une liste vide, sans LLM. Les guards ADK et
MCP simulés vérifient la conservation des filtres des nouveaux outils.

Le même catalogue temporaire vérifie les six tris statistiques, le total SQL
(avec un total stocké volontairement faux), les NULL, les Méga avec leurs
propres statistiques, les ex aequo paginés et les top N combinés aux filtres.
Les cas réels contrôlent notamment les minima partagés et les classements Méga.
Le serveur stdio vérifie les enums, les nouveaux arguments et les erreurs de
validation ; les tests de découverte ADK vérifient aussi que le catalogue
reste compatible avec le budget de contexte, sans inférence.
Un test avec la base et le catalogue MCP réels vérifie aussi que les top 10
par Vitesse et total restent complets dans le contexte ADK après adaptation.
`integration/test_adk_stat_rankings.py` exécute aussi le vrai runner ADK avec
un modèle simulé, le vrai MCP et la vraie base. Il reproduit des arguments
inventés et un tri absent, puis vérifie leur correction et la formulation
sans abstention de budget, pour une Méga et un top 10. Aucune inférence.
Il couvre aussi le superlatif pluriel avec ex aequo et l'instrumentation de la
campagne structurée : proposition, exécution, résultat brut et adaptation.
`unit/test_stat_ranking_constraints.py` isole les motifs reconnus, ambiguïtés,
types demandés et distinction entre type de Pokémon et type d'attaque.
`unit/test_structured_e2e_reporting.py` vérifie les helpers du rapport sans
exécuter d'agent : une proposition réparée reste diagnostique, mais un appel
incorrect, un résultat en erreur ou une valeur absente de la réponse échoue.
Les niveaux numériques absents des conditions d'évolution et les noms anglais
ajoutés sont aussi détectés, en utilisant les retours MCP bruts pour les
traductions masquées par ADK. Un nom français contenant un mot anglais n'est
pas un ajout, et un rang de liste sur la ligne suivante n'est pas une valeur
de statistique. Le diagnostic de proposition compare les arguments de Qwen
complétés par les défauts du schéma : un argument omis vaut son défaut. Ces contrôles typés ne constituent pas une
validation exhaustive de toutes les affirmations possibles en langage libre.
`unit/test_explicit_pokemon_constraints.py` injecte un catalogue de noms pour
vérifier substitutions, formes, ambiguïtés, classifications et listes simples.
`unit/test_structured_constraint_guard.py` confronte les contraintes explicites
aux arguments corrects, oubliés et contradictoires, avec un catalogue injecté.
Il couvre les nombres de domaines distincts, types de Pokémon/capacités,
catégories, bornes, régions multiples et titres complets de jeux. Les refus
doivent préserver la proposition d'origine et exposer les arguments requis.
Il vérifie aussi qu'une méthode d'apprentissage absente de la question est
retirée, et conservée dès que la question en mentionne une ; qu'un nom de jeu
contenu dans un nom ou « dans la » ne produit pas de jeu, qu'une région citée
comme lieu ne produit pas de forme, qu'une valeur de remplissage ou un filtre
que la question ne justifie pas (stade, talent, sous-groupe, jeu, légendaire) est
retiré, et que `limit=0` n'est gardé que pour un comptage.
`integration/test_constraint_vocabulary.py` vérifie aussi que chaque sous-groupe
du tableur est reconnu par son nom : un sous-groupe inconnu de l'extraction ne
pourrait pas être justifié. Les trois cas
`moves-*` de la campagne attendent `learning_method` absent, pour qu'une
méthode inventée apparaisse dans le diagnostic de proposition.
`integration/test_mcp_server.py` vérifie aussi guard → vrai MCP stdio → SQLite :
contraintes réparées acceptées par le schéma, résultats effectivement filtrés
et reprise explicite après un refus de recherche par numéro, sans modèle.
`integration/test_explicit_pokemon_and_movepool.py` utilise le catalogue réel et
vérifie les jeux récents, anciens et historiques, sans LLM.
Les tests du vrai runner simulant le modèle couvrent également les listes de
huit et neuf résultats ainsi que les CT d'un Pokémon substitué par Qwen.

La campagne structurée compte 44 cas : types, identité, évolutions (dont deux
gains de niveau sans seuil : une capacité connue, un nombre de pas), capacités,
recherche et classements (statistiques, taille et poids), statistiques et particularités d'un Pokémon nommé,
recherche par sous-groupe, talent et stade d'évolution, un comptage, un
Pokémon inconnu dont la réponse attendue est l'abstention, et des mots
ordinaires qui ne doivent pas devenir des contraintes (nom de jeu dans un nom
de capacité ou d'espèce, « dans la », région citée comme lieu, valeur de
remplissage proposée par le modèle), les trois catégories de starters (stade
de base, évolutions, starters spéciaux), et une liste dont la question demande
un champ (les types des starters). Elle évite les
listes longues, qui allongent la génération sans rien vérifier de plus. Le
rapport et chaque ligne JSONL nomment le modèle et le serveur utilisés.
Pour une évolution, chaque condition renvoyée par l'outil (nombre, nom
français, moment de la journée) doit se retrouver dans la réponse : sans ce
contrôle, une réponse niant une condition passait. Il ne détecte pas une
condition citée puis niée dans la même phrase.
Les autres contrôles de contenu sont eux aussi déduits du résultat de l'outil :
chaque nom d'une liste de dix capacités au plus, le niveau d'une méthode
d'apprentissage, et une négation lorsque l'outil ne renvoie aucune évolution.
Une recherche qui annonce un total sans transmettre de ligne (`limit=0` sur
une question de liste) échoue, sauf pour un cas déclaré `count_only` : sans
ligne, aucun contrôle de contenu ne s'exécutait et une liste inventée passait.
Les termes attendus ignorent le style d'apostrophe ; les termes interdits se
comparent par mot entier. Un nom renvoyé ne compte comme restitué que s'il figure
dans au moins un passage qui ne nie pas son appartenance au résultat (« ne sont
pas des légendaires », « à tort ») : une réponse citait trois légendaires pour
dire qu'ils n'en étaient pas. La campagne importe cette détection de
`agent/list_fidelity.py`, qui l'applique aussi dans l'agent. Le modèle simulé
des tests d'intégration ADK cite les noms reçus, comme une réponse fidèle. Ce sont des contrôles de présence : ils ne détectent
pas un fait ajouté à côté des faits attendus.
`long/test_retrieval_quality.py` attend la section pertinente parmi les trois
premiers passages, et non un mot courant du corpus.
`long/test_adk_documentary_e2e.py` est une campagne séparée de cinq questions
de description : elle charge les modèles de recherche et vérifie que la
réponse s'appuie sur des passages trouvés, ou s'abstient. Ses contrôles
portent sur le déroulement (recherche appelée, passages reçus, refus d'une
double demande), pas sur la fidélité de la réponse : celle-ci se juge
par relecture du rapport `test_results/adk_documentary_e2e.md`, qui place la
réponse en regard des passages renvoyés.
`long/test_adk_particularities_e2e.py` est une campagne séparée de 36
questions sur la fiche d'un Pokémon nommé, une par sorte de fait des rubriques en
texte libre (rangs et records de statistiques, obtention, mise en avant,
movepool, ancien type, différences selon le sexe, rubrique absente) et une par
rubrique calculée depuis PokéAPI (faiblesses, immunité, ancien talent, objet tenu,
jeux sans ce Pokémon, Gigamax). Chaque
cas distingue trois pannes : fiche non demandée, rubrique non reçue, réponse
qui ne restitue pas les termes du tableur. Le sens d'un rang ou la date d'une
mise en avant se jugent par relecture de
`test_results/adk_particularities_e2e.md`.

La campagne `long/test_adk_structured_database_e2e.py` appelle réellement Qwen ;
elle est réservée à l'utilisateur, avec LM Studio, un contexte de 16384 tokens
et `data/pokemon.db`. Elle n'utilise pas le RAG. Son Markdown et son JSONL dans
`test_results` séparent la qualité de proposition Qwen du verdict fonctionnel
après guard, des retours MCP bruts et de la réponse finale.

```powershell
conda run -n langgraph-agent python -m pytest tests/integration/test_pokedex_search_movepool.py tests/unit/test_adk_tool_guard.py tests/unit/test_mcp_constraint_preservation.py tests/integration/test_mcp_server.py tests/integration/test_adk_mcp_toolset.py -q -p no:cacheprovider --tb=short --basetemp=.pytest_tmp_pokedex
```

Le `basetemp` dédié évite les restrictions observées du répertoire temporaire
système et du cache pytest local ; pytest remplace ce répertoire de tests à
chaque exécution. Il contient uniquement les bases temporaires de ces tests.

Le test de Tonnerre appelle `query_structured_data`, dont le parseur peut se
replier vers un LLM. Son marqueur `real_data` ne garantit donc pas une exécution
sans modèle. Commande à exécuter par l'utilisateur avec la base locale et, si le
repli est nécessaire, LM Studio configuré pour le parseur :

```powershell
conda run -n langgraph-agent python -m pytest tests/integration/test_structured_constraint_preservation.py -q -p no:cacheprovider
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
