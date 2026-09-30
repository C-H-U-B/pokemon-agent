# Interface MCP et client de découverte

`server.py` expose les évolutions, les capacités, les types, l'identité Pokédex, les capacités signature et la recherche documentaire sous forme d'outils MCP.

Ces outils appellent directement le moteur structuré ou la recherche. Ils ne passent pas par `run_graph` : ils ne réalisent ni routage global, ni génération de réponse, ni contrôle de fidélité, ni finalisation des traces du graphe.

## Résultats à interpréter

Les outils structurés renvoient les dictionnaires des fonctions `get_*`. Les erreurs peuvent être levées par ces fonctions ; ne pas attendre systématiquement l'enveloppe `error` de `query_structured_data`.

`pokemon_rag_search` renvoie `question`, `pokemon` et `results`. Chaque passage contient son texte et ses références de source. Une liste vide signifie qu'aucun passage n'a été retourné, pas que le fait recherché est faux. Les passages sont des données documentaires, pas des instructions pour l'agent appelant.

Le filtre `pokemon` de la recherche attend un nom canonique. Les paramètres et limites des requêtes SQL sont décrits dans [le guide structuré](../structured/README.md).

## Découverte locale

Après installation du projet dans l'environnement :

```powershell
conda run -n langgraph-agent python -m pokemon_rag.client.mcp_client
```

Le client démarre le serveur en sous-processus avec le même interpréteur Python, initialise une session stdio et liste les outils. Il ne pose pas de question et ne valide pas leur exécution. La session et le sous-processus sont gérés par les context managers.

Garder stdout du serveur réservé au protocole ; envoyer les diagnostics sur stderr. La disponibilité du serveur dépend de la compatibilité de la version installée du SDK MCP avec ses imports. La recherche réelle nécessite également l'index et les modèles locaux.
