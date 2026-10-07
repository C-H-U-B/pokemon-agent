# Interface Web Gradio

`app.py` présente une conversation locale avec le `root_agent` ADK existant.
Un `InMemoryRunner` partagé réutilise cet agent ; l'interface ne crée pas de
second agent et n'appelle pas directement les moteurs métier. Les douze outils
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

En conteneur, le service `web` de `compose.yaml` lance ce même point d'entrée
sur le port 7860 (`GRADIO_SERVER_NAME=0.0.0.0`). Il vise par défaut le service
`ollama` ; `WEB_LLM_BASE_URL` et `WEB_LLM_MODEL` le dirigent vers un autre serveur, par
exemple LM Studio sur la machine hôte :

```powershell
$env:WEB_LLM_BASE_URL = "http://host.docker.internal:1234/v1"
$env:WEB_LLM_MODEL = "qwen/qwen3-vl-8b"
docker compose up -d --build web
```

La base SQLite est montée depuis `data/`. L'index Poképédia et les modèles de
recherche vivent dans des volumes Docker : l'index doit y être copié une fois,
puis après chaque réindexation, avec la commande notée dans `compose.yaml`.
Lu depuis un dossier Windows partagé, son chargement prenait 44 secondes au lieu
de 12 sur la machine de développement. Le parcours avec Ollama n'a pas encore
été validé.

Le panneau « Agent et outils en action » conserve deux parts sur cinq de la
disposition sur grand écran, à droite de la conversation qui occupe les trois
autres parts. Sur petit écran, la conversation est au-dessus de l'agent.
Les bulles utilisateur sont alignées à gauche, celles de l'assistant à droite.
Les boutons de copie restent sous le texte, alignés avec leur bulle.
La hauteur est adaptée à la fenêtre et les contenus longs défilent à
l'intérieur des panneaux, plutôt que d'allonger la page.
Il distingue l'agent ADK / Qwen des outils MCP et présente leur parcours
progressivement : analyse, consultation SQLite ou recherche de passages
Poképédia via le RAG / Chroma, retour d'outil puis préparation du texte par Qwen.
Le schéma statique et la note explicative en bas du panneau ont été retirés.
Les outils ont un libellé français avec leur identifiant technique visible.
Le thème Soft et les styles sont appliqués par le point d'entrée au lancement.

