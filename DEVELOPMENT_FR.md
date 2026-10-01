# Notes de développement

🇬🇧 [English version](DEVELOPMENT.md)

Ce document retrace l'évolution du projet Pokémon RAG au fil du
développement. Il ne cherche pas à présenter une architecture finale
figée : il conserve les principales étapes, les problèmes rencontrés,
les expérimentations et les décisions qui ont progressivement façonné le
système.

## 1. [Feature] Point de départ : expérimenter un RAG local

Le projet a commencé comme une expérimentation autour d'un pipeline de
Retrieval-Augmented Generation exécuté localement.

Pokémon a été choisi comme domaine de travail parce qu'il combine
naturellement deux types d'informations :

-   un corpus documentaire important, notamment via Poképédia ;
-   des données fortement structurées, disponibles notamment via
    PokéAPI.

Le domaine est suffisamment grand pour faire apparaître de vrais
problèmes de retrieval, tout en restant facile à vérifier manuellement.

L'objectif initial était donc de construire un système capable de
répondre à des questions détaillées à partir de Poképédia, avec des
modèles locaux servis par LM Studio.

## 2. [Feature] Construction du corpus Poképédia

La première étape a consisté à télécharger et nettoyer les pages
Poképédia afin de constituer un corpus local exploitable.

Le pipeline général est progressivement devenu :

``` text
Poképédia
    ↓
Téléchargement
    ↓
Pages brutes
    ↓
Nettoyage
    ↓
Documents structurés
    ↓
Découpage en chunks
    ↓
ChromaDB
```

Le corpus représente plus d'un millier de documents et plusieurs
dizaines de milliers de chunks.

Dès le nettoyage, il est apparu important de conserver la structure des
articles. Les documents indexés gardent donc des informations permettant
notamment d'identifier le Pokémon, le document source et la section
d'origine.

Cette décision s'est révélée importante par la suite, lorsque le
retrieval a commencé à exploiter directement la structure des sections.

## 3. [Feature] Premier pipeline de retrieval

La première architecture RAG combinait recherche sémantique et recherche
lexicale :

``` text
Question
   ↓
Recherche vectorielle
   +
BM25
   ↓
Reciprocal Rank Fusion
   ↓
CrossEncoder
   ↓
Contexte
   ↓
LLM
```

La combinaison des embeddings, de BM25 et d'un reranker a donné de
meilleurs résultats qu'une recherche vectorielle seule.

Cependant, les premiers essais ont montré qu'obtenir des chunks
individuellement pertinents ne garantissait pas encore un contexte
fiable.

Deux problèmes sont rapidement devenus importants :

1.  des résultats provenant du mauvais Pokémon pouvaient être récupérés
    ;
2.  un chunk pertinent pouvait ne contenir qu'une partie de
    l'information nécessaire.

## 4. [Feature] Limiter la recherche au Pokémon concerné

Lorsqu'une question mentionne explicitement un seul Pokémon, une
recherche globale peut récupérer des passages concernant d'autres
Pokémon utilisant un vocabulaire similaire.

Une règle stricte a donc été ajoutée :

> Lorsqu'un seul Pokémon est identifié sans ambiguïté, le retrieval
> reste limité à ce Pokémon.

Cette contrainte est conservée lors des éventuelles nouvelles recherches
effectuées par le système.

Le comportement général est devenu :

``` text
Un Pokémon identifié
        ↓
Recherche limitée à ce Pokémon

Aucun Pokémon identifié
        ↓
Recherche globale

Plusieurs Pokémon ou ambiguïté
        ↓
Traitement adapté au contexte
```

Cette étape a réduit une source importante de contamination du contexte.

## 5. [Feature] Exploiter la structure des sections

Les articles Poképédia sont organisés en sections et sous-sections. Une
information peut être répartie sur plusieurs chunks appartenant à une
même section logique.

Le retrieval a donc évolué pour tenir compte de cette structure.

