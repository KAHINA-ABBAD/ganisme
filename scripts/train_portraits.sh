#!/usr/bin/env bash
# Entraine le DCGAN sur les portraits (pipeline du cours), l'evalue puis exporte le generateur.
# Relance automatiquement l'entrainement s'il plante (5 essais max) : il reprend depuis last.pt.
#
# Usage, depuis la racine du projet :  bash scripts/train_portraits.sh 64 180
set -u
SIZE=${1:-64}
EPOCHS=${2:-180}
RUN=runs/portraits_${SIZE}
PY=.venv/Scripts/python.exe
export PYTHONPATH=src
mkdir -p "$RUN"

for attempt in 1 2 3 4 5; do
  if "$PY" -u -m ganisme.dcgan --images data/processed/portraits_128 --image_size "$SIZE" \
      --run_dir "$RUN" --epochs "$EPOCHS" --num_workers 4 >> "$RUN/train.log" 2>&1; then
    break
  fi
  echo "!! arret inattendu (essai $attempt), relance dans 30 s" >> "$RUN/train.log"
  sleep 30
done

"$PY" -u -m ganisme.evaluate --run_dir "$RUN" --data "data/processed/portraits_${SIZE}.npz" \
  --out "reports/portraits_${SIZE}" >> "$RUN/train.log" 2>&1
"$PY" -u -m ganisme.generate --run_dir "$RUN" --metrics "reports/portraits_${SIZE}/metrics.json" \
  --out "models/generator_portraits_${SIZE}.pt" >> "$RUN/train.log" 2>&1
echo "== termine ==" >> "$RUN/train.log"
