# Orchestration des réponses

`router.py` choisit le chemin ; `nodes.py` exécute les étapes métier ; `graph.py` relie les étapes, protège leur exécution et finalise les traces.

Utiliser `run_graph({"question": "…"})` pour une exécution applicative. Cette entrée conserve le dernier état disponible si le moteur échoue. Un appel direct au graphe compilé contourne cette protection extérieure.

## Contrats de sortie

- Le chemin structuré peut produire une réponse directement formatée, marquée `DETERMINISTIC`.
- Les réponses générées passent par le contrôle de fidélité. `PASS` indique l'acceptation par ce contrôle, pas une preuve indépendante de justesse factuelle.
- Un contexte insuffisant autorise une nouvelle recherche. Une réponse incomplète, non étayée ou contradictoire autorise une régénération. Ces budgets sont indépendants et limités.
- Après rejet final, le nœud d'abstention remplace la réponse. Une erreur technique suit le chemin d'erreur et conserve un diagnostic distinct.
- `trace_saved` et `trace_save_error` décrivent l'écriture de la trace, pas la validité de la réponse.

## Lors d'un changement

Vérifier le chemin normal, les transitions de reprise et le chemin terminal. Préserver le Pokémon ciblé lors des recherches supplémentaires. Les coûts répétés sont cumulés dans `observability/metrics.py` ; ne pas déduire le coût total du seul dernier appel.

Les tests de transitions et d'erreurs sont dans `tests/integration/test_graph*.py`. Leur nom ne signifie pas nécessairement qu'ils chargent les modèles : consulter leurs marqueurs et [le guide des tests](../../../tests/README.md).
