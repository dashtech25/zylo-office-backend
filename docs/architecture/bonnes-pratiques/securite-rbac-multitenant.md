# Sécurité et RBAC multi-tenant par module (Zylo Office)

Date de rédaction : 2026-10-08. Portée : recherche web + lecture seule de `app/rbac` et `app/modules_registry`.
Aucun code n'a été modifié. Les constats « code » sont issus de la lecture des fichiers ; ils restent à confirmer par test.

## 0. Sources réellement consultées

Toutes les URL ci-dessous ont été ouvertes avec WebFetch (sauf mention « extrait de recherche »).

- OWASP Authorization : https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- OWASP IDOR Prevention : https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html
- OWASP Multi-Tenant Security : https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html
- OWASP Authentication (throttling, messages génériques, MFA) : https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- OWASP Session Management : https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- OWASP File Upload : https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OWASP CSRF Prevention : https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- OWASP JWT (page Java, pratiques générales) : https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html : **404, non consultée**
- FastAPI, sécurité (premiers pas) : https://fastapi.tiangolo.com/tutorial/security/first-steps/
- FastAPI, dépendances avec yield : https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/
- OWASP ASVS 5.0, liste des chapitres (listing GitHub du tag v5.0.0) : https://github.com/OWASP/ASVS/tree/v5.0.0/5.0/en
- OWASP ASVS, page projet : https://owasp.org/www-project-application-security-verification-standard/
- Casbin, RBAC avec domaines : https://casbin.apache.org/docs/rbac-with-domains/ (redirection depuis casbin.org)
- OpenFGA, concepts (modèle Zanzibar) : https://openfga.dev/docs/concepts
- Odoo 18, sécurité backend (groupes, ir.model.access, ir.rule) : https://www.odoo.com/documentation/18.0/developer/reference/backend/security.html
- ERPNext / Frappe, Role Based Permissions : https://docs.frappe.io/erpnext/role-based-permissions (extrait de recherche seulement, page non ouverte)
- python-jose 3.4.0, changelog : https://newreleases.io/project/pypi/python-jose/release/3.4.0
- python-jose, page security advisories : https://github.com/mpdavis/python-jose/security/advisories (aucun advisory publié)
- NVD CVE-2024-33663 : https://nvd.nist.gov/vuln/detail/CVE-2024-33663 : **page vide côté outil, non vérifiée**
- ASVS 4.x, numéros d'exigences (V4.1.1, 4.1.4, 4.2.1, 4.2.2) : extrait de recherche https://owasp-aasvs4.readthedocs.io/en/latest/V4.1.html et https://owasp-aasvs4.readthedocs.io/en/latest/V4.2.html : **texte non ouvert**

**Non vérifié :** texte exact des exigences ASVS (V3/V4 en 4.0.3 et V7/V8 en 5.0) ; GitHub raw ASVS (404) ; NVD ; OWASP JWT (404). Les points correspondants sont marqués « à vérifier ».

