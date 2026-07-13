#!/usr/bin/env bash
# Gate-1+ full run: train + eval all 5 profiles SEQUENTIALLY on the widened 10-action subset.
# Sequential is mandatory — parallel bridges deadlock Postgres on the shared UGT_TEST_PILOT row.
set -u
export UGT_WIN_SCORE=100
CONFIG="ugt.config.yaml"
PROFILES=(trader explorer warrior balanced speedrun)
STATUS="all5_run.status"
echo "[all5] START $(date)" > "$STATUS"
for P in "${PROFILES[@]}"; do
  echo "[all5] TRAIN $P start $(date)" >> "$STATUS"
  ugt train --config "$CONFIG" --profile "$P" > "all5_train_${P}.log" 2>&1
  echo "[all5] TRAIN $P exit=$? $(date)" >> "$STATUS"
  echo "[all5] EVAL  $P start $(date)" >> "$STATUS"
  ugt evaluate --model "./models/ppo_${P}_final.zip" --config "$CONFIG" --profile "$P" --episodes 50 > "all5_eval_${P}.log" 2>&1
  echo "[all5] EVAL  $P exit=$? $(date)" >> "$STATUS"
done
echo "[all5] ALL DONE $(date)" >> "$STATUS"
