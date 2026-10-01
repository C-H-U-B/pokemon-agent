# Interface Web Gradio

`app.py` présente une conversation locale avec le `root_agent` ADK existant.
Un `InMemoryRunner` partagé réutilise cet agent ; l'interface ne crée pas de
second agent et n'appelle pas directement les moteurs métier. Les huit outils
restent accessibles via MCP et le guard avant appel. Les prérequis et limites
de réponse sont ceux du [guide ADK](../agent/README.md), sans grounding du graphe.

## Lancement et utilisation

Dans l'environnement `langgraph-agent`, installer le projet avec `pip install -e .`.
`pyproject.toml` déclare `gradio>=6.29,<7`. LM Studio doit déjà servir Qwen avec
le contexte de 16384 tokens décrit dans le guide ADK ; les données locales
doivent être disponibles selon les outils utilisés.

```powershell
conda activate langgraph-agent
python -m pokemon_rag.web.app
```

Le point d'entrée appelle `demo.launch(inbrowser=True)` et demande l'ouverture
automatique du navigateur. Aucune adresse ou aucun port n'est fixé dans le code.
Envoyer une question par le bouton ou Entrée appelle réellement Qwen.

Le panneau `Agent activity` affiche les noms et arguments des `function_call`
et signale la réception des `function_response`. Ses phases sont déduites de
ces événements : analyse, exécution d'outil, résultat reçu et génération finale.
Un résultat reçu ne prouve pas la réussite métier de l'outil. Les arguments
affichés ne constituent pas une preuve des arguments corrigés envoyés au serveur.
Le chrono est rafraîchi toutes les 0,1 seconde pendant l'attente ; il démarre
avant la création de la session ADK de la requête. La conversation reçoit le texte
final à la fin de l'exécution, sans affichage token par token de la réponse.

## Conversations et exemples

`WebSession` conserve un `user_id` issu d'un UUID pour l'interface. Chaque question
crée une session ADK indépendante, supprimée à la fin, y compris après une erreur.
L'historique reste affiché dans Gradio mais n'est pas envoyé à l'agent : chaque
question doit être autonome. « Nouvelle conversation » efface l'historique
affiché et crée un nouvel état Web. Rien n'est persisté après redémarrage.

Les exemples sont chargés à l'import depuis `example_questions.txt`, voisin
de `app.py`, en UTF-8 : une question par ligne non vide. Un fichier manquant
ou sans question empêche le chargement de l'interface. Un exemple aléatoire
préremplit la saisie ; « Autre exemple » et « Nouvelle conversation » en choisissent
un autre, sans lancer de requête. Le tirage peut répéter la même question.

## Points non vérifiés

L'isolation de plusieurs navigateurs reste à vérifier : `gr.State(WebSession())`
est construit une seule fois dans `build_app`, sans génération d'identifiants
explicitement attachée à l'ouverture de chaque session navigateur. L'UUID seul
ne suffit donc pas à démontrer cette isolation.

Le fichier d'exemples n'est pas explicitement déclaré dans les ressources
setuptools de `pyproject.toml`. Sa présence dans une distribution construite
reste à vérifier ; la commande ci-dessus vise le checkout installé en mode éditable.
