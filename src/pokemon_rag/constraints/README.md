# Contraintes explicites des questions

`query_constraints.py` rassemble les règles déterministes utilisées par le
[moteur structuré](../structured/README.md), le [client MCP](../mcp/README.md)
et le [guard ADK](../agent/README.md)
pour extraire les formes régionales, groupes de versions et bornes de niveau.
Il utilise uniquement la bibliothèque standard : aucun accès SQLite, appel LLM
ou appel MCP. `__init__.py` ne réexporte actuellement aucune fonction.

## Responsabilité et intégration

Le module décrit ce qu'il reconnaît dans la question. Il ne choisit pas d'outil,
ne valide pas un plan SQL et ne décide pas du message à afficher à l'utilisateur.

- Le moteur structuré appelle les extracteurs depuis ses fonctions `_fast_*`.
  Il fournit les identifiants de groupes de versions connus dans SQLite et
  conserve la responsabilité du parsing, de la validation et de l'exécution.
- Le client appelle `extract_explicit_constraints` depuis `reconcile_tool_call`,
  après le choix de Qwen et avant `session.call_tool`. Il utilise les alias du
  module sans fournir de catalogue SQLite. La réconciliation des arguments et
  les refus sont implémentés dans le client, pas dans ce dossier.
- Un appel direct à un outil du serveur MCP ne passe pas par cette
  réconciliation du client.
- Le guard ADK appelle `extract_explicit_constraints` avant l'exécution d'un
  outil. Il utilise les alias sans catalogue SQLite et conserve dans le package
  `agent` la restauration des arguments et les refus selon l'outil sélectionné.

La résolution des espèces et des capacités reste hors de ce module.
`extract_named_pokemon` reçoit un catalogue d'alias fourni par le
moteur : correspondances exactes après normalisation, frontières de noms,
priorité à un alias complet sur un nom d'espèce qu'il contient. Plusieurs
espèces ou formes détectées sont refusées ; aucune mention ne produit `None`.
L'extracteur conserve séparément l'espèce et la forme et ne déduit aucun nom.
`is_named_identity_question` reconnaît le motif numéro national / identité
Pokédex ; le guard garde la responsabilité du refus d'outil incompatible.
La correspondance interne `Tonnerre` → `thunderbolt` appartient à
`structured/query_engine.py`. L'interface du projet reste française ; les alias
anglais présents dans le code ne constituent pas un contrat d'interface bilingue.

## Contrat des extracteurs

`normalize` retire les accents, uniformise la casse et remplace les séparateurs
par des tirets. Cette normalisation sert à comparer les mentions, pas à produire
un texte destiné à l'utilisateur.

| Fonction | Résultat et limites |
| --- | --- |
| `extract_form(question)` | Une forme parmi `alola`, `galar`, `hisui`, `paldea` si une seule est reconnue ; sinon `None` |
| `extract_stat_ranking_args(question)` | Arguments de tri pour des superlatifs explicites (`moins de Défense`, `meilleure Attaque Spéciale`, `plus rapide/lent`) et top N ; `None` hors motifs reconnus, comparaisons nommées et pagination explicite ; ambiguïtés ou N invalide refusés |
| `reconcile_stat_ranking_args(question, arguments)` | Copie les arguments, restaure le classement reconnu et les types littéraux demandés ; retire un type ou une catégorie Méga inventés ; conserve les autres filtres |
| `extract_national_pokedex_number(question)` | Numéro explicite après numéro/n°/no, dans un contexte Pokémon ou Pokédex ; `None` sans mention reconnue ; `ValueError` pour plusieurs numéros, zéro, une valeur négative reconnue ou un Pokédex régional explicite |
| `has_explicit_game(question)` | Détection heuristique d'un alias ou d'une mention de jeu ; ne prouve pas que le jeu est valide |
| `extract_version_group(question, known_version_groups=None)` | Couple `(groupe, ambiguïté)` ; les alias sont examinés avant les identifiants optionnels fournis par l'appelant |
| `extract_level_bounds(question)` | Couple inclusif `(minimum, maximum)`, avec `None` pour une borne absente ; `None` si la formulation n'est pas entièrement reconnue ; `ValueError` si l'intervalle reconnu est impossible |
| `extract_explicit_constraints(question, known_version_groups=None)` | Objet immuable `ExplicitConstraints` regroupant les résultats ; peut propager la `ValueError` des niveaux |

`ExplicitConstraints` contient `form`, `version_group`, `version_ambiguous`,
`explicit_game`, `level_bounds` et `level_explicit`.

