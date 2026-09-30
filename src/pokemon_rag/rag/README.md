# Recherche documentaire et grounding

## Où intervenir

`retrieval.py` produit les passages ; `grounding.py` juge une réponse déjà générée.
La construction des prompts de réponse appartient à `graph/nodes.py`, la politique
de reprise à `graph/graph.py`. Pour changer le texte indexé ou les métadonnées,
consulter d'abord [l'ingestion](../../../scripts/README.md).

## Flux de recherche

`retrieve(question, pokemon=..., information_need=...)` combine recherche vectorielle
et BM25 par Reciprocal Rank Fusion. Des candidats issus des titres de sections
complètent le pool pour un Pokémon ciblé. Le CrossEncoder reclasse les candidats,
puis le sélecteur conserve la première section selon ce classement et en
reconstruit les fragments exacts. Son score supplémentaire `focus_score` est
actuellement diagnostique : il ne décide pas de la section retenue.

Le top de résultats sert au diagnostic. Le premier résultat porte aussi
`context_results`, utilisé pour construire le contexte envoyé au générateur
et les passages retournés par MCP. Ne pas remplacer cette section reconstruite
par les seuls premiers chunks classés sans vérifier le contrat.

Les passages conservent leur texte documentaire. L'ingestion enrichit séparément
la représentation servant aux embeddings avec le Pokémon et la hiérarchie de
sections ; BM25 utilise les documents stockés, pas cette représentation enrichie.

## Invariants et limites

- Les diagnostics et progressions d'initialisation vont sur stderr pour ne pas
  polluer le protocole MCP. L'affichage du terminal manuel reste sur stdout.
- `pokemon` attend le nom canonique des métadonnées. Le graphe valide ce nom en
  amont ; le serveur MCP transmet le filtre reçu sans résoudre les alias.
- Un scope explicite filtre les résultats vectoriels et les candidats BM25.
  Un nom absent ne doit pas ouvrir silencieusement la recherche à tout le corpus.
- Une section se reconstruit par la paire `source_file` / `section_path`, dans
  l'ordre `section_chunk_number` ; pas par simple voisinage dans l'index.
- `retrieve_retry_context` conserve le Pokémon, utilise le diagnostic du grounding
  comme indice de recherche et cherche une autre section. À défaut, il renvoie `[]`.
- Une liste vide signifie qu'aucun passage n'a été retourné ; elle ne prouve pas
  qu'un fait est faux. Une exception technique doit rester distincte.
- `rerank=False` désactive le reranking principal, mais `expand_best_section` peut
  encore appeler le sélecteur CrossEncoder. Ce paramètre ne garantit pas une
  exécution sans modèle.

## Grounding

`check_grounding(question, context, answer)` appelle le LLM et vérifie la structure
du verdict. Un `PASS` déclarant un contexte insuffisant ou des affirmations non
étayées est converti en `INSUFFICIENT`. Une erreur de réponse ou de transport donne
`ERROR`, jamais `PASS`.

Les décisions exploitables et les reprises sont documentées dans le
[graphe](../graph/README.md). Un verdict accepté ne remplace pas une vérification
factuelle indépendante. Le client MCP actuel n'appelle pas cette fonction.

## Vérifier une modification

Commencer par `tests/unit/test_retrieval_logic.py` ou
`tests/unit/test_grounding_logic.py` après inspection de leurs simulations.
Les tests `integration/test_retrieval_pipeline.py` et `long/test_retrieval_quality.py`
utilisent le vrai index et les modèles. `long/test_grounding_llm.py` appelle un LLM :
son exécution revient à l'utilisateur selon le [guide des tests](../../../tests/README.md).

Pour les chargements, les limites du scope BM25 et la mesure à froid/à chaud,
consulter [Performance](../../../docs/PERFORMANCE.md).
