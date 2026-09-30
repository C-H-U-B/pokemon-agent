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
pour formuler une réponse en français. Il lit ensuite les questions suivantes
dans la même session. Une ligne vide, `quit`, `/quit`, `exit` ou une fin de saisie
termine la boucle ; une sortie avant la première question ne démarre aucun serveur.

Les fonctions `choose_tool`, `extract_result` et `formulate_answer` sont dans
[`client/mcp_client.py`](../client/mcp_client.py). Le client vérifie le nom de
l'outil et le type dictionnaire des arguments, mais ne valide pas lui-même leur
conformité complète au schéma ni leur fidélité à la question. Une erreur MCP
signalée par `is_error` empêche la formulation ; une réponse finale vide lève une erreur.

`open_client()` ouvre un contexte réutilisable : appeler `conversation.ask(question)`
pour chaque question dans ce contexte. Le catalogue est découvert une fois et les
modèles RAG restent disponibles dans le serveur après leur premier chargement.
Les questions sont indépendantes, sans mémoire conversationnelle. Le catalogue
n'est pas rafraîchi pendant la session ; rouvrir le contexte si les outils changent.

Les context managers ferment la session, le sous-processus et le client HTTP LLM,
y compris en cas d'erreur ou d'annulation. Une erreur arrête la boucle sans
reconnexion automatique. La fonction ponctuelle `ask(question)` conserve son
comportement : elle ouvre et ferme son propre contexte. La saisie du terminal
est attendue dans un thread pour laisser fonctionner la réception MCP.
Les appels OpenAI synchrones s'exécutent dans la coroutine ;
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

Les diagnostics et barres de progression de l'initialisation RAG sont envoyés
sur stderr pour préserver stdout MCP. Un test avec modèles et collection simulés
vérifie cette séparation. Les coûts de chargement répétés
sont détaillés dans [Performance](../../../docs/PERFORMANCE.md).
