# Documentation, architecture et instructions pour agents : recherche de bonnes pratiques

Rapport de recherche web. Date de consultation : 2026-10-08. Périmètre : Zylo (docs en arborescence, petits fichiers, `docs/questions/` avec recommandation vérifiée).

Légende de vérification :
- **[V]** page consultée et contenu confirmé dans la réponse de la page.
- **[P]** page consultée, mais le contenu demandé n'y figure pas (partiel).
- **[NV]** non vérifié : la page n'a pas pu être récupérée. Ne pas citer comme source.

---

## 1. Documentation progressive en arborescence (Diátaxis, ADR, C4)

### 1.1 Diátaxis
- **Source** : https://diataxis.fr/ [P]. Les quatre formes sont confirmées (tutoriels, guides pratiques, référence, explication). La page ne développe pas les définitions détaillées ; elles sont à lire sur les pages liées.
- **Pratique** : séparer la documentation selon le besoin de l'utilisateur (apprendre, réaliser une tâche, consulter, comprendre) plutôt que selon le sujet technique. L'architecture de la doc suit ces quatre besoins.
- **Problème prévenu** : un même fichier qui mélange tutoriel, référence et explication, qui devient illisible et vite obsolète.
- **Applicabilité à Zylo** : le dossier `docs/architecture/` contient déjà un sous-dossier `performance/`. Ajouter `bonnes-pratiques/` (ce rapport) suit la même logique par sujet. Pour Zylo, une séparation simple suffit : `docs/architecture/` (explication et décisions), `docs/questions/` (questions ouvertes avec recommandation vérifiée), et la doc de référence au plus près du code.
- **Coût / limites** : coût de maintenance modéré. Sur un petit projet, quatre catégories formelles sont trop lourdes ; deux ou trois dossiers suffisent.
- **Vérification** : [P] https://diataxis.fr/

### 1.2 ADR (décisions d'architecture)
- **Source** : https://github.com/joelparkerhenderson/architecture-decision-record [V] (page consultée, réponse obtenue). Le dépôt liste une douzaine de gabarits (dont MADR) sans en imposer un.
- **Pratique** : une ADR = un document court qui consigne une décision, son contexte et ses conséquences. Une décision par ADR. Dater l'ADR. Une décision remplacée donne une nouvelle ADR qui en référence l'ancienne. Ajouter des mises à jour datées est accepté (le dépôt reconnaît que la mutabilité pure fonctionne moins bien en pratique).
- **Problème prévenu** : perdre le « pourquoi » d'un choix technique et le rediscuter sans fin ; ou relire une décision périmée sans savoir qu'elle a été remplacée.
- **Applicabilité à Zylo** : un gabarit court (Contexte / Décision / Conséquences / Alternatives écartées, plus une date et un statut `acceptée` ou `remplacée par ...`). Stocker dans `docs/architecture/decisions/` avec numérotation `NNNN-titre.md`. Les `docs/questions/` restent pour les questions encore ouvertes ; une question tranchée devient une ADR.
- **Coût / limites** : écrire une ADR a un coût. Réserver aux décisions difficiles à inverser (structure des modules, persistance, contrats entre modules).
- **Vérification** : [V] https://github.com/joelparkerhenderson/architecture-decision-record. Note : https://adr.github.io/ n'a pas pu être récupéré [NV].

### 1.3 C4 model
- **Source** : https://c4model.com/ [P]. Les quatre niveaux sont confirmés : contexte système, conteneurs, composants, code ; plus diagrammes de paysage, dynamiques et de déploiement. La page ne dit pas combien de diagrammes produire ni quand s'arrêter.
- **Pratique** : décrire l'architecture par niveaux de zoom (du système entier jusqu'au code). Un diagramme par niveau utile, pas plus.
- **Problème prévenu** : un schéma unique illisible, ou une documentation de composants qui se désynchronise du code.
- **Applicabilité à Zylo** : pour un backend, viser au plus les niveaux contexte et conteneurs (et composants pour le monolithe modulaire, voir section 3). Le niveau code se remplace par les docstrings.
- **Coût / limites** : diagrammes à maintenir. Préférer du texte + diagramme ASCII/Mermaid versionné dans le dépôt.
- **Vérification** : [P] https://c4model.com/ ; https://c4model.com/abstractions [P] (confirme la hiérarchie : système -> conteneurs -> composants -> code, sans règle de quantité).

---

## 2. Commentaires d'intention (« pourquoi » plutôt que « quoi »)