**Attention à la numérotation ASVS.** Les chapitres cités dans la demande (V3 sessions, V4 contrôle d'accès) sont ceux de **ASVS 4.0.x**. Dans **ASVS 5.0.0** (listing du dépôt, vérifié) : V4 = « API and Web Service », V7 = « Session Management », V8 = « Authorization », V6 = « Authentication », V5 = « File Handling », V9 = « Self-contained Tokens ». Il faut citer la version avec le numéro (ex. « ASVS 5.0.0 V8 ») pour éviter toute confusion.

## 1. Constats du code (lecture seule)

Fichiers lus : `app/rbac/models.py`, `app/rbac/permissions.py`, `app/rbac/service.py` (lignes 17-23, 26-135, 183-236), `app/modules_registry/models.py`, `app/modules_registry/permissions.py`.

1. **Org de contrôle = en-tête, org de l'objet = chemin.** `get_current_organization_id` (`app/rbac/service.py:17`) lit `X-Organization-Id`. `require_permission_scoped` (`service.py:204`) prend l'identifiant de ressource dans le chemin, puis appelle `user_has_permission(..., organization_id=<header>, resource_id=<chemin>)`. Rien ne vérifie que la ressource du chemin appartient à l'organisation de l'en-tête. Un utilisateur ayant un rôle org-entière dans l'organisation A peut donc passer `X-Organization-Id: A` avec l'identifiant d'une ressource de B : `_scope_covers` renvoie `True` pour un grant à portée NULL, quel que soit l'objet. **C'est l'IDOR inter-organisations annoncé.** À confirmer par un test d'intégration.
2. **Le moteur est sain sur le principe.** `user_has_permission` (`service.py:92`) : deny explicite prioritaire, absence de grant = refus, portée comparée par type + identifiant. C'est une base correcte.
3. **Le moteur ne lie pas le scope à l'organisation.** `_scope_covers` compare `resourceType`/`resourceId` sans `organizationId` de la ressource. Le contrôle dépend entièrement de l'appelant.
4. **Permissions globales, rôles par organisation.** `Permission.code` est unique globalement avec `moduleCode` (`app/rbac/models.py`), `Role` est unique par `(organizationId, code)`. Le modèle supporte donc déjà « commercial en CRM + lecture seule en Stock » via deux attributions de rôles, mais un rôle n'a pas de module propre : rien n'empêche de mélanger des permissions de plusieurs modules dans un même rôle.
5. **Module activé = table séparée.** `OrganizationModule` (`app/modules_registry/models.py`) porte le statut `active/inactive/trial`. Le lien avec la vérification de permission n'est pas dans le moteur RBAC (il est fait ailleurs, p. ex. `require_module_active` cité dans `app/location/service.py:448`). À vérifier : que toutes les routes passent par les deux contrôles.
6. **Membership implicite.** `user_has_permission` ne vérifie pas explicitement qu'un `OrganizationUser` actif existe pour `(user, organization)` ; l'appartenance est seulement déduite de la présence d'un `UserRole` dans cette organisation.

## 2. Recommandations sourcées

Format : Source / Pratique / Problème prévenu / Applicabilité à Zylo / Coût-limites-risques / Comment la vérifier.

### R1. Le client ne fait jamais autorité sur le tenant
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html
- **Pratique :** « Treat client-supplied tenant identifiers as selectors only. » et « Bind tenant context to a server-verified identity and current tenant membership ». Le tenant est choisi par le client parmi ceux dont l'utilisateur est membre actif ; il n'est jamais cru au-delà.
- **Problème prévenu :** constat 1 (IDOR inter-organisations) et usurpation d'organisation via en-tête.
- **Applicabilité à Zylo :** très forte. Le dépendance `get_current_organization_id` doit valider `X-Organization-Id` contre `OrganizationUser` actif, et toute ressource chargée doit être filtrée par cette organisation.
- **Coût / limites / risques :** faible. Une requête de plus par appel (cacheable par requête via une dépendance FastAPI). Risque : oublier une route qui n'utilise pas la dépendance.
- **Comment la vérifier :** test d'intégration : utilisateur admin de l'org A, ressource de l'org B, requête avec `X-Organization-Id: A` et l'identifiant de B → attendu 404 (ou 403 uniforme). Ajouter un test par route qui modifie une ressource.

### R2. Filtrer chaque accès objet par l'organisation (pas seulement par permission)
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html ; https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- **Pratique :** « Perform access control checks on every request for the specific object ». Charger avec `WHERE id = :id AND organizationId = :org`, ne jamais faire `get(id)` puis vérifier. Pour un ID absent ou interdit, répondre de manière identique (« map both cases to the same public response », p. ex. 404).
- **Problème prévenu :** IDOR (constat 1) et énumération d'identifiants.
- **Applicabilité à Zylo :** forte. Les services `get_role` (`app/rbac/service.py:367`) font déjà ce test (`role.organizationId != organization_id`) : c'est le bon modèle, à généraliser à tous les modules.
- **Coût / limites / risques :** modéré : une revue de toutes les requêtes par ID. Limite : ORM helper = défense en profondeur, pas une garantie (citation Multi-Tenant ci-dessus).
- **Comment la vérifier :** grep des `session.get(` et `select(` par ID dans `app/*/service.py` ; chaque occurrence doit porter un filtre `organizationId`. Test automatisé par ressource.

### R3. Isolation en base (PostgreSQL RLS) comme filet
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html
- **Pratique :** pour les tables partagées, activer la RLS et vérifier que le rôle applicatif ne la contourne pas ; « Re-establish the tenant context for every transaction » (`set_config` par transaction, pas par connexion réutilisée) ; tester avec le même rôle et le même pool qu'en production.
- **Problème prévenu :** oubli d'un filtre dans une requête brute ou une opération en masse.
- **Applicabilité à Zylo :** moyenne. Le pool SQLAlchemy async impose la règle « réinitialiser le contexte à chaque transaction ».
- **Coût / limites / risques :** élevé à mettre en place (migrations, rôle sans BYPASSRLS, tests par table). Risque : performances et erreurs de contexte si mal fait.
- **Comment la vérifier :** `SELECT relname, relrowsecurity FROM pg_class` ; connexion avec le rôle applicatif, tentative de lecture d'une autre organisation → 0 ligne.

### R4. Deny by default, vérification à chaque requête, pas de confiance client
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html ; FastAPI https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/
- **Pratique :** « For security purposes an application should be configured to deny access by default. » ; « Permission should be validated correctly on every request » ; « Developers must never rely on client-side access control checks. » Centraliser dans une dépendance FastAPI (sous-dépendances : auth → membership → permission).
- **Problème prévenu :** routes oubliant le contrôle ; masquage UI pris pour une sécurité.
- **Applicabilité à Zylo :** déjà présente (`user_has_permission` renvoie False par défaut ; `require_permission*`). À renforcer : rendre obligatoire une dépendance de permission sur chaque route métier (test qui énumère les routes FastAPI et refuse celles sans dépendance de sécurité, sauf liste blanche).
- **Coût / limites / risques :** faible. Limite : le « rien oublié » n'est garanti que par un test d'inventaire.
- **Comment la vérifier :** test pytest qui parcourt `app.routes` et échoue si une route métier n'a pas de dépendance `require_*` dans son arbre de dépendances.

### R5. Modèle d'autorisation : RBAC par module + portée de ressource ; ReBAC plus tard si besoin
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html (« RBAC is poorly suited for use cases » au niveau objet ; « ABAC and ReBAC should typically be preferred ») ; https://casbin.apache.org/docs/rbac-with-domains/ (rôles par domaine : `g(sub, role, dom)` + `r.dom == p.dom`) ; https://openfga.dev/docs/concepts (tuples user/relation/object, `check`)
- **Pratique :** garder le RBAC par module pour le « quoi » (permissions `module.ressource.action`), et une portée ressource pour le « où ». Casbin et Odoo confirment le même pattern : le rôle est lié à un domaine (tenant) ; OpenFGA apporte un moteur relationnel dédié, plus lourd.
- **Problème prévenu :** explosion du nombre de rôles (un rôle par combinaison module × organisation × niveau).
- **Applicabilité à Zylo :** le modèle actuel (`UserRole` + `UserPermissionGrant` avec portée) est déjà de ce type. Introduire OpenFGA maintenant serait un coût d'infrastructure sans gain démontré.
- **Coût / limites / risques :** Casbin/OpenFGA = service supplémentaire, apprentissage, synchronisation. Rester en SQL est le meilleur compromis tant que les portées restent « organisation » ou « une station/un entrepôt ».
- **Comment la vérifier :** cas de test matriciel (utilisateur × module × action × org) avec la vérité attendue écrite à la main.

### R6. Odoo : règles globales et de groupe (référence de combinaison)
- **Source :** https://www.odoo.com/documentation/18.0/developer/reference/backend/security.html (vérifié) : « Access rights are additive » ; « Record rules are default-allow » ; règles de groupe combinées en OR ; règles globales combinées en AND (« both must be satisfied »), « The global and group rulesets intersect ». Un ensemble global non chevauchant supprime tout accès.
- **Problème prévenu :** une règle de restriction ajoutée qui en contredit une autre sans qu'on le voie.
- **Applicabilité à Zylo :** le `deny` de Zylo (`service.py:92`) est déjà plus strict qu'Odoo (Odoo n'a pas de refus explicite). Odoo rappelle un piège : la composition des règles doit être testée.
- **Coût / limites / risques :** aucun coût ; c'est une référence de conception.
- **Comment la vérifier :** tests de composition deny + allow à portées différentes (déjà la logique de `_scope_covers`).

