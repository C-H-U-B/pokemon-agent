# Agent Pokémon ADK

Ce package ajoute une couche d'orchestration indépendante du graphe et du client
MCP existants. Il contient un seul agent, `agent.py:root_agent`, qui demande au
modèle de répondre en français.

Le parcours est : utilisateur → agent ADK → LiteLLM → API compatible OpenAI de
LM Studio (`http://localhost:1234/v1`) → `qwen/qwen3-vl-8b` local. Le préfixe
`openai/` du nom LiteLLM indique le protocole utilisé. L'URL et la clé factice
`lm-studio` sont passées explicitement au modèle, sans modifier les variables
globales `OPENAI_API_BASE` et `OPENAI_API_KEY`.

Cette première intégration ne dispose d'aucun outil ni sous-agent. Elle n'accède
pas à SQLite, Chroma ou au RAG et n'applique pas le grounding du graphe. Ses
réponses reposent uniquement sur le modèle. MCP est le protocole d'accès aux
outils existants ; sa connexion à cet agent reste hors du périmètre actuel.

## Utilisation manuelle

Dans l'environnement Conda `langgraph-agent`, installer le projet avec
`pip install -e .`. Les versions déclarées sont `google-adk==2.10.0` et
`litellm==1.103.2`. LM Studio doit déjà servir `qwen/qwen3-vl-8b` sur le port 1234.

Depuis la racine du dépôt :

```powershell
conda activate langgraph-agent
adk run src/pokemon_rag/agent
```

Cette commande interactive est réservée à l'utilisateur : envoyer une question
appelle réellement Qwen. Vérifier une réponse en français et transmettre la
sortie ou l'erreur pour valider le parcours complet. Importer ou construire
l'agent ne constitue pas une validation de l'inférence.

Le smoke test existant est également réservé à une exécution manuelle, dans
le même environnement avec LM Studio et Qwen disponibles :

```powershell
python -m pytest tests/long/test_adk_agent.py -q -p no:cacheprovider
```

Il porte les marqueurs `llm`, `long` et `models`, utilise `asyncio.run` sans
plugin pytest asynchrone et vérifie le retour du témoin `ADK_OK`. Transmettre
la sortie pytest ; ce témoin valide le parcours technique, pas la qualité
factuelle des réponses Pokémon.