- **Source** : Google Engineering Practices, https://google.github.io/eng-practices/review/ : les pages de revue (reviewer, comments, standard) n'ont pas pu être récupérées [NV]. Aucune citation Google n'est donc retenue ici.
- **Pratique** (principe général, non vérifié sur la source Google) : le code dit *quoi* ; le commentaire doit dire *pourquoi* (contrainte externe, invariant, piège évité, choix non évident). Les docstrings décrivent le contrat (entrées, sorties, erreurs) et non l'implémentation.
- **Problème prévenu** : commentaires qui paraphrasent le code et deviennent faux, ou absence de raison qui pousse le prochain développeur (ou agent) à « nettoyer » une protection importante.
- **Applicabilité à Zylo** : règle simple : un commentaire doit justifier une chose non évidente. Pas de commentaire qui répète le nom de la fonction. Les décisions structurantes vont dans une ADR, le commentaire renvoie à elle.
- **Coût / limites** : la règle est subjective ; à faire respecter en revue, pas par outil.
- **Vérification** : [NV] Google eng-practices. Recommandation à confirmer si une citation est requise.

---

## 3. Monolithe modulaire

### 3.1 Monolith First (Fowler)
- **Source** : https://martinfowler.com/bliki/MonolithFirst.html [V].
- **Pratique** : commencer par un monolithe, mais le concevoir modulaire (frontières d'API et de données) pour pouvoir le découper plus tard. Une frontière mal placée au départ coûte cher à déplacer entre services, et même entre modules si les dépendances sont mal maîtrisées.
- **Citations vérifiées** : « By building a monolith first, you can figure out what the right boundaries are » ; « Most systems acquire too many dependencies between their modules, and thus can't be sensibly broken apart. » ; « Any refactoring of functionality between services is much harder than it is in a monolith. »
- **Problème prévenu** : microservices prématurés avec frontières instables ; ou monolithe « boule de boue » impossible à découper.
- **Applicabilité à Zylo** : directement pertinent. Découper par bornes de contexte métier, chaque module exposant un contrat public minimal (interface / façade) et ne lisant pas les tables d'un autre module.
- **Coût / limites** : l'auteur précise que l'évidence est mince et que son avis est tentatif.

### 3.2 Bornes de contexte (Fowler)
- **Source** : https://martinfowler.com/bliki/BoundedContext.html [V] (partielle : la page ne parle pas de modules ni d'un « common » anti-pattern).
- **Pratique** : un grand domaine se découpe en contextes, chacun avec son modèle cohérent ; un même mot (« Client », « Produit ») peut signifier des choses différentes d'un contexte à l'autre ; il faut une carte des contextes et une traduction explicite entre eux.
- **Problème prévenu** : un modèle unique partagé par tout le système, impossible à faire évoluer.
- **Applicabilité à Zylo** : appliquer l'idée aux modules : ne pas créer un module `common/` ou `shared/` fourre-tout. Ce qui est réellement partagé se limite à des types stables et petits (identifiants, erreurs, horloge), et chaque module garde ses propres modèles.
- **Coût / limites** : l'interdiction du « common » est une recommandation de conception, non une citation de Fowler : pour le « common » formulé ainsi, la page ne le dit pas [P].

---

## 4. Clean Architecture avec parcimonie
- **Source** : aucune page consultée avec succès sur ce sujet dans cette session.
- **Pratique** (non vérifié en source) : séparer le domaine, les cas d'usage et l'infrastructure. Utile quand la logique métier est riche ; sur un CRUD simple, c'est du code en plus.
- **Applicabilité à Zylo** : n'introduire les couches que là où la logique métier justifie l'indirection. Commencer par des modules avec façade publique (section 3).
- **Vérification** : [NV]. Aucune citation retenue. Recherche à compléter si ce sujet doit être tranché.

---

## 5. Revue de code et gestion d'issues
- **Source** : Google eng-practices [NV] (voir section 2). Non vérifié dans cette session.
- **Pratique** (principe connu, non cité) : approuver une modification dès qu'elle améliore la santé globale du code, même imparfaite ; revues rapides ; commentaires explicites (distinguer ce qui bloque de ce qui est une suggestion).
- **Gabarit d'issue** : titre court, contexte, comportement attendu, comportement actuel, critères d'acceptation, lien vers l'ADR ou la question concernée. Non vérifié dans une source consultée.
- **Applicabilité à Zylo** : lier les issues à `docs/questions/` quand une question donne lieu à une recommandation vérifiée.
- **Vérification** : [NV].

---

## 6. Instructions durables pour agents Claude Code

### 6.1 CLAUDE.md et mémoire
- **Source** : https://code.claude.com/docs/en/memory [V] (la doc a migré depuis docs.claude.com, redirection suivie).
- **Pratique confirmée** :
  - Cible : moins de 200 lignes par CLAUDE.md ; au-delà, l'adhérence diminue.
  - Imports : syntaxe `@chemin/fichier`. Les fichiers importés se chargent au lancement : l'import n'allège pas le contexte.
  - Chargement : `CLAUDE.md` et `CLAUDE.local.md` du répertoire courant et de ses parents, concaténés. Les `CLAUDE.md` des sous-dossiers se chargent à la demande, quand Claude lit un fichier de ce dossier.
  - Règles scopées : `.claude/rules/*.md` (un sujet par fichier), avec un champ `paths:` pour limiter le chargement aux fichiers concernés.
  - Consistance : les instructions contradictoires sont arbitrairement tranchées ; relire périodiquement.
  - Commandes : `/init` (génère un point de départ), `/memory` (ouvre les fichiers), `/context` (vérifie ce qui est chargé), `/doctor prompt-audit` (audit des fichiers d'instructions).
  - Rappel de la doc : CLAUDE.md est du contexte, pas une configuration imposée ; pour bloquer une action, utiliser un hook PreToolUse.
- **Problème prévenu** : instructions trop longues qui sont ignorées, ou règles contradictoires.
- **Applicabilité à Zylo** : un CLAUDE.md court (commandes, conventions, pointeurs vers `docs/architecture/`) ; les règles par zone dans `.claude/rules/` avec `paths:`. Ne pas y copier la doc d'architecture : la référencer.

### 6.2 Subagents (`.claude/agents/*.md`)
- **Source** : https://code.claude.com/docs/en/sub-agents [V] (ancienne URL docs.claude.com redirigée).
- **Frontmatter vérifié** : seuls `name` et `description` sont requis. Champs optionnels notables : `tools` (chaîne séparée par virgules ou liste YAML ; hérite de tous les outils si omis), `disallowedTools`, `model` (`sonnet`, `opus`, `haiku`, `fable`, un ID complet ou `inherit`), `permissionMode`, `maxTurns`, `skills`, `memory`, `effort`, `isolation`, `color`. Les champs inconnus sont ignorés sans erreur. Le prompt système suit la fermeture `---`.
- **Priorité des emplacements** : réglages managés > option `--agents` > `.claude/agents/` (projet) > `~/.claude/agents/` > dossier `agents/` d'un plugin.
- **Problème prévenu** : un sous-agent qui hérite de tous les outils ; une description trop vague qui empêche la délégation.
- **Applicabilité à Zylo** : un sous-agent de revue en lecture seule (`tools: Read, Grep, Glob`) pour vérifier la cohérence doc/code.

### 6.3 Skills (`.claude/skills/<nom>/SKILL.md`)
- **Source** : https://code.claude.com/docs/en/skills [V] (ancienne URL docs.claude.com redirigée).
- **Frontmatter vérifié** : aucun champ requis ; `description` est recommandée. Champs notables : `when_to_use`, `allowed-tools` (outils utilisables sans demande de permission ; séparés par des espaces dans l'exemple), `disable-model-invocation`, `user-invocable`, `context: fork`, `agent`, `paths`, `model`, `effort`. Champs inconnus ignorés. La ligne `---` d'ouverture doit être la première du fichier.
- **Limites** : `description` + `when_to_use` tronqués à 1 536 caractères dans la liste ; SKILL.md sous 500 lignes, le détail va dans des fichiers séparés du dossier.
- **Applicabilité à Zylo** : une skill « documenter une décision » (crée une ADR à partir d'une question tranchée) avec `disable-model-invocation: true` pour ne pas se déclencher seule.

### 6.4 Gabarits exacts (format vérifié dans les exemples officiels)

Subagent, `.claude/agents/revue-architecture.md` :
```
---
name: revue-architecture
description: Vérifie qu'une modification respecte les frontières des modules et les ADR. À utiliser après une modification de code backend.
tools: Read, Grep, Glob
model: sonnet
---

Tu es un relecteur d'architecture. Pour chaque écart constaté, cite le fichier, la règle violée et la décision (ADR) concernée.
```

Skill, `.claude/skills/nouvelle-adr/SKILL.md` :
```
---
name: nouvelle-adr
description: Rédige une ADR datée à partir d'une question tranchée dans docs/questions/.
when_to_use: Quand l'utilisateur demande de transformer une recommandation validée en décision d'architecture.
disable-model-invocation: true
allowed-tools: Read Grep Write
---

Instructions de la skill ici.
```

---

## 7. Synthèse de recommandations pour Zylo
1. Arborescence légère : `docs/architecture/` (explication), `docs/architecture/decisions/` (ADR numérotées, datées, avec statut), `docs/questions/` (questions ouvertes).
2. Modules métier avec façade publique ; pas de `common/` fourre-tout.
3. C4 limité aux niveaux contexte et conteneurs.
4. Commentaires : justifier le pourquoi ; docstrings pour les contrats.
5. CLAUDE.md < 200 lignes, règles `.claude/rules/` scopées, sous-agents et skills avec les frontmatters ci-dessus.

## 8. Sources consultées
- [V] https://martinfowler.com/bliki/MonolithFirst.html
- [V] https://martinfowler.com/bliki/BoundedContext.html
- [V] https://code.claude.com/docs/en/memory
- [V] https://code.claude.com/docs/en/sub-agents
- [V] https://code.claude.com/docs/en/skills
- [V] https://github.com/joelparkerhenderson/architecture-decision-record
- [P] https://diataxis.fr/
- [P] https://c4model.com/
- [P] https://c4model.com/abstractions
- [NV] https://google.github.io/eng-practices/review/ (pages reviewer/comments/standard : échec de récupération)
- [NV] https://adr.github.io/ (échec de récupération)