### R7. ERPNext : permissions de rôle + « User Permissions » par document, avec propagation par liens
- **Source :** extrait de https://docs.frappe.io/erpnext/role-based-permissions (non ouvert en entier). Extrait : User Permissions restreignent l'accès à des documents précis et « also get applied if they are related to the current Document Type through Link Fields ».
- **Pratique :** une restriction par enregistrement (ex. une société) se propage aux documents liés.
- **Problème prévenu :** fuite par document lié (une commande visible alors que le client est restreint).
- **Applicabilité à Zylo :** à retenir pour la portée ressource : ne pas supposer que la restriction d'un parent couvre les enfants ; chaque module doit filtrer par organisation (R2).
- **Coût / limites / risques :** modéré. Le comportement exact de propagation n'a pas été vérifié sur la page complète.
- **Comment la vérifier :** test « enfant d'une ressource restreinte » non visible.

### R8. Throttling de connexion par compte, messages génériques
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- **Pratique :** compteur d'échecs lié au **compte**, pas à l'IP ; seuil, fenêtre et durée ; backoff exponentiel possible ; réponse identique (« Login failed; Invalid user ID or password. ») et même code HTTP, même temps de traitement ; journaliser les verrouillages ; ne pas bloquer la récupération de mot de passe ; MFA « wherever possible ».
- **Problème prévenu :** brute force et énumération de comptes (absence de rate limiting constatée).
- **Applicabilité à Zylo :** forte. Pas besoin de Redis : compteur en PostgreSQL (`loginAttempt`) suffit au départ. Limite IP en plus (protection globale).
- **Coût / limites / risques :** faible à modéré. Risque : verrouillage utilisé en déni de service sur un compte ; d'où le backoff plutôt que le verrouillage fixe.
- **Comment la vérifier :** test : 20 échecs sur un compte → réponses identiques et 429/423 ensuite ; vérifier que la réponse « compte inconnu » et « mauvais mot de passe » sont identiques en code et en contenu.

