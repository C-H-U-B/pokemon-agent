# Transmettre un travail

Un relais doit permettre au prochain intervenant de reprendre sans reconstruire toute la conversation. Il peut être destiné à un humain ou à un autre agent ; il n'implique pas de lancer automatiquement des agents supplémentaires.

## Informations à transmettre

```text
Objectif et critère de fin :
Périmètre autorisé :
État : en cours / prêt à relire / bloqué
Constats vérifiés (fichier, fonction ou résultat à l'appui) :
Modifications effectuées et fichiers concernés :
Validation (commandes, résultats, prérequis manquants) :
Travaux préexistants à préserver :
Questions restantes et prochaine action concrète :
Processus encore actifs et effets locaux éventuels :
```

Garder les champs utiles au contexte. Séparer une proposition d'une modification déjà réalisée et une validation simulée d'une validation avec les vraies données ou les modèles.

## Si plusieurs intervenants travaillent ensemble

Définir les fichiers ou responsabilités de chacun avant les modifications. Signaler un changement de contrat partagé avant qu'un autre intervenant ne s'appuie dessus. Le responsable de l'intégration relit les différences et vérifie les interactions entre composants.

Ne pas annuler un changement inconnu pour obtenir un arbre Git propre. Les comptes rendus temporaires n'ont pas vocation à être ajoutés à l'historique de développement ; celui-ci conserve les évolutions effectivement réalisées.
