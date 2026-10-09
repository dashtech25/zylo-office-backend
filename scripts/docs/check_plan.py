#!/usr/bin/env python3
"""Contrôle de cohérence du plan de remise sur pied (T-016).

Source de vérité : les fiches docs/plans/taches/T-XXX-*.md. Le registre
(docs/plans/REGISTRE_TACHES.md) et la liste d'issues (docs/plans/ISSUES_A_CREER.md)
sont dérivés des fiches, jamais édités à la main.

Usage :
  python3 scripts/docs/check_plan.py              contrôle seul (code 1 si erreur)
  python3 scripts/docs/check_plan.py --generer    régénère registre et issues, puis contrôle
  python3 scripts/docs/check_plan.py --gh         affiche les commandes gh (ne les exécute pas)

Intention de chaque contrôle (PLAN_REMISE_SUR_PIED.md §2 et §10) :
  - une dépendance doit exister : sinon l'ordonnancement est faux ;
  - la vague ne doit jamais décroître le long d'une dépendance : une tâche ne
    peut pas être planifiée dans une revue antérieure à celle de ce qu'elle attend ;
  - pas de cycle : aucune tâche ne peut démarrer ;
  - niveau strictement supérieur à celui de chaque dépendance (niveau = profondeur
    calculée, c'est elle qui fixe le chemin critique) ;
  - ports : formule back 3100+n, front dev 3200+n, front prod 3300+n, sans port
    réservé (3001, 3002, 3055 : checkouts principaux et e2e) ni interdit (3006, 3007),
    et sans collision entre deux numéros de tâche ;
  - base de test : zylo_t<NNN>[lettre]_test uniquement, jamais une base de dev ;
  - décision citée : le fichier docs/questions/<catégorie>/<sujet>.md doit exister ;
  - registre et issues régénérés : un fichier généré obsolète est une erreur (CI).
  - liens : les chemins `docs/...` et `scripts/...` cités dans docs/process/ existent.
"""

import glob
import json
import os
import re
import shlex
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DOCS = os.path.join(RACINE, "docs")
TACHES = os.path.join(DOCS, "plans", "taches")
REGISTRE = os.path.join(DOCS, "plans", "REGISTRE_TACHES.md")
ISSUES = os.path.join(DOCS, "plans", "ISSUES_A_CREER.md")

# Ports réservés : checkout principal backend (3002), frontend dev (3001), e2e prod (3055).
PORTS_RESERVES = {3001, 3002, 3055}
# Ports interdits par le plan (§2).
PORTS_INTERDITS = {3006, 3007}
# Formule de T-003 : base + n, avec n le numéro de la tâche.
BASE_PORT = {"back": 3100, "front dev": 3200, "front prod": 3300}
# Bases jamais utilisées par un test (règle T-004 / T-005).
BASES_INTERDITES = {"zylo", "zylo_office", "zylo_dev", "zylo_liquid", "zylo_recette", "zylo_office_test"}
RE_BASE = re.compile(r"^zylo_t(\d{3})([a-z]?)_test$")


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read()


def champ(texte, motif, defaut=None):
    m = re.search(motif, texte, re.M)
    return m.group(1).strip() if m else defaut


def charger_fiches(erreurs):
    """Lit les fiches et renvoie {id: dict}. Remplit `erreurs` pour les défauts de forme."""
    taches = {}
    for chemin in sorted(glob.glob(os.path.join(TACHES, "T-*.md"))):
        fichier = os.path.basename(chemin)
        texte = lire(chemin)
        entete = re.search(r"^# (T-\d{3}[a-z]?) : (.+)$", texte, re.M)
        if not entete:
            erreurs.append(f"{fichier}: en-tête '# T-XXX : titre' absent")
            continue
        tid, titre = entete.group(1), entete.group(2).strip()
        if not fichier.startswith(tid + "-"):
            erreurs.append(f"{fichier}: le nom de fichier ne commence pas par {tid}-")
        deps_brut = champ(texte, r"\*\*Dépendances\*\* : (.+)")
        if deps_brut is None:
            erreurs.append(f"{tid}: ligne Dépendances absente")
            deps_brut = ""
        vague_brut = champ(texte, r"\*\*Vague\*\* : (\d)")
        if vague_brut is None:
            erreurs.append(f"{tid}: Vague absente")
        ports = {k: int(v) for k, v in re.findall(r"(back|front dev|front prod) (\d{4})", champ(texte, r"\*\*Ports\*\* : (.+)$", ""))}
        base = champ(texte, r"\*\*Base de test\*\* : `([^`]+)`")
        decisions = re.findall(r"`([^`]+)`", champ(texte, r"\*\*Décisions requises\*\* : (.+)", "") or "")
        taches[tid] = {
            "fichier": fichier,
            "titre": titre,
            "statut": champ(texte, r"\*\*Statut\*\* : ([^·\n]+)", "?"),
            "prio": champ(texte, r"\*\*Priorité\*\* : (P\d)", "?"),
            "vague": int(vague_brut) if vague_brut else -1,
            "taille": champ(texte, r"\*\*Taille\*\* : ([SML])", "?"),
            "depot": champ(texte, r"\*\*Dépôt\(s\)\*\* : ([^·\n]+)", "?"),
            "domaine": champ(texte, r"\*\*Domaine\*\* : ([^·\n]+)", "?"),
            "type": champ(texte, r"\*\*Type\*\* : ([^·\n]+)", "?"),
            "deps": re.findall(r"T-\d{3}[a-z]?", deps_brut),
            "decisions": decisions,
            "base": base,
            "ports": ports,
        }
    return taches


