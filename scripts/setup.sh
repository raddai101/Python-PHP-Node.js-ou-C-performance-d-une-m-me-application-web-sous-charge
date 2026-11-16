#!/usr/bin/env bash
# Installation unique : environnement Python, compilation C#, génération des données.
# Prérequis (Ubuntu 24.04 / WSL2) :
#   sudo apt install -y python3-venv nodejs php8.3-fpm php8.3-apcu nginx wrk dotnet-sdk-8.0 curl
#   (Node.js 22 LTS : voir https://nodejs.org ; si la version d'Ubuntu est plus ancienne)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Données =="
python3 data/generate_tasks.py

echo "== Python / FastAPI =="
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r python/requirements.txt

echo "== C# / ASP.NET Core (Release) =="
export DOTNET_CLI_TELEMETRY_OPTOUT=1
dotnet publish csharp -c Release -o csharp/publish --nologo -v quiet

echo "== Versions installées =="
bash scripts/env_info.sh >/dev/null && echo "écrit dans results/environment.txt"
echo "Installation terminée."
