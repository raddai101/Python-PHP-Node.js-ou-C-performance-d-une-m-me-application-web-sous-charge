# Mini-Task API — comparaison de performance (TP2 MRI)

> **Note de remise.** Les versions réellement installées et mesurées sont celles de `results/environment.txt` (Python 3.14.4, PHP 8.5.4, Nginx 1.28.3, Node.js 22.22.1, .NET 10) ; les versions citées plus bas (Python 3.12, PHP 8.3, .NET 8) sont celles visées au cadrage. Mesures finales : profil `reduced` avec essais de 8 s et 5 répétitions (voir `results/mesures_finales/run_config.json`).

Une même application HTTP (cinq endpoints) écrite en quatre technologies, avec
le dispositif complet de test de charge `wrk` qui produit les fichiers CSV de
données brutes.

| Technologie | Serveur | Port | Dossier |
|---|---|---|---|
| Python 3.12 + FastAPI 0.115 | Uvicorn 0.32 (1 processus, `uvicorn[standard]`) | 8080 | `python/` |
| PHP 8.3 | PHP-FPM (pool dynamique, 20 enfants max) + Nginx | 8081 | `php/` |
| JavaScript natif (Node.js 22 LTS) | module `http`, sans framework | 8082 | `javascript/` |
| C# / ASP.NET Core Minimal API (.NET 8 LTS) | Kestrel | 8083 | `csharp/` |

Tout écoute sur `127.0.0.1`, journaux d'accès désactivés partout.

## 1. Installation (Ubuntu 24.04 ou WSL2)

```bash
sudo apt install -y python3-venv nodejs php8.3-fpm php8.3-apcu nginx wrk dotnet-sdk-8.0 curl
# Node.js 22 LTS : si `node --version` affiche autre chose, installez-le depuis nodejs.org
bash scripts/setup.sh        # génère tasks.json, crée le venv Python, compile le C#
```

`php8.3-apcu` est **obligatoire** : c'est la mémoire partagée qui permet à PHP-FPM
de garder les données en mémoire entre requêtes (voir « Choix de conception »).
`wrk` ne fonctionne que sous Linux/macOS (sous Windows : WSL2).

## 2. Démarrer, vérifier

```bash
bash scripts/server.sh start all          # démarre les 4 serveurs
bash scripts/server.sh status all
python3 scripts/verify_equivalence.py     # DOIT afficher OK pour les 4 versions
python3 scripts/verify_equivalence.py --full   # ajoute /compute?n=35
bash scripts/server.sh stop all
```

La vérification compare, pour 53 cas, le code HTTP, le `Content-Type` et le
corps **octet pour octet** avec une réponse de référence calculée à part
(les 1 000 tâches, les 404, les 400, les POST valides/invalides, l'UTF-8…).
Elle s'exécute sur des serveurs fraîchement démarrés (les POST créent les
tâches 1001 et 1002).

## 3. Lancer les tests de charge

```bash
python3 scripts/run_benchmarks.py --profile smoke      # essai rapide (~5 min) pour valider la machine
python3 scripts/run_benchmarks.py --profile reduced    # recommandé : ~2 h
python3 scripts/run_benchmarks.py --profile full       # protocole nominal : ~42 h
python3 scripts/run_benchmarks.py --dry-run --profile full   # affiche le plan et la durée estimée
```