Lorsqu'un résultat pertinent est sélectionné, le système peut retrouver
les autres chunks appartenant exactement à la même section, plutôt que
de simplement prendre les chunks voisins dans l'index.

L'objectif est de reconstruire un contexte cohérent :

``` text
Résultat pertinent
      ↓
Identification de sa section
      ↓
Expansion de la section
      ↓
Contexte documentaire complet
```

Cette évolution a amélioré la cohérence du contexte fourni au
générateur.

## 6. [Feature] Grounding et mécanisme de retry

Une réponse produite à partir d'un contexte récupéré peut malgré tout
introduire une information absente des sources ou contredire celles-ci.

Un contrôle de grounding a donc été ajouté après la génération.

Il distingue plusieurs situations :

``` text
PASS
CONTRADICTION
UNSUPPORTED
INSUFFICIENT
```

Cette étape a également conduit à introduire un mécanisme de retry.
Selon le type d'échec, le système peut tenter une nouvelle génération ou
rechercher un meilleur contexte.

Cette expérimentation a cependant fait apparaître une distinction
importante :

> Une réponse peut être parfaitement ancrée dans son contexte sans pour
> autant répondre correctement à la question.

## 7. [Feature] Expérimentation autour de la suffisance du contexte

Pour traiter ce problème, une étape séparée de vérification de la
suffisance du contexte a été expérimentée.

L'idée était de distinguer deux questions :

``` text
Grounding
→ La réponse est-elle supportée par le contexte ?

Suffisance
→ Le contexte contient-il réellement ce qu'il faut pour répondre ?
```

En pratique, cette nouvelle validation pouvait elle-même produire des
faux positifs et ajoutait un appel supplémentaire au modèle local.

Cette étape a renforcé une idée qui deviendra importante pour la suite
du projet : ajouter des validations LLM ne corrige pas nécessairement un
problème situé plus tôt dans la chaîne de retrieval.

## 8. [Architecture] Améliorer la représentation utilisée pour la recherche

Une partie des erreurs de retrieval provenait de la représentation des
chunks dans l'index.

Le système a donc été modifié pour distinguer :

-   le texte source, conservé pour être fourni au générateur ;
-   une représentation enrichie, utilisée pour les embeddings et la
    recherche.

La représentation de recherche contient davantage de contexte
structurel, notamment l'identité du Pokémon et la position du passage
dans l'article.

Cette séparation permet d'améliorer la recherche sans polluer le texte
documentaire finalement transmis au LLM.

## 9. [Architecture] Limites du RAG pour les données structurées

Au fil des tests, certaines questions se sont révélées mal adaptées au
RAG.

Des demandes concernant par exemple :

-   une évolution ;
-   des capacités apprises à certains niveaux ;
-   des CT disponibles dans une version ;
-   une méthode d'apprentissage ;

correspondent davantage à des requêtes relationnelles qu'à de la
recherche documentaire.

Faire passer systématiquement ces questions par le RAG ajoutait
plusieurs risques :

-   retrieval incomplet ;
-   mauvaise section ;
-   filtrage approximatif par le LLM ;
-   perte d'informations présentes dans des tableaux ;
-   latence inutile.

Le projet a donc commencé à évoluer d'un RAG pur vers une architecture
hybride.

## 10. [Feature] Introduction des données PokéAPI

Les données PokéAPI ont été téléchargées et importées dans SQLite.

L'objectif n'était pas de reproduire toute la structure de PokéAPI dans
le code applicatif, mais de disposer localement d'une source
relationnelle suffisamment complète pour répondre de manière
déterministe aux questions structurées.

Au cours de cette étape, le schéma importé a été progressivement
complété lorsque certaines relations nécessaires n'étaient pas encore
disponibles localement.

Cette phase a également montré l'intérêt de valider le schéma réel de
PokéAPI plutôt que de compenser ses particularités dans les couches
supérieures du système.

