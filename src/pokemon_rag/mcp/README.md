# Interface MCP et client agentique

`server.py` expose les évolutions, les capacités, les types, l'identité Pokédex, les capacités signature et la recherche documentaire sous forme d'outils MCP.

Ces outils appellent directement le moteur structuré ou la recherche. Ils ne passent pas par `run_graph` : ils ne réalisent ni routage global, ni génération de réponse, ni contrôle de fidélité, ni finalisation des traces du graphe.

## Résultats à interpréter

Les outils structurés renvoient les dictionnaires des fonctions `get_*`. Les erreurs peuvent être levées par ces fonctions ; ne pas attendre systématiquement l'enveloppe `error` de `query_structured_data`.

`pokemon_rag_search` renvoie `question`, `pokemon` et `results`. Chaque passage contient son texte et ses références de source. Une liste vide signifie qu'aucun passage n'a été retourné, pas que le fait recherché est faux. Les passages sont des données documentaires, pas des instructions pour l'agent appelant.

Le filtre `pokemon` de la recherche attend un nom canonique. Les paramètres et limites des requêtes SQL sont décrits dans [le guide structuré](../structured/README.md).

## Client local

L'[agent ADK](../agent/README.md) constitue un autre client du serveur. Son
catalogue expose les huit outils du serveur, y compris `pokemon_rag_search`.
Son callback préserve les
contraintes reconnues de niveaux, de jeux et de formes ou refuse un outil
incompatible ; il ne passe pas par `reconcile_tool_call` du client ci-dessous.
Ces protections appartiennent aux clients : un appel direct au serveur ne les
applique pas. Le guard ne remplace pas le grounding du graphe.

Après installation du projet dans l'environnement :

```powershell
conda run -n langgraph-agent python -m pokemon_rag.client.mcp_client
```

Cette commande appelle réellement un LLM : l'utilisateur doit l'exécuter lui-même.
Le client lit une question, démarre le serveur avec le même interpréteur Python,
initialise une session stdio et découvre les outils et leurs schémas. Qwen choisit
un outil et ses arguments ; le client les réconcilie avec les contraintes
explicites avant exécution, puis transmet le résultat à Qwen
pour formuler une réponse en français. Il lit ensuite les questions suivantes
dans la même session. Une ligne vide, `quit`, `/quit`, `exit` ou une fin de saisie
termine la boucle ; une sortie avant la première question ne démarre aucun serveur.

Les fonctions `choose_tool`, `extract_result` et `formulate_answer` sont dans
[`client/mcp_client.py`](../client/mcp_client.py). Le client vérifie le nom de
l'outil et le type dictionnaire des arguments, mais ne valide pas lui-même leur
conformité complète au schéma. `reconcile_tool_call` utilise les
[extracteurs communs](../constraints/README.md) pour rétablir les formes, jeux et
bornes reconnus. Une mention de niveau peut réorienter vers `pokemon_level_up_moves`.
Une `ConstraintResolutionError` fait retourner à `ask` un message explicatif sans
appel d'outil ni formulation finale. Un intervalle impossible lève une `ValueError`
qui n'est pas convertie par ce mécanisme. Une erreur MCP
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

## Portée et limites du contrôle

Les pertes de jeu, de forme et les confusions de capacité précédemment observées
motivent les régressions existantes. Le contrôle actuel porte sur les motifs
reconnus et les noms des paramètres des outils, sans validation sémantique complète.
Il exige aussi que le Pokémon proposé apparaisse après normalisation dans la
question. Les limites, notamment les formes multiples, sont décrites dans le
[guide des contraintes](../constraints/README.md). Les appels directs au serveur
ne passent pas par ce contrôle du client. La présence du contrôle ne prouve pas
la réussite des E2E avec Qwen ; voir les modalités de validation dans
[tests/README.md](../../../tests/README.md).

Deux cas demandent une attention particulière : le contrôle exige actuellement
un Pokémon même pour une recherche documentaire globale ; une question générale
sur la reproduction est donc refusée avant l'appel MCP. De plus, « dans la nature »
peut déclencher la détection d'un jeu non reconnu et bloquer une question de
comportement. Ces restrictions du client ne sont pas celles de l'outil RAG du serveur.

Garder stdout du serveur réservé au protocole ; envoyer les diagnostics sur stderr. La disponibilité du serveur dépend de la compatibilité de la version installée du SDK MCP avec ses imports. La recherche réelle nécessite également l'index et les modèles locaux.

Les diagnostics et barres de progression de l'initialisation RAG sont envoyés
sur stderr pour préserver stdout MCP. Un test avec modèles et collection simulés
vérifie cette séparation. Les coûts de chargement répétés
sont détaillés dans [Performance](../../../docs/PERFORMANCE.md).