def controler_fiche(tid, t, erreurs):
    n = int(tid[2:5])
    lettre = tid[5:]
    for k, v in t["ports"].items():
        attendu = BASE_PORT[k] + n
        if v != attendu:
            erreurs.append(f"{tid}: port {k}={v}, attendu {attendu} (formule T-003)")
    if t["base"] is not None:
        if t["base"] in BASES_INTERDITES:
            erreurs.append(f"{tid}: base interdite {t['base']}")
        m = RE_BASE.match(t["base"])
        if not m:
            erreurs.append(f"{tid}: base {t['base']} hors motif zylo_t<NNN>[lettre]_test")
        elif m.group(1) != f"{n:03d}" or m.group(2) != lettre:
            erreurs.append(f"{tid}: base {t['base']}, attendue zylo_t{n:03d}{lettre}_test")
    for d in t["decisions"]:
        if not os.path.exists(os.path.join(DOCS, "questions", d)):
            erreurs.append(f"{tid}: décision absente docs/questions/{d}")


def controler_graphe(taches, erreurs):
    """Dépendances, vagues, cycles et niveaux. Renvoie {id: niveau}."""
    for tid, t in taches.items():
        for d in t["deps"]:
            if d not in taches:
                erreurs.append(f"{tid}: dépendance inconnue {d}")
            elif taches[d]["vague"] > t["vague"]:
                erreurs.append(f"{tid} (vague {t['vague']}) dépend de {d} (vague {taches[d]['vague']}) : vague décroissante")
    niveau = {}

    def profondeur(tid, pile=()):
        if tid in niveau:
            return niveau[tid]
        if tid in pile:
            erreurs.append("CYCLE : " + " -> ".join(pile + (tid,)))
            return 0
        deps = [d for d in taches[tid]["deps"] if d in taches]
        niveau[tid] = 0 if not deps else 1 + max(profondeur(d, pile + (tid,)) for d in deps)
        return niveau[tid]

    for tid in taches:
        profondeur(tid)
    for tid, t in taches.items():
        for d in t["deps"]:
            if d in niveau and niveau[d] >= niveau[tid]:
                erreurs.append(f"{tid} niveau {niveau[tid]} <= niveau de {d} ({niveau[d]})")
    return niveau


def controler_ports(taches, erreurs):
    """Un port ne doit servir qu'à un numéro de tâche (les lettres d'une tâche partagent n)."""
    par_port = {}
    for tid, t in taches.items():
        for v in t["ports"].values():
            par_port.setdefault(v, set()).add(tid)
    for v, ids in sorted(par_port.items()):
        if len({int(i[2:5]) for i in ids}) > 1:
            erreurs.append(f"port {v} partagé entre numéros différents : {sorted(ids)}")
        if v in PORTS_RESERVES or v in PORTS_INTERDITS:
            erreurs.append(f"port {v} réservé ou interdit utilisé par {sorted(ids)}")


def controler_liens_process(erreurs):
    """Les chemins docs/... ou scripts/... cités dans docs/process/ doivent exister."""
    for chemin in sorted(glob.glob(os.path.join(DOCS, "process", "*.md"))):
        for cite in set(re.findall(r"`((?:docs|scripts)/[^`\s]+)`", lire(chemin))):
            if not os.path.exists(os.path.join(RACINE, cite.rstrip("/"))):
                erreurs.append(f"{os.path.relpath(chemin, RACINE)}: chemin cité absent : {cite}")