## 11. [Feature] Intégration du Pokédex personnalisé

En parallèle, un tableur bilingue est utilisé pour stocker des
informations spécifiques au projet qui ne sont pas directement
disponibles dans PokéAPI.

Il contient les espèces du Pokédex national ainsi que les formes
pertinentes pour le projet et diverses informations complémentaires.

Un mapping explicite avec PokéAPI a été ajouté afin de relier sans
ambiguïté les lignes du tableur aux entités de la base officielle.

Cette étape a permis de préparer la fusion entre les données
personnalisées et les données PokéAPI.

## 12. [Architecture] Passage à une base SQLite unifiée

À un moment du développement, le runtime utilisait à la fois SQLite et
le tableur via Pandas.

Cette organisation créait deux chemins d'accès différents aux données
structurées.

L'architecture a donc été simplifiée autour d'une seule base :

``` text
PokéAPI
   ↓
Base intermédiaire
   │
   ├──── Données du Pokédex personnalisé
   ↓
pokemon.db
```

Le tableur reste une source de construction, mais n'est plus consulté
directement à l'exécution.

La règle est désormais simple :

> Les requêtes structurées du runtime passent par `pokemon.db`.

Cette unification réduit les dépendances du runtime et fournit une
interface unique pour les données structurées.

## 13. [Feature] Création du moteur de requêtes structurées

Le système ne laisse pas le LLM générer du SQL librement.

À la place, une question structurée est transformée en une opération
sémantique contrainte, puis validée par Python avant l'exécution d'une
requête SQL prédéfinie.

Le principe est :

``` text
Question
   ↓
Interprétation
   ↓
Plan structuré validé
   ↓
Fonction SQL prédéfinie
   ↓
Résultat déterministe
```

Les premières familles de requêtes concernent les évolutions et les
capacités, notamment l'apprentissage par niveau, les CT et les méthodes
d'apprentissage.

Ce choix conserve la compréhension du langage naturel tout en évitant la
génération arbitraire de SQL.

## 14. [Bug fix] Stabilisation des évolutions et des formes

Les évolutions ont constitué l'une des premières parties complexes du
moteur structuré.

Les données peuvent dépendre d'une forme, d'une version, d'un objet,
d'un niveau ou d'autres conditions.

Plusieurs problèmes ont été découverts au cours de cette phase,
notamment autour de la distinction entre :

-   l'espèce ;
-   la forme du Pokémon ;
-   la version du jeu.

Le moteur a progressivement été corrigé pour conserver ces notions
séparées et éviter qu'une règle associée à une forme particulière ne
soit appliquée à une autre.

Cette phase a aussi servi à renforcer les tests de régression du moteur
structuré.

## 15. [Feature] Extension aux requêtes sur les capacités

Le moteur structuré a ensuite été étendu aux principales questions
portant sur l'apprentissage des capacités.

Il peut notamment traiter :

``` text
capacités apprises par niveau
CT
méthodes d'apprentissage
```

Cette étape a confirmé que les données PokéAPI étaient plus adaptées que
le RAG pour ce type de questions.

Elle a également permis d'identifier et de corriger plusieurs hypothèses
faites initialement sur le schéma relationnel.

## 16. [Feature] Apparition des trois routes d'exécution

À ce stade, l'architecture a pris une forme plus générale avec trois
chemins :

``` text
                     Question
                        │
                     Routeur
              ┌─────────┼─────────┐
              │         │         │
        STRUCTURED      RAG     HYBRID
              │         │         │
         pokemon.db  Poképédia   combinaison
```

**STRUCTURED**

Utilisé lorsque la réponse peut être obtenue directement depuis les
données relationnelles.

**RAG**

Utilisé lorsque la réponse nécessite du contenu documentaire, explicatif
ou contextuel.

**HYBRID**

Utilisé lorsque les deux sources peuvent contribuer à la réponse.

