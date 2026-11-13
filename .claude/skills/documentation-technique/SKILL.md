---
name: documentation-technique
description: Rédige ou met à jour un document technique de docs/ à partir du code réel, dans une arborescence de petits fichiers.
when_to_use: Quand un comportement, un module, une API ou une procédure doit être documenté ou corrigé dans docs/.
allowed-tools: Read Grep Glob Write Edit Bash
---

# Documentation technique

1. Trouver le dossier du sujet dans `docs/README.md`. Un fichier = un sujet ; au-delà de 300 lignes, découper.
2. Vérifier chaque affirmation dans le code (`grep`, lecture) et la citer par chemin:ligne quand elle n'est pas évidente.
3. Ne pas recopier un fichier de code : décrire le contrat et l'intention.
4. Les rapports de livraison et les anciens documents vont dans `docs/archive/`, jamais réécrits.
5. Une question ouverte va dans `docs/questions/<catégorie>/`, avec options et recommandation vérifiée.
6. Lancer `scripts/docs/generer_index.sh` puis `scripts/docs/verifier_liens.sh`. Zéro lien cassé.

Rapport : fichiers touchés, liens vérifiés, affirmations non vérifiées.
