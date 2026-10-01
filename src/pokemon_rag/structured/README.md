# Requêtes structurées

`query_engine.py` traduit une question en plan validé puis appelle une fonction SQL prédéfinie. Le parseur rapide couvre les formulations sûres ; le modèle traite les autres formulations. La base utilisée est définie dans `config.py`.

## Interfaces et limites

Les extracteurs de formes, jeux et niveaux sont partagés avec le client MCP dans
[`constraints/query_constraints.py`](../constraints/README.md). Le moteur fournit
les groupes de versions connus depuis SQLite et conserve la validation des plans.
La résolution des espèces et capacités reste ici, notamment la correspondance
de Tonnerre vers l'identifiant interne `thunderbolt`. L'interface reste française.

- `query_structured_data(question)` renvoie un résultat avec `error`. Toujours lire ce champ : `count == 0` peut accompagner une erreur et ne suffit pas à conclure à l'absence de données.
- `execute_plan(plan)` valide le plan ; les fonctions `get_*` sont aussi appelées directement par MCP et peuvent lever une exception.
- Les bornes de niveau sont inclusives dans le plan. « Après le niveau 40 » devient donc un minimum de 41.
- Pour les CT/CS, un jeu omis sélectionne le groupe le plus récent possédant
  des données de machines pour le Pokémon et sa forme, selon `version_groups.order`.
  Le résultat indique `version_group` et `version_selection="latest_available"`.
  Un jeu explicite reste inchangé (`"explicit"`), même si son résultat est vide.
  La disponibilité signifie ici présence de données locales de CT, pas preuve
  exhaustive de présence dans tous les jeux. Les autres opérations restent inchangées.
- Espèce, forme et groupe de versions sont des paramètres distincts. Ne pas remplacer une forme introuvable par la forme de base.
- Les types, l'identité Pokédex et les capacités signature viennent du Pokédex personnalisé. Ces opérations ne prennent pas en charge les filtres par jeu. Une valeur absente reste non renseignée ; les annotations de source sont conservées.
  Lorsque le nom d'espèce n'est pas un nom complet d'entrée, le moteur utilise
  le catalogue PokéAPI pour retrouver `species_id`, puis l'entrée personnalisée
  par défaut. Une forme explicite reste prioritaire ; aucune forme manquante
  n'est remplacée par défaut, et plusieurs entrées possibles restent une erreur.
- La protection contre certaines mentions de jeux inconnus appartient au parseur de questions. Ne pas supposer que les appels directs aux fonctions SQL bénéficient de ce contrôle de langage naturel.

## Ajouter une opération

Vérifier d'abord que les données locales permettent réellement de répondre. Ajouter l'exécution et la validation du plan, puis adapter le parseur, le routeur et le formatage dans `graph/nodes.py`. Si l'opération doit être accessible aux clients MCP, ajouter son outil explicitement : l'exposition n'est pas automatique.

Tester la bonne réponse ainsi que la conservation des filtres et le traitement des données absentes. Adapter les attentes du benchmark et ajouter une référence factuelle vérifiée dans la source, sans la dériver de la réponse générée. Voir [tests/README.md](../../../tests/README.md).