Le numéro national est extrait séparément par les deux clients : il n'est pas
ajouté à cet objet ni utilisé par le parseur du graphe. Par exemple,
« Quel Pokémon numéro 369 du Pokédex national ? » retourne 369, tandis que
« Quel est le numéro national de Lockpin ? » ne contient aucun numéro à chercher.
Le motif ne couvre pas les nombres écrits en lettres ou les numéros isolés.

Les indicateurs de présence permettent de distinguer une mention non résolue
d'une absence de contrainte.

`BASE_STAT_NAMES` centralise les libellés français et identifiants statistiques.
Le moteur conserve les colonnes SQL et tous les calculs. Les deux clients
appliquent la réconciliation de classement uniquement à `pokemon_search`.
Elle distingue top N et superlatif, reconnaît les Méga (et X/Y/Z explicites),
les types monotypes et ne confond pas un type d'attaque avec un type de Pokémon.
Sans quantité explicite, un superlatif singulier ou pluriel conserve tous les
ex aequo (`best_only=true`) ; avec N explicite, `best_only=false` et `limit=N`.
Les formulations « Défense la plus basse » et « PV les plus élevés » sont aussi
reconnues, ainsi que les libellés pluriels d'Attaque et de Défense.
Elle ne calcule ni valeur, ni maximum, ni total. La reconnaissance reste limitée
aux motifs documentés ; les autres contraintes sont traitées comme auparavant.
`reconcile_search_args` ajoute les invariants des listes : pas de `best_only=true`
sans optimum reconnu, et classifications positives indépendantes (`légendaire`
→ `legendary=true`, `fabuleux` → `mythical=true`). Un filtre de l'autre catégorie
inventé par le modèle est retiré. Les négations reconnues et alternatives entre
classifications sont refusées plutôt que traduites en une intersection incorrecte.
`VERSION_GROUP_NAMES_FR` fournit des libellés de présentation des jeux connus,
sans modifier leurs identifiants internes.
`level_explicit` exige un mot de niveau et un nombre dans la question ; une
demande générale « en montant de niveau » ne constitue pas une borne explicite.
`version_ambiguous` couvre aussi une mention de jeu non reconnue, pas seulement
plusieurs groupes possibles. Il n'existe pas d'indicateur équivalent pour les
formes : `form=None` peut signifier absence, forme inconnue ou plusieurs formes.

## Exemples de niveaux et de versions

| Mention | Résultat |
| --- | --- |
| « après le niveau 40 » | `(41, None)` |
| « jusqu'au niveau 30 » | `(None, 30)` |
| « au niveau 30 » | `(30, 30)` |
| « entre les niveaux 10 et 20 » | `(10, 20)` |
| « après le niveau 40 et avant le niveau 50 » | `(41, 49)` |
| « au niveau 20 ou au niveau 30 » | `None` : une alternative n'est pas un intervalle |
| « dans Pokémon Rouge » | `version_group="red-blue"` |

Les jeux sont ramenés aux groupes de versions du modèle de données, pas à une
édition individuelle. La table d'alias couvre actuellement Rouge/Bleu,
Diamant/Perle, Soleil/Lune, Épée/Bouclier et Écarlate/Violet. Elle n'est pas
exhaustive. Des identifiants supplémentaires peuvent être fournis par l'appelant.

## Limites et évolution

Ce parseur repose sur des motifs textuels, sans compréhension générale de la
phrase. Par exemple, le mot « dans » peut signaler un jeu à tort ; plusieurs
formes ne sont pas distinguées d'une absence de forme ; une alternative avec
« ou » ou des nombres restant hors des motifs reconnus empêchent l'extraction
des niveaux. Il ne faut donc pas interpréter `None` comme une autorisation
générale de supprimer un filtre. Les formulations « entre les niveaux X et Y »
et « entre le niveau X et le niveau Y » sont traitées en premier : le premier
intervalle reconnu est retourné sans vérifier les autres contraintes de niveau
de la phrase, ni les alternatives éventuelles qui suivent.

Ajouter ici les règles d'extraction communes, puis vérifier leurs consommateurs.
Garder dans le moteur structuré les accès aux données et la validation des plans,
et dans le client la compatibilité des contraintes avec les outils découverts.
Les régressions concernées sont
[`test_mcp_constraint_preservation.py`](../../../tests/unit/test_mcp_constraint_preservation.py)
et [`test_structured_constraint_preservation.py`](../../../tests/integration/test_structured_constraint_preservation.py).
Les E2E avec Qwen sont dans `tests/long/test_mcp_client_e2e.py` ; leur exécution
relève de l'utilisateur. Voir le [guide des tests](../../../tests/README.md).