Cette séparation constitue un changement important par rapport au RAG
initial : le système ne cherche plus à faire résoudre toutes les
questions par le même pipeline.

## 17. [Architecture] Refactorisation de la structure du projet

Avec l'augmentation du nombre de composants, le projet a été réorganisé
autour d'un package `src/pokemon_rag`.

Les responsabilités ont été séparées entre plusieurs ensembles :

``` text
graph/       orchestration et routage
structured/  interrogation de pokemon.db
rag/         retrieval et validations documentaires
scripts/     construction et ingestion des données
tests/       régressions
```

Les chemins vers les données, les bases et les index ont également été
centralisés.

Cette refactorisation a permis de clarifier la séparation entre :

-   construction des données ;
-   runtime ;
-   tests.

## 18. [Performance] Premier travail ciblé sur les performances

Une fois les principales routes fonctionnelles, les mesures de temps ont
montré que SQLite n'était pas le principal goulot d'étranglement.

Les requêtes SQL s'exécutaient généralement en quelques dizaines de
millisecondes, tandis que certains appels aux modèles locaux prenaient
plusieurs secondes.

Le premier composant ciblé a été le routeur.

**Fast Router**

Un routeur déterministe a été ajouté devant le routeur LLM.

Son principe est volontairement conservateur :

``` text
Question
   ↓
Fast Router
   ├── décision certaine → route directe
   └── incertitude       → routeur LLM
```

Les questions structurées suffisamment explicites peuvent ainsi être
dirigées vers `STRUCTURED` sans appel au modèle.

Le routeur LLM reste disponible comme fallback pour les questions
ambiguës, documentaires ou hybrides.

Sur les cas structurés simples, cette modification a réduit le temps du
routage de plusieurs secondes à quelques dizaines de millisecondes.

## 19. [Performance] Fast Parser pour les requêtes structurées

Après l'optimisation du routeur, les mesures ont montré que le principal
coût restant sur une requête structurée simple venait du parser
sémantique.

Un Fast Parser déterministe a donc été ajouté devant le parser LLM.

L'architecture devient :

``` text
Question
   ↓
Fast Router
   ↓
Fast Parser
   ├── plan certain → SQL
   └── incertitude  → parser LLM → SQL
```

Le Fast Parser ne cherche pas à comprendre toutes les formulations
possibles.

Il prend uniquement la main lorsqu'il peut identifier de manière
suffisamment sûre l'opération et ses paramètres. Dans les autres cas, le
comportement LLM existant est conservé.

Cette approche poursuit le même principe que le Fast Router : réserver
les modèles aux situations où leur capacité d'interprétation apporte
réellement quelque chose.

## 20. [Architecture] Suppression du contrôle de suffisance séparé

Le contrôle du contexte avant génération ajoutait un appel au modèle et
faisait en partie doublon avec le contrôle de fidélité effectué après la
réponse. Il a été retiré des chemins documentaires et hybrides.

Le contrôle après génération décide alors si la réponse peut être
acceptée, si une nouvelle recherche est nécessaire ou si la réponse doit
être régénérée. Les tests du graphe vérifient que ces reprises restent
limitées et que la recherche conserve le Pokémon ciblé.

## 21. [Performance] Chargement de la recherche à la demande

Importer les modules du graphe déclenchait le chargement du corpus et
des modèles de recherche, même lorsque la requête ou le test ne les
utilisait pas.

Cette initialisation a été déplacée au premier accès réel à la recherche
documentaire. Les traitements structurés et les tests utilisant des
dépendances simulées évitent ainsi ce coût.

## 22. [Bug fix] Séparation des budgets de reprise

Un compteur commun limitait les nouvelles recherches et les
régénérations. Une recherche supplémentaire pouvait donc empêcher la
correction ultérieure de la réponse.

Les deux mécanismes ont reçu des budgets indépendants, chacun autorisant
une reprise. Les tests de régression vérifient qu'ils peuvent
s'enchaîner sans provoquer de boucle. Une décision de contrôle non
reconnue arrête le traitement.