def rendre_registre(taches, niveau):
    def cle(tid):
        m = re.match(r"T-(\d{3})([a-z]?)", tid)
        return (int(m.group(1)), m.group(2))

    ordre = sorted(taches, key=cle)
    lignes = [
        "# Registre des tâches\n",
        "Statut initial : **Planifiée** (aucune tâche démarrée). **Généré à partir des fiches** `taches/T-XXX-*.md` (source de vérité) : ne pas éditer à la main. Colonne « Décision requise » : chemins relatifs à `docs/questions/`.\n",
        "**Vague** = jalon de revue humaine (0 à 3). **Niveau** = profondeur de dépendance, calculée : une tâche démarre quand toutes ses dépendances sont fusionnées. Invariants contrôlés : niveau strictement supérieur à celui de chaque dépendance ; vague supérieure ou égale ; aucun cycle.\n",
        "| ID | Titre | Prio | Vague | Niveau | Taille | Statut | Dépendances | Dépôt(s) | Décision requise | Fiche |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for tid in ordre:
        t = taches[tid]
        deps = ", ".join(t["deps"]) if t["deps"] else "—"
        dec = ", ".join(f"`{x}`" for x in t["decisions"]) if t["decisions"] else "—"
        lignes.append(
            f"| {tid} | {t['titre']} | {t['prio']} | {t['vague']} | {niveau[tid]} | {t['taille']} | "
            f"{t['statut']} | {deps} | {t['depot']} | {dec} | [fiche](taches/{t['fichier']}) |"
        )
    cnt = {w: sum(1 for t in taches.values() if t["vague"] == w) for w in range(4)}
    lignes += [
        "",
        f"Total : {len(taches)} tâches (vague 0 : {cnt[0]}, vague 1 : {cnt[1]}, vague 2 : {cnt[2]}, vague 3 : {cnt[3]}). Niveau maximal : {max(niveau.values())}.",
    ]
    return "\n".join(lignes) + "\n"


def labels_issue(t):
    depot = t["depot"].lower()
    repos = (["repo:backend"] if "backend" in depot else []) + (["repo:frontend"] if "frontend" in depot else [])
    return [f"priority:{t['prio']}", f"wave:{t['vague']}", f"area:{t['domaine']}", f"type:{t['type']}"] + repos


def rendre_issues(taches):
    def cle(tid):
        m = re.match(r"T-(\d{3})([a-z]?)", tid)
        return (int(m.group(1)), m.group(2))

    lignes = [
        "# Issues à créer (une par tâche, générées depuis les fiches)\n",
        "Labels : `priority:Px`, `wave:N`, `area:<domaine>`, `type:<type>`, `repo:<backend|frontend>`. Généré par `scripts/docs/check_plan.py --generer` : ne pas éditer à la main.\n",
        "| ID | Titre d'issue | Labels |",
        "|---|---|---|",
    ]
    for tid in sorted(taches, key=cle):
        t = taches[tid]
        lignes.append(f"| {tid} | [{tid}] {t['titre']} | {', '.join(labels_issue(t))} |")
    return "\n".join(lignes) + "\n"


def rendre_commandes_gh(taches):
    """Texte d'un script bash à relire avant exécution. Rien n'est exécuté ici."""
    couleurs = {"priority": "b60205", "wave": "0e8a16", "area": "1d76db", "type": "5319e7", "repo": "c5def5"}
    labels = sorted({l for t in taches.values() for l in labels_issue(t)})
    out = [
        "#!/usr/bin/env bash",
        "# Commandes gh générées par scripts/docs/check_plan.py --gh. NON EXÉCUTÉES.",
        "# Dépôt cible : à décider (visibilité du dépôt = question client, process/visibilite-depot-requirements.md).",
        "# Lancer d'abord les labels, puis les issues ; relire chaque ligne avant d'exécuter.",
        'ZYLO_GH_REPO="${ZYLO_GH_REPO:?définir OWNER/REPO}"',
        "",
        "# Labels (--force met à jour la couleur et la description si le label existe).",
    ]
    for l in labels:
        prefixe = l.split(":")[0]
        out.append(f"gh label create {shlex.quote(l)} --repo \"$ZYLO_GH_REPO\" --color {couleurs.get(prefixe, 'ededed')} --force")
    out += ["", "# Issues (une par tâche, depuis les fiches ; corps = chemin de la fiche)."]
    for tid in sorted(taches, key=lambda x: (int(x[2:5]), x[5:])):
        t = taches[tid]
        out.append(
            f"gh issue create --repo \"$ZYLO_GH_REPO\" --title {shlex.quote(f'[{tid}] {t['titre']}')} "
            f"--label {shlex.quote(','.join(labels_issue(t)))} "
            f"--body {shlex.quote('Fiche : docs/plans/taches/' + t['fichier'])}"
        )
    return "\n".join(out) + "\n"


def main(argv):
    erreurs = []
    taches = charger_fiches(erreurs)
    for tid, t in taches.items():
        controler_fiche(tid, t, erreurs)
    niveau = controler_graphe(taches, erreurs)
    controler_ports(taches, erreurs)
    controler_liens_process(erreurs)

    if "--gh" in argv:
        sys.stdout.write(rendre_commandes_gh(taches))
        return 0

    attendus = {REGISTRE: rendre_registre(taches, niveau), ISSUES: rendre_issues(taches)}
    if "--generer" in argv:
        for chemin, contenu in attendus.items():
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(contenu)
    else:
        for chemin, contenu in attendus.items():
            if not os.path.exists(chemin) or lire(chemin) != contenu:
                erreurs.append(f"{os.path.relpath(chemin, RACINE)} non régénéré (lancer avec --generer)")

    print(f"TACHES {len(taches)}")
    print(f"NIVEAU MAX {max(niveau.values())}")
    print(f"ERREURS {len(erreurs)}")
    for e in erreurs:
        print(f"  - {e}")
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
