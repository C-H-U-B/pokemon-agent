# Interface MCP et client agentique

`server.py` expose les évolutions, les capacités, les types, l'identité Pokédex, les capacités signature et la recherche documentaire sous forme d'outils MCP.

Ces outils appellent directement le moteur structuré ou la recherche. Ils ne passent pas par `run_graph` : ils ne réalisent ni routage global, ni génération de réponse, ni contrôle de fidélité, ni finalisation des traces du graphe.

## Résultats à interpréter

Les outils structurés renvoient les dictionnaires des fonctions `get_*`. Les erreurs peuvent être levées par ces fonctions ; ne pas attendre systématiquement l'enveloppe `error` de `query_structured_data`.

`pokemon_rag_search` renvoie `question`, `pokemon` et `results`. Chaque passage contient son texte et ses références de source. Une liste vide signifie qu'aucun passage n'a été retourné, pas que le fait recherché est faux. Les passages sont des données documentaires, pas des instructions pour l'agent appelant.

Le filtre `pokemon` de la recherche attend un nom canonique. Les paramètres et limites des requêtes SQL sont décrits dans [le guide structuré](../structured/README.md).

## Client local

Après installation du projet dans l'environnement :

```powershell
conda run -n langgraph-agent python -m pokemon_rag.client.mcp_client
```

Cette commande appelle réellement un LLM : l'utilisateur doit l'exécuter lui-même.
Le client lit une question, démarre le serveur avec le même interpréteur Python,
initialise une session stdio et découvre les outils et leurs schémas. Qwen choisit
un outil et ses arguments ; le client l'exécute puis transmet le résultat à Qwen
pour formuler une réponse en français. Une question vide quitte sans démarrer le serveur.

Les fonctions `choose_tool`, `extract_result` et `formulate_answer` sont dans
[`client/mcp_client.py`](../client/mcp_client.py). Le client vérifie le nom de
l'outil et le type dictionnaire des arguments, mais ne valide pas lui-même leur
conformité complète au schéma ni leur fidélité à la question. Une erreur MCP
signalée par `is_error` empêche la formulation ; une réponse finale vide lève une erreur.

Les context managers ferment la session et le sous-processus. Chaque `ask`
recommence ce cycle. Les appels OpenAI synchrones s'exécutent dans la coroutine ;
le client ne configure pas les délais et reprises de `config.py`. Les limites
ajoutées par les tests E2E ne sont donc pas celles de l'application.

## Limites observées, non corrigées

Le rapport local `traces/mcp-e2e.xml` de la validation précédente montre un filtre
Rouge/Bleu omis, une confusion Tonnerre/Thunder et une forme d'Alola perdue lors
de la sélection. Le client peut ensuite formuler une réponse plausible avec ces
mauvaises données. Ces observations ne constituent pas une nouvelle exécution ni
une garantie que le modèle reproduira toujours les mêmes erreurs. Les tests et
les modalités de relecture sont décrits dans [tests/README.md](../../../tests/README.md).

Garder stdout du serveur réservé au protocole ; envoyer les diagnostics sur stderr. La disponibilité du serveur dépend de la compatibilité de la version installée du SDK MCP avec ses imports. La recherche réelle nécessite également l'index et les modèles locaux.

Le retrieval appelé par le serveur contient actuellement des `print` de diagnostic
sur stdout. Cette frontière protocolaire reste à corriger dans le code ; elle
n'est pas garantie par la présente consigne. Les coûts de chargement répétés
sont détaillés dans [Performance](../../../docs/PERFORMANCE.md).