## 23. [Bug fix] Distinguer contexte insuffisant et réponse incomplète

Le contrôle de fidélité pouvait accepter une réponse cohérente avec les
sources alors que celles-ci ne permettaient pas réellement de répondre à
la question. Ses consignes et les vérifications Python ont été
renforcées pour examiner explicitement la suffisance du contexte et les
affirmations non étayées.

Une réponse pouvait aussi omettre des informations pourtant disponibles.
La décision INCOMPLETE a été ajoutée pour déclencher une régénération
dans ce cas, sans relancer inutilement la recherche documentaire.

## 24. [Feature] Mise en place des benchmarks

Des benchmarks séparés ont été ajoutés pour évaluer la recherche
documentaire, le routage et le contrôle de fidélité, puis un benchmark
du graphe complet a relié ces vérifications.

Pour la recherche, les questions ont été rédigées à partir de sections
réelles du corpus, avec une source attendue pour chaque cas. Pour le
contrôle de fidélité, des contextes synthétiques permettent d'isoler la
décision du modèle de la qualité de la recherche.

Le benchmark du graphe vérifie les chemins structurés, documentaires et
hybrides, ainsi que le rejet des demandes multiples. Il distingue une
réponse structurée produite directement d'une réponse générée soumise au
contrôle de fidélité.

Les durées observées sur le graphe complet ont motivé l'ajout de mesures
par étape pour localiser les coûts de traitement.

## 25. [Feature] Suivi des exécutions et de leurs performances

La durée globale d'une requête ne permettait pas d'expliquer sa lenteur.
Une trace par exécution a été ajoutée au graphe pour relier le parcours
suivi, les reprises, la décision finale et le temps passé dans chaque
étape.

Les traces sont enregistrées en JSONL et un script les agrège pour
comparer les parcours et repérer les requêtes lentes. Les premières
observations ont confirmé le poids des appels aux modèles par rapport à
l'exécution SQL et à la construction du contexte.

## 26. [Feature] Mesure de la consommation des modèles

La durée d'un appel ne suffisait pas à distinguer une réponse longue
d'un ralentissement du modèle. Les traces ont donc été enrichies avec
les volumes de tokens et le débit des appels de génération, de contrôle
et de régénération.

Le débit est calculé sur la durée totale de l'appel : il inclut le
traitement du prompt et ne mesure pas seulement la production du texte.
Le script d'analyse exploite ces informations tout en conservant la
lecture des anciennes traces.

## 27. [Bug fix] Alignement du routeur sur les opérations disponibles

Le routeur envoyait les questions sur les types, talents et statistiques
vers STRUCTURED, alors que le moteur ne proposait pas d'opération pour y
répondre.

Les règles rapides et le prompt ont été alignés sur les opérations
disponibles : évolutions, capacités par niveau, capacités par machine et
méthodes d'apprentissage. À cette étape, les autres questions ciblées
passent par la recherche documentaire. Les présentations générales
conservent le chemin hybride, qui utilise le profil issu du tableur.

Les tests et les attentes du benchmark ont été adaptés à ce
comportement.

## 28. [Bug fix] Abstention après échec du grounding

Une réponse rejetée par le grounding pouvait encore être affichée après
épuisement des retries.

Un nœud d'abstention remplace désormais cette réponse par un message
indiquant que les sources ne permettent pas de répondre de manière
suffisamment fiable. La décision et la justification du checker restent
disponibles pour le diagnostic.

## 29. [Bug fix] Gestion des erreurs de traitement

Une panne de recherche ou de génération pouvait interrompre le graphe
avant la sauvegarde de sa trace.

Les nœuds sont maintenant protégés pour conserver l'état déjà acquis et
identifier l'étape en échec. La fonction `run_graph()` gère également
les erreurs du moteur LangGraph. Le terminal, le batch et le benchmark
utilisent cette entrée commune.