### R9. Jetons : ne pas les mettre dans localStorage ; cookie HttpOnly ou BFF
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html : « Do not store authentication tokens, session IDs, JWTs, refresh tokens, or any credential in » localStorage/sessionStorage ; cookies `HttpOnly; Secure; SameSite=Strict` (ou Lax) ; préfixe `__Host-` recommandé ; expiration absolue et d'inactivité appliquée côté serveur ; renouvellement de l'ID après élévation de privilège ; invalidation côté serveur à la déconnexion (« deleting a cookie alone does not invalidate a stolen copy ») ; `Cache-Control: no-store` sur les réponses sensibles.
- **Problème prévenu :** vol de jeton par XSS (constat « tokens en localStorage »).
- **Applicabilité à Zylo :** forte. Avec cookies, la protection CSRF devient nécessaire (R10).
- **Coût / limites / risques :** modéré : changement côté Next.js (route handlers ou BFF) et CORS avec credentials. HttpOnly ne protège pas contre un XSS actif : compléter par CSP.
- **Comment la vérifier :** DevTools → `document.cookie` ne doit pas montrer le jeton ; `localStorage` vide après login ; en-têtes `Set-Cookie` avec HttpOnly, Secure, SameSite.

### R10. CSRF : sans cookie, rien à faire ; avec cookie, protection obligatoire
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html : le risque vient de l'envoi automatique des cookies ; « Do not use GET requests for state changing operations. » ; « Cross-Site Scripting (XSS) can defeat all CSRF mitigation techniques! »
- **Pratique :** si R9 est adopté, ajouter un token synchronisé ou une vérification d'en-tête et SameSite ; ne jamais modifier l'état en GET.
- **Problème prévenu :** actions effectuées à l'insu de l'utilisateur via cookie.
- **Applicabilité à Zylo :** conditionnelle à R9.
- **Coût / limites / risques :** faible. Les double-submit cookie naïfs sont explicitement déconseillés.
- **Comment la vérifier :** requête POST cross-origin sans jeton → 403 ; GET qui modifie → aucune route.

### R11. Uploads : liste blanche, contenu vérifié, nom généré, hors webroot, taille bornée
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html : « List allowed extensions » ; « blocking specific extensions is a weak protection method on its own » ; « don't trust the Content-Type header » ; signature de fichier « should not be used on its own » ; « Change the filename to something generated by the application » ; « Store the files on a different server. If that's not possible, store them outside of the webroot » ; limite de taille (après décompression si extraction).
- **Problème prévenu :** exécution de fichiers, écrasement, stockage non borné.
- **Applicabilité à Zylo :** forte (constat « uploads sans liste blanche »). Ajouter aussi : le fichier doit porter `organizationId` et être servi après contrôle d'accès (R2).
- **Coût / limites / risques :** faible. Limite : vérifier aussi les archives et les SVG (non traités par les sources ouvertes).
- **Comment la vérifier :** test d'upload `.html`, `.svg` avec script, `.php` renommé en `.pdf` → rejet ; URL de fichier d'une autre organisation → 404.

### R12. Dépendances JWT : python-jose à mettre à jour (ou migrer)
- **Source :** https://newreleases.io/project/pypi/python-jose/release/3.4.0 (ouvert) : « Fix for CVE-2024-33663 - signing JWT with public key is now forbidden » ; « Fix for CVE-2024-33664 - JWE limited to 250KiB ». Extrait de recherche : 3.5.0 publiée le 2025-05-28 (non vérifié sur PyPI).
- **Pratique :** épingler `python-jose>=3.4.0` au minimum ; vérifier la dernière version avant de figer ; fixer l'algorithme attendu côté décodage (liste blanche d'algorithmes) et valider `exp`, `iss`, `aud`.
- **Problème prévenu :** confusion d'algorithme (CVE-2024-33663 selon le changelog), déni de service par JWE volumineux (CVE-2024-33664).
- **Applicabilité à Zylo :** forte (constat « python-jose ancien »).
- **Coût / limites / risques :** faible pour monter de version ; migration vers une bibliothèque plus active est une option à évaluer (non étudiée ici). Les descriptions de CVE n'ont pas pu être lues (NVD vide) : la correspondance exacte n'est pas vérifiée.
- **Comment la vérifier :** `pip show python-jose` ; test : un token signé avec la clé publique en HS256 doit être refusé.

