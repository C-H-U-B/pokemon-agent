# Exécution des tests

Depuis la racine du projet, avec l'environnement `langgraph-agent` :

```powershell
conda run -n langgraph-agent python -m pytest -m "not real_data and not llm and not models"
conda run -n langgraph-agent python -m pytest -m "real_data and not models and not llm"
conda run -n langgraph-agent python -m pytest -m models
conda run -n langgraph-agent python -m pytest -m llm
```

La suite légère utilise un catalogue SQLite en mémoire pour le routeur et le
parseur. Elle interdit l'accès aux bases du projet et l'initialisation des modèles
de recherche. Les bibliothèques Python restent nécessaires, mais aucun modèle
ni corpus n'est téléchargé. Les tests de résolution sur la vraie base sont dans
`integration/test_name_resolution.py`. Les marqueurs `real_data`, `models` et `llm`
décrivent des prérequis distincts ; `long` reste disponible pour la durée.

Un test `xfail(strict=True)` documente un défaut connu du parseur rapide :
la perte d'un jeu inconnu. Il ne constitue pas une réussite. Après correction,
son succès inattendu impose de retirer xfail. Les bornes de niveau sont couvertes
par des tests ordinaires, y compris les intersections et les intervalles impossibles.

# Évaluation factuelle

```powershell
conda run -n langgraph-agent python benchmarks/benchmark_graph.py --output traces/review-001.json
conda run -n langgraph-agent python benchmarks/review_answers.py traces/review-001.json
```

Le benchmark nécessite les vraies données et LM Studio. Il exporte les réponses
complètes de dix cas avec une grille de référence dans `answer_references.json`.
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
restent explicitement en attente. Le contrôle structuré compare les champs de S01
et la liste complète des évolutions, indépendamment du verdict du LLM. Le texte
final reste à relire même si les données structurées sont correctes. Aucun second
LLM n'est utilisé comme juge. Les autres cas du benchmark restent des contrôles
de pipeline, sans note factuelle implicite.