En cas de panne, le système retourne un message explicite et tente de
sauvegarder la trace. Une erreur du checker est distinguée d'un contexte
insuffisant, ce qui évite de relancer inutilement la recherche
documentaire. Les délais réseau des clients LLM ont aussi été rendus
explicites.

## 30. [Bug fix] Sauvegarde des traces non bloquante

Une erreur d'écriture du fichier de traces ne doit pas empêcher de
retourner une réponse déjà produite.

La sauvegarde est désormais protégée : la réponse et la trace restent
disponibles en mémoire, et le résultat de l'écriture est signalé
séparément. L'erreur est journalisée sans nouvelle tentative
automatique, pour éviter de dupliquer une écriture partielle.

## 31. [Bug fix] Cumul des métriques des tentatives

Les retries remplaçaient les mesures précédentes par celles du dernier
appel, ce qui sous-estimait le coût du traitement.

Un historique conserve maintenant les mesures de chaque tentative. La
finalisation cumule les durées et les tokens des appels instrumentés de
génération, de grounding et de régénération, puis recalcule les débits à
partir des totaux.

Les consommations inconnues sont signalées plutôt que comptées comme
zéro. L'affichage et le script d'analyse ont été adaptés tout en
conservant la lecture des anciennes traces.

## 32. [Architecture] Isolation des tests et évaluation factuelle

Les tests rapides dépendaient parfois de la vraie base ou des modèles
locaux. Les tests du routeur et du parseur utilisent désormais un petit
catalogue SQLite en mémoire. Les marqueurs `real_data`, `models` et
`llm` permettent de sélectionner les tests selon leurs prérequis.

Le benchmark du graphe a aussi été complété par des références
factuelles issues des sources locales. Il exporte les réponses avec une
grille de relecture portant sur l'exactitude, la complétude et les
affirmations non étayées. Un comparateur vérifie les champs structurés
du cas de référence sur les évolutions de Pikachu.

Le verdict PASS du contrôle de fidélité ne suffit donc plus à compter
une réponse comme factuellement correcte.

Dans la continuité de ce travail, un test attendait CONTRADICTION alors
que son contexte n'excluait pas la méthode proposée par la réponse. Le
classement UNSUPPORTED du modèle était donc défendable.

Le contexte a été précisé pour rendre la contradiction explicite. Un cas
séparé vérifie l'ajout d'une condition absente des sources. Cette
distinction a été validée avec le modèle local, sans modifier le prompt.

## 33. [Bug fix] Correction des intervalles de niveaux

Le Fast Parser s'arrêtait à la première borne reconnue. Une demande «
après le niveau 20 mais avant le niveau 40 » pouvait ainsi perdre sa
limite supérieure.

Il collecte désormais les contraintes avant de calculer leur
intersection : cette demande produit les bornes 21 à 39. Les limites
inclusives sont également prises en charge, les intervalles impossibles
sont rejetés et les formulations partiellement comprises sont laissées
au parseur LLM.

Des tests de régression vérifient que les contraintes de niveau sont
conservées.

## 34. [Feature] Extension des requêtes structurées au Pokédex personnalisé

Le Pokédex personnalisé contient des données qui peuvent être restituées
directement, sans génération LLM : types, numéro national, génération
d'introduction et capacités signature.

Le moteur structuré a été étendu à ces demandes, avec un routage adapté
et une restitution directe des données. Les noms français ou anglais et
les formes explicitement nommées sont pris en charge.

Les réponses signalent les valeurs absentes et conservent les
annotations des sources. Ces données ne permettant pas de filtrer par
jeu, ce filtre est refusé. Les tests et les références factuelles du
benchmark couvrent les nouvelles opérations.

## 35. [Bug fix] Conservation des contraintes de jeu

Le parseur rapide pouvait ignorer un jeu inconnu et répondre toutes
versions confondues.