### R13. Secrets par défaut
- **Source :** https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html (le guide impose un refus des identifiants non générés par l'application ; le secret JWT doit être fort) et Authorization (« explicit configuration rather than framework defaults »).
- **Pratique :** aucune valeur par défaut acceptée en production ; démarrage en échec si le secret est absent ou faible.
- **Applicabilité à Zylo :** forte (constat).
- **Comment la vérifier :** test de démarrage avec `ENV=production` et secret par défaut → exception.

## 3. Ce que la recherche ne tranche pas

- Numéros et textes ASVS 4.0.3 (V3, V4) : non confirmés ; la numérotation 5.0 est vérifiée (V7 sessions, V8 autorisation).
- Propagation exacte des User Permissions ERPNext : extrait seulement.
- Correspondance exacte CVE python-jose / version minimale sûre : non confirmée par NVD.

## 4. Recommandation : modèle de données RBAC par module

### Décision
Garder le modèle existant (`Permission` globale `module.ressource.action`, `Role` par organisation, `RolePermission`, `UserRole` avec portée, `UserPermissionGrant` avec deny) : il couvre déjà le besoin « commercial en CRM, lecture seule en Stock ». Ne pas introduire OpenFGA ni Casbin à ce stade.

### Changements proposés (ordre d'exécution)
1. **Ajouter `Role.moduleCode` (nullable)** : un rôle peut être « global » (multi-module, existant) ou « module » (ex. `crm.commercial`, `stock.lecture`). Cela rend l'attribution lisible et évite les rôles fourre-tout. Migration additive, rétro-compatible.
2. **Contrainte de cohérence** : au moment de `update_role_permissions` et `assign_role`, vérifier que toutes les permissions d'un rôle `moduleCode` appartiennent à ce module (`Permission.moduleCode`). Coût : faible, dans `service.py`.
3. **Membership explicite** : une table/check `OrganizationUser` actif obligatoire, faite une fois dans la dépendance `get_current_organization_id` (R1). Le contrôle de module activé (`OrganizationModule.status`) va dans la même dépendance de permission, pas dans chaque route.
4. **Portée ressource validée par organisation** : toute `resourceId` d'une attribution ou d'un grant doit référencer une ressource de la même `organizationId` (contrôle au write, `assign_role` / `create_grant`, et si possible contrainte FK composite `(organizationId, resourceId)`). Cela ferme la faille côté écriture ; la lecture garde R2.
5. **Dépendance de permission sur chemin** : `require_permission_scoped` doit charger la ressource avec `organizationId == organization_id` avant de tester la portée ; sinon 404 uniforme (R2).
6. **Niveaux d'accès** : rester sur les codes `module.ressource.action` ; « lecture seule » = absence des actions `write`. Ne pas créer un niveau numérique : il masquerait les vraies permissions.

### Pourquoi pas un modèle plus lourd
- Casbin et Odoo confirment la logique « rôle × domaine × objet », déjà présente ici.
- OpenFGA est pertinent si le partage fin par objet (partage d'un document entre organisations, hiérarchie d'équipes) devient un besoin. Coût : un service supplémentaire, une synchronisation des tuples, un second point de vérité. À reconsidérer seulement si ce besoin est confirmé.

### Vérification du modèle
- Test matriciel : 3 organisations × 3 modules × 4 actions × 2 utilisateurs (un admin, un lecteur), résultat attendu écrit à la main.
- Test de non-régression IDOR (R1, R2) sur toutes les routes qui prennent un identifiant de chemin.
- Test de composition deny/allow à portées différentes.

## 5. Priorités (résumé)

1. Corriger l'IDOR inter-organisations (R1, R2) : bloquant.
2. Supprimer les secrets par défaut et monter python-jose (R12, R13).
3. Limiter les tentatives de connexion par compte (R8).
4. Sortir les jetons de localStorage (R9, R10).
5. Durcir les uploads (R11).
6. Ajouter `Role.moduleCode` et les contraintes de cohérence (section 4).
7. Évaluer la RLS PostgreSQL (R3) après 1 à 6.