Le panneau d'activité affiche le nom de chaque outil appelé et ses arguments
exécutés, après correction par le guard (lus dans l'état de session), et signale
la réception des `function_response`. Ses phases sont déduites de
ces événements : analyse, exécution d'outil, résultat reçu et génération finale.
Un résultat reçu ne prouve pas la réussite métier de l'outil. Tant que l'outil
n'a pas répondu, le panneau affiche la proposition du modèle.
Le chrono est rafraîchi toutes les 0,1 seconde pendant l'attente ; il démarre
avant la création de la session ADK de la requête.
Les durées par étape cumulent l'analyse avant le premier appel, l'attente
d'outils et la préparation entre retours et nouveaux appels ou fin de requête.
Chaque appel dispose aussi de son chrono, figé à son retour ou à la fin.
Les appels simultanés ne sont pas additionnés dans le total d'attente.
Ces mesures incluent les délais de transport et de session, pas seulement le
calcul du modèle ou du moteur. Sans outil, le temps reste dans analyse / choix.
Les appels homonymes sont associés aux retours dans l'ordre d'arrivée (FIFO).
Le panneau affiche aussi les temps mesurés par l'outil lui-même : chargement
de la base documentaire au premier appel (modèles, corpus, index lexical),
étapes de chaque recherche avec le nombre de passages, et durée de la requête
SQL. Ces mesures passent par l'état de session ADK (`tool_timings`), jamais par
le retour d'outil envoyé au modèle. Les tokens lus et générés viennent de
l'usage déclaré par le serveur de modèle ; le débit affiché les rapporte au
temps d'analyse et de préparation mesuré par l'interface, transport compris.
La conversation reçoit le texte
final à la fin de l'exécution, sans affichage token par token de la réponse.
La question apparaît dès l'envoi, et la saisie se trouve sous l'historique.
L'historique n'a pas de bandeau de titre. Les lignes de saisie et d'actions
gardent une hauteur limitée à leur contenu pour laisser l'espace à la conversation.
Une grille réserve au chat toute la hauteur restante, sans hauteur fixe.
Une bulle « … » reste visible pendant
l'exécution puis est remplacée par la réponse ou le message d'erreur. Elle
indique l'attente, y compris pendant les outils, sans exposer de raisonnement.
Une exécution sans texte final affiche « Aucune réponse finale », distinct de
« Réponse disponible » et des erreurs techniques.

## Démarrage du serveur d'outils

À l'ouverture de la page, l'interface liste les outils MCP, ce qui démarre le
serveur d'outils avant la première question ; les questions suivantes
réutilisent ce même processus. Avec `POKEMON_RAG_PRELOAD=1` (défini pour le
conteneur Web dans `compose.yaml`), l'agent lance ce serveur avec `--preload`
et la base documentaire se charge alors en arrière-plan, au lieu d'être
chargée pendant la première recherche. Sans cette variable, le chargement
reste paresseux : aucun modèle n'est chargé tant qu'une recherche
documentaire n'est pas demandée. Une question posée pendant le chargement
attend sa fin, sans le relancer. Un échec de ce démarrage anticipé est
journalisé (`warm_up_failed`) et ne bloque pas l'interface.

## Traces

Chaque question ajoute une ligne à `traces/web_traces.jsonl` : modèle et serveur
utilisés, question, issue (`answered`, `budget_abstention`,
`tool_failure_abstention`, `double_request_refusal`, `no_final_response`, `error`), réponse, temps par
étape, tokens, et pour chaque appel d'outil ses arguments exécutés après le
guard (`arguments`), la proposition du modèle lorsqu'elle diffère
(`proposed_arguments`), sa durée, ses mesures et le résultat tel que le modèle
l'a reçu. `scripts/observability/analyze_traces.py` ne lit que les traces du
graphe et refuse ce format. Le service `web` de `compose.yaml`
monte ce dossier. Une écriture impossible est journalisée (`web_trace_failed`)
sans affecter la réponse. Le débit affiché dans le panneau rapporte les tokens
générés à tout le temps passé chez le modèle, lecture des requêtes comprise :
le serveur de modèle ne sépare pas les deux.

## Conversations et exemples

`WebSession` conserve un `user_id` issu d'un UUID pour l'interface. Chaque question
crée une session ADK indépendante, supprimée à la fin, y compris après une erreur.
L'historique reste affiché dans Gradio mais n'est pas envoyé à l'agent : chaque
question doit être autonome. « Nouvelle conversation » efface l'historique
affiché et crée un nouvel état Web. Rien n'est persisté après redémarrage.

Les exemples sont chargés à l'import depuis `example_questions.txt`, voisin
de `app.py`, en UTF-8 : une question par ligne non vide. Un fichier manquant
ou sans question empêche le chargement de l'interface. Un exemple aléatoire
préremplit la saisie via « Question d'exemple », sans lancer de requête.
La saisie est vide au démarrage et après « Nouvelle conversation ».
Un rappel visible explique l'absence de mémoire entre questions.
Le tirage peut répéter la même question.

## Points non vérifiés

L'isolation de plusieurs navigateurs reste à vérifier : `gr.State(WebSession())`
est construit une seule fois dans `build_app`, sans génération d'identifiants
explicitement attachée à l'ouverture de chaque session navigateur. L'UUID seul
ne suffit donc pas à démontrer cette isolation.

Le fichier d'exemples n'est pas explicitement déclaré dans les ressources
setuptools de `pyproject.toml`. Sa présence dans une distribution construite
reste à vérifier ; la commande ci-dessus vise le checkout installé en mode éditable.
