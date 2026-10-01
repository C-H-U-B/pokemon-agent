# Repères pour contribuer

Commencer par la ligne correspondant à la tâche, puis lire le code et les tests
concernés. Il n'est pas nécessaire de lire tous les guides, les historiques ou
les données locales. Chaque guide ci-dessous est la référence de son périmètre.

| Besoin | Document |
| --- | --- |
| Installer et lancer le projet | [README français](../README_FR.md) |
| Comprendre les flux et choisir le module à modifier | [Architecture](../ARCHITECTURE.md) |
| Transmettre une tâche à un humain ou un agent | [Collaboration](COLLABORATION.md) |
| Comprendre le graphe et ses sorties | [Graphe](../src/pokemon_rag/graph/README.md) |
| Ajouter une requête structurée | [Moteur structuré](../src/pokemon_rag/structured/README.md) |
| Extraire les contraintes communes de forme, jeu et niveau | [Contraintes](../src/pokemon_rag/constraints/README.md) |
| Modifier la recherche documentaire ou le grounding | [RAG](../src/pokemon_rag/rag/README.md) |
| Utiliser les outils et le client MCP | [MCP](../src/pokemon_rag/mcp/README.md) |
| Utiliser l'agent ADK avec Qwen local | [Agent ADK](../src/pokemon_rag/agent/README.md) |
| Comprendre les sources et scripts | [Scripts](../scripts/README.md) |
| Choisir les tests et relire les réponses | [Tests](../tests/README.md) |
| Mesurer la latence et les coûts | [Performance](PERFORMANCE.md) |
| Comprendre l'ordre des décisions passées | [Historique français](../DEVELOPMENT_FR.md) |

Le code décrit le comportement effectif. Si un guide le contredit, signaler l'écart et vérifier l'implémentation avant de modifier l'un ou l'autre. L'historique peut décrire un comportement ancien : ce n'est pas une spécification actuelle.
