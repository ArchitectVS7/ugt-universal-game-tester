#!/usr/bin/env bash
# Run all 5 strategy profiles through UGT evaluate (20 episodes each = 100 games total).
# Run this AFTER training all profiles with the train:* npm scripts.
#
# Usage:
#   cd integrations/spacerquest
#   npm run train:trader && npm run train:explorer && ...  (or use a parallel trainer)
#   bash run-eval.sh

set -e

CONFIG="ugt.config.yaml"
EPISODES=20

PROFILES=("trader" "explorer" "warrior" "balanced" "speedrun")

echo "SpacerQuest — 100-Game Balance Evaluation"
echo "=========================================="
echo "5 profiles × ${EPISODES} episodes = 100 total games"
echo ""

for PROFILE in "${PROFILES[@]}"; do
  MODEL="models/ppo_${PROFILE}_final.zip"

  if [ ! -f "$MODEL" ]; then
    echo "[SKIP] $PROFILE — model not found at $MODEL (run npm run train:${PROFILE} first)"
    continue
  fi

  echo "--- $PROFILE ---"
  ugt evaluate \
    --config "$CONFIG" \
    --profile "$PROFILE" \
    --model "$MODEL" \
    --episodes "$EPISODES"

  echo ""
done

echo "=========================================="
echo "All evaluations complete."
echo "Results in integrations/spacerquest/results/"
echo ""
echo "Quick summary:"
for PROFILE in "${PROFILES[@]}"; do
  RESULT="results/eval_${PROFILE}.json"
  if [ -f "$RESULT" ]; then
    # Extract win rate from JSON if python is available
    python3 -c "
import json, sys
with open('$RESULT') as f:
    d = json.load(f)
wr = d.get('win_rate', 0)
ep = d.get('episodes', 0)
print(f'  $PROFILE: {wr:.1%} win rate over {ep} episodes')
" 2>/dev/null || echo "  $PROFILE: (install python3 to parse results)"
  fi
done
