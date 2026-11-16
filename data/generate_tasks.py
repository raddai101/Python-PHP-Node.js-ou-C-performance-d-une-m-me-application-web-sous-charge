#!/usr/bin/env python3
"""Génère tasks.json (1 000 tâches, graine fixe seed=42) et le copie dans
les quatre dossiers de versions (python/, php/, javascript/, csharp/).

Le fichier est généré UNE fois puis copié : il est donc identique (octet pour
octet) dans les quatre versions.

Format : tableau JSON compact (sans espaces), UTF-8, clés dans l'ordre
id, title, done, priority.
"""
import hashlib
import json
import random
import shutil
from pathlib import Path

SEED = 42
N_TASKS = 1000

VERBS = ["Préparer", "Rédiger", "Vérifier", "Envoyer", "Planifier", "Corriger",
         "Tester", "Installer", "Configurer", "Réviser", "Archiver", "Imprimer",
         "Appeler", "Livrer", "Commander", "Organiser", "Valider", "Mettre à jour"]
NOUNS = ["rapport", "réunion", "facture", "serveur", "budget", "présentation",
         "contrat", "inventaire", "dossier", "formulaire", "projet", "planning",
         "capteur", "carte", "réseau", "base de données", "sauvegarde", "mémoire",
         "diagramme", "tableau", "script", "protocole", "cahier des charges"]
COMPLEMENTS = ["urgent", "hebdomadaire", "mensuel", "final", "provisoire",
               "pour demain", "avec l'équipe", "du groupe", "de l'atelier",
               "à la faculté", "du laboratoire", "avant vendredi", "en priorité",
               "du semestre", "numérique"]


def make_title(rng: random.Random) -> str:
    """Titre de 3 à 6 mots (les expressions composées comptent chacune pour
    leur nombre de mots réel)."""
    while True:
        words = [rng.choice(VERBS), rng.choice(NOUNS)]
        extra = rng.randint(1, 2)
        for _ in range(extra):
            words.append(rng.choice(COMPLEMENTS))
        title = " ".join(words)
        if 3 <= len(title.split()) <= 6:
            return title


def main() -> None:
    rng = random.Random(SEED)
    tasks = []
    for i in range(1, N_TASKS + 1):
        tasks.append({
            "id": i,
            "title": make_title(rng),
            "done": rng.random() < 0.4,
            "priority": rng.randint(1, 5),
        })

    here = Path(__file__).resolve().parent
    root = here.parent
    out = here / "tasks.json"
    payload = json.dumps(tasks, ensure_ascii=False, separators=(",", ":"))
    out.write_text(payload, encoding="utf-8")

    for sub in ("python", "php", "javascript", "csharp"):
        shutil.copyfile(out, root / sub / "tasks.json")

    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    print(f"{N_TASKS} tâches écrites dans {out} ({len(payload.encode('utf-8'))} octets)")
    print(f"SHA-256 : {digest}")
    print("Copié dans : python/, php/, javascript/, csharp/")


if __name__ == "__main__":
    main()