Il détecte désormais les mentions explicites de jeu non reconnues et le
traitement les rejette avant le recours au LLM, pour conserver la
contrainte de la question. Des tests de régression vérifient que la
contrainte de jeu est conservée.

## 36. [Feature] Exposition des capacités du projet via MCP

Pour utiliser le projet depuis des clients compatibles MCP, un serveur
expose les opérations structurées et la recherche documentaire sous
forme d'outils typés. Il réutilise le moteur existant et le pipeline de
recherche sans dupliquer la logique métier.

La recherche peut porter sur tout le corpus ou être limitée à un
Pokémon. Elle retourne des passages et leurs références de source.
Les outils appellent directement les composants sous-jacents, sans
passer par les contrôles et les reprises du graphe.

Un client découvre les outils disponibles et leurs schémas, puis confie
à Qwen le choix d'un outil et de ses arguments à partir de la question.
Il exécute cet outil via MCP et transmet le résultat à Qwen pour
formuler une réponse en français. Cette première boucle permet ainsi
au modèle de choisir entre données structurées et recherche
documentaire.

L'intégration a été validée sur des questions mobilisant ces deux
sources.

## 37. [Bug fix] Séparation des diagnostics RAG du protocole MCP

Au premier appel documentaire, l'initialisation RAG écrivait ses
diagnostics sur stdout, également utilisé par les messages MCP.

Ces diagnostics et les barres de progression sont désormais dirigés
vers stderr. Un test de régression avec une collection et des modèles
simulés vérifie que l'initialisation laisse stdout vide et conserve
les informations de diagnostic.

## 38. [Feature] Questions successives dans une session MCP

Le client ouvrait un nouveau serveur pour chaque question, ce qui empêchait
de conserver les ressources de recherche déjà chargées entre les appels.

Le terminal accepte désormais plusieurs questions dans une même session.
Le serveur, le catalogue d'outils et le client LLM sont réutilisés ; chaque
question reste indépendante. Un contexte réutilisable est aussi disponible
en Python, tandis que l'appel ponctuel conserve son fonctionnement.

Les ressources sont fermées à la sortie, en cas d'erreur ou d'annulation.
Des tests simulés vérifient cette fermeture et la réutilisation de la session.
Le gain de latence sur les modèles réels reste à mesurer.

## 39. [Bug fix] Arrêt explicite après une panne du routeur

Une panne du routeur déclenchait une recherche documentaire globale et son
diagnostic disparaissait de l'état du graphe. Le Pokémon ciblé pouvait ainsi
être perdu sans signalement.

Les erreurs de routage rapide, d'appel au modèle et de validation interrompent
désormais le traitement avant la recherche. Le diagnostic est conservé dans
l'état et les traces, ainsi que le Pokémon déjà validé. Le repli documentaire
après une sortie valide reste distinct de cette gestion des pannes.

Des tests simulés vérifient la conservation du scope, la trace du diagnostic
et l'absence d'appel aux étapes suivantes après une panne.

## 40. [Bug fix] Contrôle des contraintes avant un appel MCP

Le client MCP et le moteur structuré doivent interpréter les mêmes mentions de
forme, de jeu et de niveau. Le dossier `constraints` rassemble désormais leurs
règles d'extraction déterministes, sans accès aux données ni appel au modèle.

Le moteur conserve la validation des plans et l'accès à SQLite ; le client
conserve la réconciliation des arguments avant l'appel d'outil. Le guide du
module précise cette séparation et les limites de reconnaissance, pour ne pas
confondre extraction partagée et validation complète d'une demande.

Le client rétablit les filtres reconnus et refuse les contraintes non résolues
ou incompatibles avec l'outil. Les intervalles « entre les niveaux » sont reconnus,
et le moteur associe Tonnerre à son identifiant interne `thunderbolt` sans changer
la langue de l'interface. Les tests déterministes couvrent la réconciliation ;
la validation complète avec Qwen reste à effectuer. Les restrictions sur les
questions documentaires générales sont décrites dans le guide MCP.

