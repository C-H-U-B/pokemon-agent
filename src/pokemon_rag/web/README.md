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
Envoyer une question par le bouton ou Entrée appelle réellement le modèle configuré (Qwen par défaut).

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
de 12 sur la machine de développement. Le parcours avec Ollama a été validé le
6 octobre : campagne structurée complète et clone neuf monté en suivant le README.

Le panneau de droite (onglets « Parcours » et « Observabilité », voir [Graphe du parcours](#graphe-du-parcours)
et [Onglet « Observabilité »](#onglet--observabilité-))
conserve deux parts sur cinq de la
disposition sur grand écran, à droite de la conversation qui occupe les trois
autres parts. Sur petit écran, la conversation est au-dessus de l'agent.
Les bulles utilisateur sont alignées à gauche, celles de l'assistant à droite.
Les boutons de copie restent sous le texte, alignés avec leur bulle.
La hauteur est adaptée à la fenêtre et les contenus longs défilent à
l'intérieur des panneaux, plutôt que d'allonger la page.
La conversation reçoit le texte
final à la fin de l'exécution, sans affichage token par token de la réponse.
La question apparaît dès l'envoi, et la saisie se trouve sous l'historique.
En tête de page, trois lignes disent ce que fait l'outil, nomment le modèle servi, renvoient au dépôt
et préviennent que les questions sont enregistrées. Une question est limitée à 300 caractères
(`MAX_QUESTION_CHARS`), dans le champ de saisie et de nouveau dans `chat`, qu'un appel direct de l'API
atteint sans passer par le champ : au-delà, aucun appel au modèle n'est fait. Tant qu'aucune recherche
documentaire n'a abouti depuis le démarrage, le graphe et l'onglet « Observabilité » préviennent, après
trois secondes d'attente, que la base se charge ; c'est un indice tenu par l'interface, pas l'état réel du
serveur d'outils.

Le champ de saisie est vidé à l'envoi, pas à l'arrivée de la réponse : une question préparée pendant
l'attente y reste. Pendant l'exécution, seul le panneau de droite est mis à jour, la conversation se
lit donc librement ; à l'arrivée de la réponse, elle revient sur la dernière question.

L'historique n'a pas de bandeau de titre. Les lignes de saisie et d'actions
gardent une hauteur limitée à leur contenu pour laisser l'espace à la conversation.
Une grille réserve au chat toute la hauteur restante, sans hauteur fixe.
Une bulle « … » reste visible pendant
l'exécution puis est remplacée par la réponse ou le message d'erreur. Elle
indique l'attente, y compris pendant les outils, sans exposer de raisonnement.
Une exécution sans texte final est dite dans le bloc « Réponse » de l'onglet « Observabilité », distincte
d'une réponse rédigée et d'une erreur technique. Une erreur technique affiche
un message fixe (`TECHNICAL_ERROR_MESSAGE`), sans le type ni le texte de
l'exception, qui peuvent contenir l'adresse du serveur de modèle : le détail va
au journal (`web_request_failed`) et au champ `error` de la trace.

## Graphe du parcours

Le panneau de droite a deux onglets. « Parcours », affiché à l'ouverture, dessine le chemin de la question ;
« Observabilité » en montre les données, étape par étape.

Le graphe montre les modules réellement exécutés : la question, le modèle qui choisit l'outil, le guard, le
serveur d'outils, puis un anneau à deux branches (la base de données d'un côté, Poképédia et ses quatre étapes
de recherche de l'autre) qui se referme sur le budget de contexte, le modèle qui rédige et la réponse. Un
liquide parcourt les tubes et remplit les nœuds ; un tube ne se remplit qu'une fois plein le nœud d'où il sort.
Sous le dessin, un encart donne le rôle du nœud survolé et ce qu'il a produit, un passage par ligne, le plus
récent en premier ; un clic épingle le nœud. Sans survol ni épinglage, l'encart suit l'étape en cours et
affiche le temps passé dessus.

`graph.py` porte le dessin (`NODES`, `EDGES`, `graph_template`), ses styles et son comportement dans le
navigateur. Ajouter un module revient à ajouter une entrée dans `NODES` et ses liens dans `EDGES`.
`graph_path(trace)` traduit une trace de la forme de `_web_trace`, complète ou en cours, en passages ordonnés
(nœud de départ, nœud atteint, phrase). `chat` envoie ce parcours à l'envoi, à chaque événement de l'agent et à
la fin, jamais au rythme du chrono ; le navigateur le déroule lui-même, un passage après l'autre. La réponse
n'attend donc pas l'animation, qui peut finir une ou deux secondes après elle.

| Issue | Parcours |
| --- | --- |
| Réponse rédigée d'après un résultat d'outil | jusqu'à « Réponse » |
| Appel refusé par le guard, ou outil en erreur | retour au modèle par un tube de retour ; la question continue |
| Question trop longue, double demande | « Votre question » → « Rejet » |
| Abstention de budget | « Rejet » depuis le budget, ou depuis le guard ou le serveur d'outils si le dernier appel a échoué |
| Abstention d'échec d'outil, aucune réponse finale, erreur technique | « Rejet » depuis le nœud du modèle alors sollicité |
| Réponse écrite sans aucun appel d'outil | « Rejet » : elle n'est pas vérifiée, même si son texte est affiché |

Le remplacement d'une liste infidèle par les données reste une réponse ; il est dit sur « Modèle · rédige ».
Plusieurs outils demandés dans le même tour comptent pour un seul passage du modèle.

Deux nœuds ne sont dessinés que lorsque le parcours y passe : « Rejet », et « Chargement », qui s'allume quand
une première recherche documentaire depuis le démarrage attend depuis plus de trois secondes
(`LOADING_HINT_SECONDS`). C'est un indice tiré de l'attente, pas l'état réel du serveur d'outils : sur une
machine lente, il peut s'allumer alors que la base est déjà chargée.

Les têtes sont des icônes de Pokémon Shuffle **liées** depuis Poképédia (`shuffle_icon`), non redistribuées :
un Pikachu tiré au hasard à chaque question pour le visiteur, et sur « Réponse » l'espèce du premier Pokémon
cité dans la réponse et présent dans les données. Poképédia n'a pas d'icône après la septième génération ; le
nœud reste alors un rond. À l'ouverture, le graphe rejoue une fois, en accéléré, le parcours de l'exemple
enregistré (`exemple_ouverture.json`, clé `trace`), sans appel au modèle.

Le dessin et l'encart tiennent dans le panneau sans défilement : la hauteur du dessin est calculée dans le
navigateur d'après le panneau, et l'encart a une hauteur fixe, où un texte long défile. Mesuré le 9 octobre
2026 de 1920 × 950 à 1280 × 600. Les `@keyframes` du graphe sont dans `APP_CSS` : Gradio emboîte le style
d'un composant `gr.HTML` sous un sélecteur, où ils sont ignorés.

Le bouton d'envoi est inactif et libellé « Réponse en cours… » de l'envoi à la réponse ; « Nouvelle
conversation », qui annule la question, le rétablit.

## Onglet « Observabilité »

Le second onglet montre la chaîne de la question en blocs, pour suivre ce que chaque étape a reçu et renvoyé.
Une ligne de synthèse (durée totale, choix des outils, attente des outils, rédaction, tokens lus et générés),
puis un bloc « Question », un bloc par appel d'outil et un bloc « Réponse » qui dit l'issue en clair. Un bloc
d'appel porte le libellé français de l'outil, son identifiant, sa durée, et jusqu'à quatre étapes :

| Étape | Ce qu'elle montre |
| --- | --- |
| Modèle · choisit l'outil | l'outil appelé et les arguments proposés ; l'appel émis, en JSON dans un bloc repliable |
| Guard | « conforme », « corrige » avec ce qui est ajouté, modifié ou retiré, ou « refuse l'appel » avec son message et les arguments exigés ; en bloc repliable, l'appel transmis à l'outil ou le refus rendu au modèle |
| Outil | les arguments exécutés, la durée de la requête SQL ou des étapes de la recherche, le chargement de la base documentaire au premier appel, la taille du retour de l'outil |
| Budget de contexte | « transmet en entier », « réduit aux champs utiles », « tronque » ou « ne transmet rien », la taille transmise, et le retour tel que le modèle l'a reçu, en JSON dans un bloc repliable |

La chaîne s'arrête à l'étape qui a arrêté l'appel : au guard pour un refus, à l'outil pour une erreur. Le
retour brut de l'outil n'est pas affiché, seulement sa taille ; le retour transmis l'est en entier (3 211
octets au plus sur les 204 appels tracés au 9 octobre 2026) et défile dans son bloc.

`observability.py` porte ce rendu : `observability_html(trace)` lit une trace de la forme de `_web_trace`,
complète ou en cours, comme `graph_path`. La page est publique : tout texte venu de la question, du modèle ou
d'un outil est échappé, et le texte d'exception qui suit « Détail : » dans une erreur d'outil n'est pas
affiché (la trace le garde). Une question en cours n'affiche aucune durée qui change : `chat` ne renvoie les
blocs qu'à l'arrivée d'un appel ou d'un retour, jamais au rythme du chrono, et le navigateur garde dépliés les
blocs que le lecteur a ouverts, ainsi que la position de l'onglet. Le temps de l'étape en cours se lit dans
l'encart du graphe. À l'ouverture, l'onglet montre la chaîne de l'exemple enregistré.

Le panneau lui-même ne défile pas : la barre d'onglets reste en place et c'est le contenu de l'onglet qui
défile (`#agent-panel .tabitem`). Gradio masque l'onglet inactif par un `display: none` sur ce conteneur,
pas par l'attribut `hidden` : une règle CSS qui teste `hidden` sur un composant s'applique à tous les onglets.

Les durées par étape de la synthèse sont mesurées par l'interface : analyse avant le premier appel, attente
des outils (les appels simultanés ne sont pas additionnés), préparation entre retours et nouveaux appels ou
fin de requête ; elles incluent le transport et la session. Les appels homonymes sont associés aux retours
dans l'ordre d'arrivée (FIFO). Les mesures de l'outil et la taille de son retour passent par l'état de session
ADK (`tool_timings`), jamais par le retour envoyé au modèle. Un résultat reçu ne prouve pas la réussite métier
de l'outil.

## Illustrations

En haut d'une réponse, jusqu'à cinq illustrations officielles, sur une ligne
(HTML, 80 px imposés par `APP_CSS` car Gradio agrandit les images des messages ;
crédit en petits caractères dessous ; la trace garde la réponse sans elles) :
celles des Pokémon cités dans la réponse **et** présents dans les données reçues
(retours d'outils, arguments exécutés), dans l'ordre de citation ; le nom le plus
long l'emporte (« Raichu d'Alola » ne montre pas aussi Raichu). Un nom ajouté de
mémoire par le modèle, ou un mot courant qui est aussi un nom de Pokémon, n'est
donc pas illustré. Une abstention ou un refus n'a pas d'image, et le modèle ne
reçoit jamais ces images.

Un clic sur une illustration l'ouvre en grand au milieu de l'écran
(`IMAGE_VIEWER_JS`, un élément `dialog` ajouté à la page) ; la croix, le fond ou
Échap la referment. Une petite loupe dans le coin de chaque image l'annonce.

Dans la conversation, le bouton de copie est placé à côté de sa bulle, dans la
marge, et la bulle d'attente porte trois points animés (`PENDING_ANSWER`),
redessinés d'après ceux que Gradio ne montre qu'à l'envoi.

`pokemon_image_urls()` (moteur structuré) associe chaque entrée du tableur à son
illustration : l'image de son `pokemon_id`, ou `espèce-forme` pour une forme
cosmétique autre que celle par défaut. Les images sont **liées** depuis le dépôt
public PokeAPI/sprites et chargées par le navigateur : rien n'est téléchargé par
le serveur ni redistribué. Une image indisponible n'empêche pas la réponse ; une
base absente donne une réponse sans galerie. Couverture vérifiée le 7 octobre
2026 : 1 270 entrées liées sur 1 275 (les cinq formes de Vrombotor n'ont pas de
lien PokéAPI).

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
`tool_failure_abstention`, `double_request_refusal`, `list_fidelity_replacement`, `no_final_response`, `error`), réponse, temps par
étape, tokens (lus, générés, de réflexion, et `output_limit_reached` quand le
modèle s'est arrêté sur la limite de sortie), et pour chaque appel d'outil ses arguments exécutés après le
guard (`arguments`), la proposition du modèle lorsqu'elle diffère
(`proposed_arguments`), son instant de départ (`start` : deux appels partis au même instant ont été
demandés dans le même tour), sa durée, ses mesures, la taille de ce que le budget de contexte a reçu
(`raw_bytes` : le retour de l'outil avant réduction, ou le refus du guard ; absent des traces antérieures au
9 octobre 2026) et le résultat tel que le modèle l'a reçu. `scripts/observability/analyze_traces.py` ne lit que les traces du
graphe et refuse ce format. Le service `web` de `compose.yaml`
monte ce dossier. Une écriture impossible est journalisée (`web_trace_failed`)
sans affecter la réponse. Avec `WEB_TRACE_STDOUT=1` (image `demo`), la même trace part aussi sur la
sortie standard en une ligne JSON, sous la clé `web_trace` : sur un hébergeur sans disque persistant, c'est
le journal de la plateforme qui la conserve.

## Conversations et exemples

`WebSession` conserve un `user_id` issu d'un UUID pour l'interface. Chaque question
crée une session ADK indépendante, supprimée à la fin, y compris après une erreur.
L'historique reste affiché dans Gradio mais n'est pas envoyé à l'agent : chaque
question doit être autonome. « Nouvelle conversation » efface l'historique
affiché et crée un nouvel état Web. Rien n'est persisté après redémarrage.

Une question abandonnée est arrêtée : « Nouvelle conversation » annule l'envoi
en cours (`cancels`), et Gradio ferme le générateur `chat` quand le navigateur
se déconnecte ; dans les deux cas `chat` annule la tâche de l'agent, dont la
session ADK est supprimée. Aucun nouvel appel au modèle ne part ensuite ; un
appel d'outil déjà transmis au serveur MCP se termine de son côté. Une question
abandonnée n'écrit pas de trace.

Au-dessus de la saisie, l'intitulé « Pas d'idée ? Essayez une question, puis
envoyez-la : » précède trois boutons qui proposent des questions selon le
public : « Débutant » (`questions_decouvrir.txt`, langage courant, pour
quelqu'un qui n'a jamais joué ; les critères l'appellent « Je découvre »),
« Joueur » (`questions_connaisseurs.txt`, ce qu'on voit en jouant ; « Je
connais Pokémon » dans les critères) et « Expert » (`questions_experts.txt`,
contraintes combinées, cas rares et histoire du jeu). « Nouvelle
conversation », qui efface, est seule sous la saisie. Ce qui fait une bonne
question est écrit plus bas, dans « Critères d'une suggestion ». Chaque bouton
préremplit la saisie avec la question suivante de sa liste, sans lancer de
requête, y place le curseur, et revient au début après la dernière. Pendant
une réponse, le bouton d'envoi est inactif et la touche Entrée est arrêtée
dans le navigateur (`BLOCK_ENTER_WHILE_ANSWERING_JS`) : une question préparée
pendant l'attente reste dans la saisie. La position
dans chaque liste est propre à chaque navigateur (`WebSession.next_suggestion`) et
repart du début avec « Nouvelle conversation ». Les fichiers sont chargés à
l'import, en UTF-8, une question par ligne non vide ; un fichier manquant ou vide
empêche le chargement de l'interface. Au lancement, la conversation
montre déjà la première question « découvrir » (« Quels sont les 5 Pokémon les
plus lourds ? ») et sa réponse, sans aucun appel au modèle : un exemple
enregistré (`exemple_ouverture.json`, réponse réelle du modèle de la démo avec
les numéros de ses illustrations). Rien à l'écran ne le signale comme un
exemple : c'est dit ici seulement. La page se place sur la question, que
Gradio laissait cachée au-dessus de la réponse. Le visiteur a ainsi de quoi
lire pendant que sa propre question charge. Si la
première question de la liste change sans que l'exemple suive, il n'est pas
affiché et la question est proposée dans la saisie, comme avant ; un test
`real_data` vérifie que l'exemple reste la réponse que donnerait la base.
« Nouvelle conversation » l'efface. Un rappel visible explique
l'absence de mémoire entre questions.

### Critères d'une suggestion

À appliquer avant d'ajouter, de reformuler ou de déplacer une question dans les
trois fichiers. Le visiteur est un recruteur peu joueur qui essaie trois à cinq
suggestions : les listes sont longues non pour être parcourues, mais pour qu'une
question éveille sa curiosité. « Je découvre » parle à quelqu'un qui n'a jamais
joué. « Je connais Pokémon » parle à un joueur occasionnel, « Expert » à un
joueur confirmé : le visiteur n'a pas à comprendre ces réponses, il doit voir
l'outil traiter une question pointue sans se tromper. La frontière entre les
deux : ce qu'on voit en jouant (types, évolutions, légendaires, formes) relève
de « Je connais Pokémon » ; l'histoire du jeu d'une génération à l'autre
(ancien type, ancien talent, objets tenus, présence dans les jeux) relève
d'« Expert », comme un Pokémon peu connu dont ni le nom ni l'anecdote ne sont
célèbres (Pandespiègle, Froussardine). En cas de doute, « Expert ».

Familles écartées tant que l'outil ne les sert pas comme il faut : la version
exclusive d'un Pokémon nommé (utile seulement en liste par jeu, avec la
contrepartie de l'autre version) et les jeux où un Pokémon nommé est absent
(utile en classement des plus absents).

1. **Une curiosité vécue.** Le critère qui prime : une question que
   l'utilisateur ou ses amis se sont réellement posée. Aucun outil n'est
   intéressant en soi, et montrer une capacité jamais montrée ne justifie pas
   une question : le numéro de Pokédex d'un Pokémon quelconque n'intéresse
   personne, celui qui porte le numéro 1, le 666 ou le 1000, si. Signes d'une
   vraie curiosité : un extrême (Leveinard, 250 PV et 5 en Attaque), un nombre
   rond, un contre-pied (Terhal aussi difficile à capturer que Mewtwo), un
   Pokémon célèbre. En « Je découvre » : records du langage courant (le plus
   lourd, le plus grand), idées reçues, comptages, origine des noms qui ne se
   devinent pas. Une question inventée par un agent reste une candidate tant que l'utilisateur ne l'a pas reconnue ; une phrase écrite
   pour être reconnue par le guard (parenthèse explicative, tournure d'outil)
   est à refaire. Une question qui suppose ce que le curieux ignore n'est pas
   spontanée : si la source ne répond pas à la question naturelle (la page dit
   que Miaouss raffole des pièces, pas pourquoi), on abandonne le sujet au lieu
   de tordre la phrase. Avant de conclure que la source ne répond pas, lire le
   passage : une recherche de « mal de tête » a fait écarter à tort Psykokwak,
   dont la page parle de « migraines ».
2. **Le mot du domaine.** « Évolue », « type Glace pur » : le terme que les
   joueurs emploient. Si l'extraction des contraintes ne le reconnaît pas, c'est
   elle qu'on corrige, pas la phrase.
3. **Surprenante.** La réponse apprend quelque chose à la personne du niveau
   visé. Une question dont elle connaît déjà la réponse (l'apparence de Pikachu,
   Magicarpe au niveau 20) part, comme l'origine d'un nom qui se lit tout seul
   (Dracaufeu, « draco » et « au feu ») : une étymologie ne vaut que si le nom
   cache quelque chose.
4. **L'exemple le plus riche.** Pour une capacité donnée, choisir le Pokémon qui
   fait apparaître ce que l'outil sait de moins évident : une double faiblesse
   emblématique (Cizayox) ou une immunité due au talent qui ne laisse aucune
   faiblesse (Ohmassacre), une égalité pour un record, deux voies pour une
   évolution (Insécateur), une forme régionale d'un Pokémon connu (Arcanin de
   Hisui). Éviter un Pokémon à plusieurs formes quand la réponse
   en dépend (les faiblesses de Motisma).
5. **Aucun échec connu.** Lire la réponse, pas le statut de la trace : une
   réponse coupée, à côté de la question ou complétée de mémoire est un échec,
   même notée `answered`. La question retirée est notée dans `CHANTIER.md` avec
   sa cause, et revient quand une réponse correcte est constatée.
6. **Réponse illustrée.** La réponse cite des Pokémon, tous affichés : cinq
   résultats au plus (`MAX_IMAGES`). Un « top N » vaut mieux qu'un record seul,
   plusieurs images valant mieux qu'une.
7. **Pas de doublon.** Deux questions voisines ne donnent pas la même réponse :
   une variante porte un filtre, une statistique ou une capacité de l'outil que
   l'autre ne montre pas. Un même type de question peut revenir plus loin dans
   la liste, jamais à la suite ; le contraire d'un record (les plus légers
   après les plus lourds) n'est pas un doublon. Le doublon se juge sur toute
   la démo : « Léviator est-il de type Dragon ? » répète « Dracaufeu est-il un
   dragon ? » même dans une autre liste. La Vitesse ne sert qu'une fois
   par liste.
8. **Pokémon variés.** Dès « Je connais Pokémon », un Pokémon n'apparaît qu'une
   fois par liste ; préférer un Pokémon connu avec un versant méconnu.
9. **Capacités équilibrées.** Chaque liste couvre les outils qui conviennent à
   son niveau (recherche et classements, types, évolutions, capacités, CT,
   statistiques de base, numéro de Pokédex, capacité signature, fiche, recherche
   documentaire), sans qu'un seul domine.
10. **Contraintes empilées.** Une question à trois contraintes ou plus est
    admise, jamais deux à la suite.
11. **Vitrine.** Les trois premières de chaque liste sont ce qu'un visiteur
    voit ; leur message est « il sait faire beaucoup de choses ». Les neuf
    montrent donc neuf capacités différentes, sans répétition ni dans un bouton
    ni entre boutons : un visiteur qui clique une fois sur chaque bouton ne doit
    pas voir deux classements. Aujourd'hui : classement, comptage, texte
    Poképédia ; évolution, statistiques de base, étymologie ; capacités par
    niveau et par jeu, recherche par talent, CT. La première de
    « Je découvre », affichée déjà répondue à l'ouverture, est vue par tous :
    la plus visuelle. Celle
    d'« Expert » est la preuve de sérieux : plusieurs contraintes tenues. Pas de
    question documentaire avant la position 3 : la base documentaire charge
    encore. Grille d'une réponse de vitrine, jugée sur le modèle de la démo
    (`scripts/batch/questions_vitrine.txt`) : juste ; complète, non coupée ;
    en phrase, la question reprise avec au moins un fait autour, pas des noms
    nus ; les Pokémon attendus cités, donc illustrés ; aucun mot technique
    (nom de champ, identifiant anglais) ; moins de 15 s hors premier
    chargement de la base documentaire.
12. **Vérification avant ajout.** D'abord la sonde sans modèle,
    `tool_guard._explicit_arguments(extract_explicit_constraints(question))` :
    un dictionnaire vide signifie que tout repose sur le modèle. Puis Qwen en
    local, réponse lue et comparée à la base. Le modèle payant de la démo ne
    sert qu'à chercher une erreur anticipée, nommée à l'avance. Une question
    fermée (« Dracaufeu est-il un dragon ? », « Mélofée a-t-il toujours été de
    type Fée ? ») réussie avec Qwen peut échouer avec lui : il lance deux
    outils à la fois, et une erreur ou un refus du second donne une abstention.
13. **Questions documentaires.** Une question précise sur une description
    (« Pourquoi Miaouss aime-t-il les pièces ? ») sonne fabriquée, sauf
    curiosité célèbre (le crâne d'Osselait, le déguisement de Mimiqui). La
    forme naturelle est ouverte : « Quelle anecdote peux-tu me donner sur
    Y ? ». « Quelle est la description du Pokédex de X ? » a reçu la physionomie
    de la page et non les textes du Pokédex (Qwen, 8 octobre 2026) : forme non
    retenue.
14. **Étymologies.** Seulement les noms à référence cachée, que l'on ne devine
    pas en les lisant : Lokhlass (Loch Ness et « la classe ! »), Tygnon (Mike
    Tyson), Lewsor (Roswell à l'envers), Tutafeh (« tout à fait »). Un nom
    transparent (Dracaufeu, Carapuce), un simple calembour (Théffroi) ou une
    référence déjà connue des joueurs (Artikodin et Odin) n'apprend rien. Les
    noms récents sont les plus travaillés ; ils vont aux deux listes de joueurs.
15. **Ton.** Une histoire triste est admise (le crâne d'Osselait), pas la mort
    d'un Pokémon attachant (la flamme de Salamèche). En « Je découvre », une
    image intrigante suffit à rendre accessible un Pokémon inconnu (Mimiqui).

## Démo hébergée

La cible `demo` du `Dockerfile` produit une image autonome pour un hébergeur sans volume : base et
index téléchargés depuis la release à la construction (sommes vérifiées), modèles de recherche
inclus, aucun accès à Hugging Face au démarrage. Le serveur de modèle reste extérieur et se règle
au déploiement : `LLM_BASE_URL`, `LLM_MODEL`, `LLM_MAX_OUTPUT_TOKENS`, et `LLM_API_KEY` fournie par
le gestionnaire de secrets de l'hébergeur.

Déploiement actuel : Cloud Run, service `pokemon-agent`, projet `pokemon-agent-demo`, région
`europe-west1`, 4 Gio et 2 vCPU, une instance au plus et aucune au repos, compte de service
`pokemon-demo`, secret `gemini-api-key`, modèle `gemini-3.8-flash`. Une nouvelle version se publie
en trois temps : construire (`docker build --target demo`), envoyer l'image dans le dépôt
`europe-west1-docker.pkg.dev/pokemon-agent-demo/pokemon-agent`, puis
`gcloud run deploy pokemon-agent --image=<image> --region=europe-west1`, qui garde les autres réglages.

Le fichier de traces du conteneur disparaît avec l'instance. L'image pose `WEB_TRACE_STDOUT=1` :
les traces se lisent dans le journal de l'hébergeur, sous `jsonPayload.web_trace`
(`gcloud logging read "resource.labels.service_name=pokemon-agent AND jsonPayload.web_trace.question:*"`).
Les questions des visiteurs y sont donc conservées.

Mesuré le 8 octobre 2026, une exécution : conteneur prêt en 24 s au déploiement, base documentaire
prête 86 s après l'ouverture de la page ; question structurée en 8 à 18 s. Le démarrage depuis
zéro instance n'est pas mesuré.

## Points non vérifiés

Le graphe en direct n'a été vu que sur des parcours rejoués et sur l'exemple d'ouverture, dans un Chrome sans
fenêtre. Restent à voir : le thème sombre, un écran tactile (pas de survol), une fenêtre de moins de 760 px de
large, où le dessin garde une hauteur minimale et où le panneau peut défiler. L'onglet « Observabilité » et
l'arrêt de la touche Entrée pendant une réponse ont été vus sur une réponse rejouée par un agent simulé
(Chrome sans fenêtre, 1534 × 693 et 1920 × 950, 9 octobre 2026), pas sur une réponse d'un vrai modèle.

L'annulation d'une question abandonnée est testée à la fermeture du générateur
`chat`, avec un agent simulé. Que Gradio ferme bien ce générateur à la fermeture
de l'onglet est lu dans son code (6.29 : `clean_events` puis `reset_iterators`),
pas observé dans un navigateur.

L'isolation de plusieurs navigateurs reste à vérifier : `gr.State(WebSession())`
est construit une seule fois dans `build_app`, sans génération d'identifiants
explicitement attachée à l'ouverture de chaque session navigateur. L'UUID seul
ne suffit donc pas à démontrer cette isolation.

Les fichiers de questions et l'exemple d'ouverture ne sont pas explicitement
déclarés dans les ressources setuptools de `pyproject.toml`. Leur présence dans
une distribution construite
reste à vérifier ; la commande ci-dessus vise le checkout installé en mode éditable.