| Profil | Durée d'un essai | Échauffement | Répétitions | Niveaux | Essais | Durée estimée |
|---|---|---|---|---|---|---|
| `full` (protocole du dossier) | 30 s | 10 s (C# : 30 s) | 10 | 10/50/100/200 | 480 | ≈ 4 h 40 |
| `reduced` | 10 s | 5 s (C# : 15 s) | 10 | 10/50/100/200 | 480 | ≈ 1 h 55 |
| `smoke` | 3 s | 2 s | 2 | 10/50 | 24 | ≈ 5 min |

> **Correction du dossier de référence** : 4 technologies × 3 endpoints × 4 niveaux × 10 répétitions
> = **480 essais**, pas 4 800 ; à 30 s, cela donne ≈ 4 h de mesure (≈ 4 h 40 avec redémarrages et
> échauffements), pas 40 h. Le profil `full` est donc réalisable en une nuit. La durée réelle peut
> dépasser l'estimation sur les cas lourds (attentes de retour au repos, voir ci-dessous).

Le script :
1. lance d'abord la vérification d'équivalence et s'arrête si elle échoue ;
2. pour chaque (endpoint, niveau de charge), mesure les technologies dans un ordre
   aléatoire (graine 42) ; **un seul serveur tourne à la fois** ;
3. redémarre le serveur, l'échauffe, puis enchaîne les répétitions ; **avant chaque répétition il attend que le serveur soit
   revenu au repos** (CPU < 5 %), car les requêtes abandonnées par wrk à la fin d'un essai continuent de
   s'exécuter côté serveur ; si le serveur n'est pas au repos après 20 s (`--settle-max`), il est redémarré et
   la répétition est marquée `restarted_before = 1` ;
4. échantillonne CPU et mémoire du serveur chaque seconde pendant chaque répétition ;
5. écrit les CSV au fur et à mesure. **Reprenable** : relancez la même commande
   avec le même `--out` après une coupure, les répétitions faites sont sautées.

Options utiles : `--techs php csharp`, `--endpoints tasks compute35`, `--conns 10 100`,
`--reps 20`, `--duration 20`, `--threads 2`, `--timeout 30`, `--out results/mon_dossier`,
`--wrk-cpuset 0` (épingle wrk au cœur 0) ; variable `SERVER_CPUSET="1,2"` pour épingler
le serveur sur d'autres cœurs.

Puis :
```bash
python3 scripts/aggregate.py results/run_XXXXXXXX_XXXX     # produit summary.csv + résumé à l'écran
```

## 4. Fichiers produits (dossier `results/run_…/`)

| Fichier | Contenu |
|---|---|
| `raw_runs.csv` | **une ligne par répétition** (données brutes à joindre au rendu) |
| `resource_samples.csv` | un échantillon CPU / mémoire par seconde et par répétition |
| `summary.csv` | moyenne, écart-type et IC 95 % par (endpoint, niveau, technologie) |
| `run_config.json` | paramètres exacts du test |
| `environment.txt` | machine, système, versions des outils, empreinte de `tasks.json` |

### Colonnes de `raw_runs.csv`

| Colonne | Définition |
|---|---|
| `throughput_rps` | **Débit** : requêtes réussies (2xx) par seconde = (requêtes − non-2xx) / durée |
| `raw_rps` | requêtes terminées par seconde, erreurs HTTP comprises |
| `lat_mean_ms`, `p50_ms`, `p90_ms`, `p95_ms`, `p99_ms`, `lat_min_ms`, `lat_max_ms`, `lat_stdev_ms` | **Latence** par requête (envoi → réponse complète), en ms |
| `err_status`, `err_timeout`, `err_connect`, `err_read`, `err_write` | compteurs d'erreurs de wrk |
| `error_rate_pct` | **Taux d'erreur** = (non-2xx + timeouts + erreurs de socket) / (requêtes + timeouts + erreurs de socket) × 100 |
| `cpu_pct_mean`, `cpu_pct_max` | **CPU** du serveur en % d'**un** cœur (200 % = 2 cœurs saturés), toute l'arborescence de processus (PHP : Nginx + PHP-FPM + enfants) |
| `rss_mb_mean`, `rss_mb_max` | **Mémoire résidente** (RSS) cumulée de l'arborescence, en Mo |
| `pss_mb_mean`, `pss_mb_max` | Mémoire **PSS** (pages partagées réparties) : plus juste pour PHP-FPM, dont les 20 enfants partagent OPcache/APCu, ce que la somme des RSS compte plusieurs fois |
| `transfer_mb_s` | débit de données (Mo/s) |
| `settle_wait_s`, `restarted_before` | temps d'attente du retour au repos avant la répétition ; 1 si le serveur a dû être redémarré avant cette répétition (cas lourds) |

## 5. Contrat de réponse (identique dans les 4 versions)

`Content-Type: application/json; charset=utf-8`, JSON compact, UTF-8 non échappé.
Une tâche : `{"id":1,"title":"…","done":false,"priority":3}` (clés dans cet ordre).

| Requête | Succès | Erreurs |
|---|---|---|
| `GET /health` | `200 {"status":"ok"}` | |
| `GET /tasks` | `200` tableau des tâches | |
| `GET /tasks/{id}` | `200` tâche | `404 {"error":"not found"}` (inconnu ou non numérique) |
| `POST /tasks` | `201` tâche créée (id suivant) | `400 {"error":"invalid payload"}` |
| `GET /compute?n=N` | `200 {"n":N,"result":fib(N)}` | `400 {"error":"invalid n"}` |
| toute autre route/méthode | | `404 {"error":"not found"}` |

Précisions ajoutées au cahier des charges (le dossier de référence ne les fixait pas) :
- `POST /tasks` : `title` = chaîne non vide, `priority` = entier de 1 à 5, `done` = booléen optionnel (défaut `false`) ; champs en trop ignorés ; JSON invalide, non-objet, UTF-8 invalide → 400.
- `/compute` : `n` entier de 0 à 40 (borne ajoutée pour éviter qu'une requête mal formée ne bloque un serveur) ; sinon 400.
- Cas non couvert : `priority: 1.0` est accepté par JavaScript (qui ne distingue pas `1` de `1.0`) et refusé par les trois autres. Non testé, hors de la charge mesurée.

## 6. Choix de conception à connaître (à citer dans l'article)

1. **PHP et la mémoire partagée.** PHP-FPM est « sans partage » : chaque requête repart de zéro, il n'y a pas de variable globale persistante. Relire et décoder `tasks.json` à chaque requête désavantagerait PHP pour une raison étrangère à la performance du langage. La version PHP garde donc les tâches dans **APCu** (mémoire partagée entre processus) et active **OPcache** ; c'est la pratique de production courante. Coût : un `apcu_fetch` (désérialisation des 1 000 tâches) à chaque `GET /tasks`.
2. **Python : `async def` partout, sauf `/compute` en `def`.** C'est la recommandation de FastAPI pour le code bloquant : `/compute` s'exécute dans le pool de threads au lieu de bloquer la boucle d'événements. Pas de `response_model` (pas de validation Pydantic) pour rester « léger ». Sérialisation : `json` de la bibliothèque standard (comportement par défaut de FastAPI).
3. **Python et JavaScript : un seul processus.** Le dossier de référence ne fixe pas le nombre de workers. Uvicorn et Node tournent en un processus (valeur par défaut) ; PHP-FPM utilise jusqu'à 20 processus et Kestrel tous les cœurs. L'écart sur `/compute` reflète donc aussi cette différence d'architecture, à discuter dans les limites. (Variante possible : `uvicorn --workers N`, `node:cluster`.)
4. **Uvicorn** est installé avec `[standard]` (uvloop + httptools), l'installation recommandée en production.
5. **Nginx** : tampons FastCGI de 16 × 32 Ko pour que la réponse de `/tasks` (~78 Ko) ne passe pas par un fichier temporaire ; `Content-Length` fourni par PHP.
6. **C#** : compilé en `Release` ; JSON via `System.Text.Json` (réflexion, comportement par défaut) ; données dans un instantané immuable remplacé à chaque POST (lecture sans verrou).
7. **Les POST ne sont pas mesurés** (endpoints testés : `/tasks`, `/compute?n=30`, `/compute?n=35`) ; leur correction est vérifiée par le script d'équivalence.

## 7. Points d'attention méthodologiques

- **Durée.** Voir le tableau ci-dessus ; `--dry-run` donne l'estimation exacte. Si vous réduisez la durée des essais (profil `reduced`), conservez les 10 répétitions et **écrivez l'écart au protocole dans le rapport**.
- **Ordre de grandeur de `fib(30)`** (mesuré sur la machine de développement de ce dispositif, 2 cœurs) : ≈ 200 ms en Python, ≈ 25 ms en PHP, ≈ 10 ms en Node, ≈ 4 ms en C#. Le dossier de référence annonce « inférieur à 100 ms partout » : ce n'est pas vrai pour Python. Vérifiez sur votre machine avant de reprendre cette phrase dans le rapport.
- **`/compute?n=35` à forte charge.** `fib(35)` coûte ≈ 1–3 s en Python et ≈ 0,5–1 s en PHP : avec 100–200 connexions simultanées, ces versions peuvent ne terminer presque aucune requête pendant l'essai (latences > durée de l'essai). `wrk` ne compte alors que les requêtes terminées : un débit proche de 0 et une latence très élevée sont **des résultats** à interpréter, pas des erreurs de mesure. Le timeout wrk est réglé à 30 s (défaut de wrk : 2 s, qui transformerait tout en erreurs).
- **Une seule machine pour wrk et le serveur** : wrk consomme du CPU, ce qui plafonne le débit mesuré des serveurs rapides. Gardez wrk à 2 threads, fermez les autres applications, branchez le secteur, et notez le nombre de cœurs. Option : épingler wrk et le serveur sur des cœurs distincts (`--wrk-cpuset`, `SERVER_CPUSET`).
- **Omission coordonnée** : `wrk` (contrairement à `wrk2`) souffre de l'« omission coordonnée » : sous saturation, les latences extrêmes sont sous-estimées. À mentionner dans les limites.
- **Même machine, mêmes conditions** pour les 4 technologies, sur tout le test (même session si possible, même alimentation, pas d'autre charge).
- Après modification d'une version, **relancez toute sa série de mesures** (règle d'équipe) et la vérification d'équivalence.
- Versions réellement installées : voir `results/environment.txt` (Ubuntu 24.04 fournit Nginx 1.24 et PHP 8.3 ; le dossier visait Nginx 1.26 — à indiquer tel quel dans le rapport).

## 8. Arborescence

```
mini-task-api/
├── README.md
├── data/generate_tasks.py      génère tasks.json (seed=42) et le copie dans les 4 dossiers
├── python/   main.py  requirements.txt  tasks.json
├── php/      public/index.php  conf/nginx.conf.tpl  conf/php-fpm.conf.tpl  tasks.json
├── javascript/ server.js  tasks.json
├── csharp/   Program.cs  MiniTaskApi.csproj  tasks.json
├── scripts/
│   ├── setup.sh                installation unique
│   ├── server.sh               start | stop | status | pids
│   ├── verify_equivalence.py   vérification d'équivalence (53 cas)
│   ├── run_benchmarks.py       orchestrateur wrk + CPU/RSS → CSV
│   ├── report.lua              sortie wrk avec p95
│   ├── aggregate.py            raw_runs.csv → summary.csv
│   └── env_info.sh             machine et versions
└── results/                    données produites (à joindre au rendu)
```
# Python-PHP-Node.js-ou-C-performance-d-une-m-me-application-web-sous-charge