## 41. [Architecture] Séparation des validations MCP

Les scénarios qui utilisent réellement Qwen sont regroupés dans `tests/long`,
séparément des parcours client simulés. Un test d'intégration du serveur vérifie
la découverte des outils et une requête structurée via stdio sans génération LLM.
Cette séparation permet de choisir une validation selon ses dépendances réelles.

## 42. [Architecture] Introduction d'un agent ADK local

ADK est introduit pour expérimenter une couche d'orchestration supplémentaire
sans remplacer les composants métier existants. Qwen reste le modèle qui génère
le texte ; ADK définit l'agent et ses instructions ; MCP est le protocole qui
expose les capacités du projet aux clients.

La première implémentation se limite volontairement à un seul agent répondant
en français, avec Qwen local via LiteLLM et l'API compatible OpenAI de LM Studio.
L'endpoint est explicite pour éviter qu'une configuration OpenAI externe détourne
les appels. Les versions ADK et LiteLLM validées localement sont déclarées dans
les dépendances du projet.

L'agent ne possède encore aucun outil. Son accès aux capacités existantes par
MCP est différé à une intégration distincte. Le graphe, le client et le serveur
MCP restent disponibles ; SQLite, Chroma, le moteur structuré, le RAG et le
grounding conservent leurs responsabilités.

## 43. [Feature] Connexion de l'agent ADK aux types Pokémon via MCP

Le function calling ADK/LiteLLM/Qwen a d'abord été validé manuellement avec
un outil Python simple, sans MCP. L'agent a ensuite été connecté au serveur
Pokémon par `McpToolset`, en limitant les outils visibles à `pokemon_types`.

La découverte échouait car l'initialisation MCP prenait environ 9,2 secondes,
au-delà du délai ADK de 5 secondes. Le diagnostic a identifié l'import immédiat
de `pokemon_rag.rag.retrieval`, et notamment de `sentence_transformers`, comme
cause principale. Cet import est désormais effectué uniquement dans l'outil
RAG : les outils structurés démarrent sans charger ce module lourd.

L'initialisation mesurée après correction est d'environ 1,7 seconde sur la même
machine. Ces mesures ont motivé le chargement différé, sans devenir des seuils
de test. La découverte de `pokemon_types` par `McpToolset` et le parcours complet
Qwen → ADK → MCP → `pokemon_types` → réponse ont été validés manuellement.
Les tests conservent des frontières distinctes : protocole stdio, découverte
ADK, function calling et parcours complet.

## 44. [Feature] Guard déterministe des niveaux dans l'agent ADK

Un callback avant l'appel d'outil réutilise l'extraction commune des contraintes
pour restaurer les bornes numériques dans `pokemon_level_up_moves`. Il bloque
les niveaux ambigus ou invalides et les outils qui ne peuvent pas les respecter.
Cette première protection porte uniquement sur les niveaux, sans remplacer
les contrôles du graphe ou du client MCP.

La détection `level_explicit` exige désormais un nombre en plus du mot niveau,
pour laisser passer une demande générale comme « en montant de niveau ».
Des tests unitaires avec le contexte ADK simulé vérifient ces décisions sans LLM.

## 45. [Feature] Extension du guard ADK aux jeux et aux formes

Le guard réutilise désormais aussi les groupes de versions et les formes
régionales reconnus par l'extracteur commun. Il rétablit ces arguments lorsque
l'outil les accepte, remplace les valeurs incorrectes proposées par le modèle
et bloque les outils incompatibles. Les jeux inconnus ou ambigus sont refusés.

Les tests unitaires couvrent ces contraintes et la combinaison jeu/niveaux,
sans appel au modèle. La reconnaissance des formes conserve les limites de
l'extracteur partagé ; le guard ne modifie pas le catalogue d'outils exposé.
