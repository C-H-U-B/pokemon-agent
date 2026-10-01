# Orchestration des réponses

`router.py` choisit le chemin ; `nodes.py` exécute les étapes métier ; `graph.py` relie les étapes, protège leur exécution et finalise les traces.

Utiliser `run_graph({"question": "…"})` pour une exécution applicative. Cette entrée conserve le dernier état disponible si le moteur échoue. Un appel direct au graphe compilé contourne cette protection extérieure.

## Contrats de sortie

- Le chemin structuré peut produire une réponse directement formatée, marquée `DETERMINISTIC`.
- Les réponses générées passent par le contrôle de fidélité. `PASS` indique l'acceptation par ce contrôle, pas une preuve indépendante de justesse factuelle.
- Un contexte insuffisant autorise une nouvelle recherche. Une réponse incomplète, non étayée ou contradictoire autorise une régénération. Ces budgets sont indépendants et limités.
- Après rejet final, le nœud d'abstention remplace la réponse. Une erreur technique suit le chemin d'erreur et conserve un diagnostic distinct.
- `trace_saved` et `trace_save_error` décrivent l'écriture de la trace, pas la validité de la réponse.

## Erreurs et repli du routeur

Une panne du routage rapide (notamment SQLite), un échec d'appel LLM ou une sortie
invalide retourne `router_mode=ERROR`, `router_error` et `router_error_type`, sans
inventer de route ni de Pokémon. `route_query` conserve le diagnostic dans l'état
et déclenche `processing_error` avant toute recherche ou génération. Un Pokémon
déjà présent dans l'état reste conservé ; sinon, la question originale reste dans
la trace sans prétendre avoir résolu l'entité. Aucune panne n'autorise un repli RAG
automatique : la priorité est de ne pas élargir silencieusement le scope.

Le repli sémantique existant reste permis après une sortie LLM valide : un intent
`PROFILE` dont le nom ne peut être résolu devient `RAG` / `DOCUMENT_SEARCH`.
Ce n'est pas une panne et `router_error` reste nul. Une requête documentaire valide
peut également suivre normalement la route RAG.

La finalisation copie `router_error` dans la trace JSONL, y compris après une
exception inattendue du nœud routeur. La réponse utilisateur reste un message
d'erreur technique générique ; le diagnostic est destiné à l'observabilité.

## Lors d'un changement

Vérifier le chemin normal, les transitions de reprise et le chemin terminal. Préserver le Pokémon ciblé lors des recherches supplémentaires. Les coûts répétés sont cumulés dans `observability/metrics.py` ; ne pas déduire le coût total du seul dernier appel.

Les tests de transitions et d'erreurs sont dans `tests/integration/test_graph*.py`. Leur nom ne signifie pas nécessairement qu'ils chargent les modèles : consulter leurs marqueurs et [le guide des tests](../../../tests/README.md).
