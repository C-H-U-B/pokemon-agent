# Contraintes explicites des questions

`query_constraints.py` rassemble les règles déterministes utilisées par le
[moteur structuré](../structured/README.md) et le [client MCP](../mcp/README.md)
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

La résolution des espèces et des capacités reste hors de ce module. En
particulier, la correspondance interne `Tonnerre` → `thunderbolt` appartient à
`structured/query_engine.py`. L'interface du projet reste française ; les alias
anglais présents dans le code ne constituent pas un contrat d'interface bilingue.

## Contrat des extracteurs

`normalize` retire les accents, uniformise la casse et remplace les séparateurs
par des tirets. Cette normalisation sert à comparer les mentions, pas à produire
un texte destiné à l'utilisateur.

| Fonction | Résultat et limites |
| --- | --- |
| `extract_form(question)` | Une forme parmi `alola`, `galar`, `hisui`, `paldea` si une seule est reconnue ; sinon `None` |
| `has_explicit_game(question)` | Détection heuristique d'un alias ou d'une mention de jeu ; ne prouve pas que le jeu est valide |
| `extract_version_group(question, known_version_groups=None)` | Couple `(groupe, ambiguïté)` ; les alias sont examinés avant les identifiants optionnels fournis par l'appelant |
| `extract_level_bounds(question)` | Couple inclusif `(minimum, maximum)`, avec `None` pour une borne absente ; `None` si la formulation n'est pas entièrement reconnue ; `ValueError` si l'intervalle reconnu est impossible |
| `extract_explicit_constraints(question, known_version_groups=None)` | Objet immuable `ExplicitConstraints` regroupant les résultats ; peut propager la `ValueError` des niveaux |

`ExplicitConstraints` contient `form`, `version_group`, `version_ambiguous`,
`explicit_game`, `level_bounds` et `level_explicit`. Les indicateurs de présence
permettent de distinguer une mention non résolue d'une absence de contrainte.
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
