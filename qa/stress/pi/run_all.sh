#!/usr/bin/env bash
# run_all.sh - orchestrator, order from spec section G:
#   d5 (explicit only) -> hw -> net -> [C/C2 hook] -> [E hook] -> dur
#   run_all.sh [--dry-run] [--destructive] [--i-know-this-kills] [--group g1,g2]
# groups: d5 hw hw-risky net net-disruptive dur dur-destructive
# default groups (no flags)     : hw net dur          (non-destructive)
# --destructive adds            : net-disruptive dur-destructive
# --i-know-this-kills + --destructive adds : hw-risky (H5 H10 H13)
# d5 never runs implicitly: it power-cycles the box (needs POWER_CYCLE_CMD, see durability.sh) and is multi-boot.
# Hooks (optional shell commands, e.g. the py/sec suites owned elsewhere), run in spec order:
#   HOOK_RACE_CMD  (C and C2, ideally while you shape with netem)     HOOK_SEC_CMD  (E)
set -euo pipefail
. "$(dirname "$0")/lib.sh"

DESTRUCTIVE=0 KILLS=0 GROUPS_ARG="" FWD=()
while (( $# )); do
  case $1 in
    --dry-run) FWD+=(--dry-run); shift ;;
    --destructive) DESTRUCTIVE=1; shift ;;
    --i-know-this-kills) KILLS=1; shift ;;
    --group) GROUPS_ARG=${2:?--group needs a list}; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [ -z "$GROUPS_ARG" ]; then
  GROUPS_ARG="hw,net,dur"
  [ "$DESTRUCTIVE" = 0 ] || GROUPS_ARG="$GROUPS_ARG,net-disruptive,dur-destructive"
  { [ "$DESTRUCTIVE" = 1 ] && [ "$KILLS" = 1 ]; } && GROUPS_ARG="$GROUPS_ARG,hw-risky"
fi
want() { case ",$GROUPS_ARG," in *",$1,"*) return 0 ;; esac; return 1; }
for g in d5 hw-risky net-disruptive dur-destructive; do
  want "$g" || continue
  case $g in
    hw-risky) [ "$DESTRUCTIVE" = 1 ] && [ "$KILLS" = 1 ] || die "group hw-risky needs --destructive --i-know-this-kills" ;;
    *) [ "$DESTRUCTIVE" = 1 ] || die "group $g needs --destructive" ;;
  esac
done

export RESULTS_DIR COLLECT_EXTERNAL=1
mkdir -p "$RESULTS_DIR"
echo "results: $RESULTS_DIR"

RC=0
step() { echo; echo "######## $*"; mark "run_all: $*"; }
sh_() { bash "$LIB_DIR/$1" "${@:2}" || RC=1; }   # a failing group never stops the later ones
hook() { # NAME CMD
  [ -n "${2:-}" ] || { echo "(no $1 set, skipping)"; return 0; }
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: $2"; else bash -c "$2" || RC=1; fi
}

trap 'collect_stop' EXIT
if [ "$DRY_RUN" != 1 ]; then bash "$LIB_DIR/collect.sh" >/dev/null 2>&1 & COLLECT_PID=$!; fi

step "internet speed + latency baseline (Cloudflare, no setup)"; TAG=base sh_ speedtest_baseline.sh "${FWD[@]}"
want d5 && { step "D5 power loss (one cycle; continue with verify_after_boot.sh --continue)"; sh_ durability.sh "${FWD[@]}" --destructive D5; }
want hw && { step "B hardware (safe set)"; sh_ hw_stress.sh "${FWD[@]}"; }
want hw-risky && { step "B hardware (H5 H10 H13)"; sh_ hw_stress.sh "${FWD[@]}" --i-know-this-kills H5 H10 H13; }
want net && { step "A network (N1-N7)"; sh_ net_scenarios.sh "${FWD[@]}"; }
# for a speed/RTT reading under shaping, run by hand while netem is active: TAG=shaped ./speedtest_baseline.sh
want net-disruptive && { step "A network (N8-N11)"; sh_ net_scenarios.sh "${FWD[@]}" --disruptive N8 N9 N10 N11; }
step "C / C2 race suite (hook)"; hook HOOK_RACE_CMD "${HOOK_RACE_CMD:-}"
step "E security (hook)"; hook HOOK_SEC_CMD "${HOOK_SEC_CMD:-}"
want dur && { step "D durability (config checks)"; sh_ durability.sh "${FWD[@]}" D9 D10; }
want dur-destructive && { step "D durability (destructive)"; sh_ durability.sh "${FWD[@]}" --destructive D1 D2 D3 D6 D12; }

echo
summary || RC=1
exit "$RC"
