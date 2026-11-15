# Modèles embarqués dans l'image du worker

Copie des 6 fichiers de `data/models/` dont le traitement partie par partie a besoin (`rlpi.game`).
Ils sont versionnés ici, exception à la règle « `data/` n'est jamais versionné », pour que la GitHub Action
puisse les mettre dans l'image `rlpi-worker` sans étape manuelle sur le serveur.

Après un réentraînement (`rlpi.value train`, `rlpi.decisions touches|placement`, `rlpi.perf`), recopier :

    value_h5.txt  policy_touch.txt  q_touch.txt  placement_x.txt  placement_y.txt  perf_reference.npz

depuis `data/models/`, commiter et pousser : les workers sont reconstruits avec les nouveaux modèles.
