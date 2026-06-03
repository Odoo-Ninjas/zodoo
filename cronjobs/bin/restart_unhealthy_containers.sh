#!/bin/bash

# In DEVMODE, skip restart logic unless explicitly forced via FORCE_RESTART_UNHEALTHY_CONTAINERS=1
# (robot tests set FORCE_RESTART_UNHEALTHY_CONTAINERS=1 to ensure restarts work even in dev)
if [ "$DEVMODE" = "1" ] && [ "$FORCE_RESTART_UNHEALTHY_CONTAINERS" != "1" ]; then
  echo "⚙️  DEVMODE=1 and FORCE_RESTART_UNHEALTHY_CONTAINERS!=1 → Skipping healthcheck and restart logic."
  exit 0
fi

# Filtering on health=unhealthy alone misses two real failure modes:
#   1. crash-loop: supervisor exits before StartPeriod, Docker keeps the
#      container in 'restarting' state, healthcheck never runs, status
#      never becomes 'unhealthy'. The 2026-05-23 MANIFEST=0B incident sat
#      here for days.
#   2. stuck-in-starting: container is up but health stays 'starting'
#      (curl keeps returning != 0 inside the StartPeriod re-eval window).
# Thresholds are deliberately generous so normal boot / brief restarts
# don't trip them.
RESTARTING_STUCK_SECS=${RESTARTING_STUCK_SECS:-300}
STARTING_STUCK_SECS=${STARTING_STUCK_SECS:-300}

now_epoch=$(date -u +%s)
to_restart=()

while IFS= read -r container; do
  [ -z "$container" ] && continue

  read -r status health started_at finished_at <<<"$(
    docker inspect "$container" --format \
      '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.State.StartedAt}} {{.State.FinishedAt}}' \
      2>/dev/null
  )"
  [ -z "$status" ] && continue

  reason=""
  case "$status" in
    running)
      if [ "$health" = "unhealthy" ]; then
        reason="unhealthy"
      elif [ "$health" = "starting" ]; then
        started_epoch=$(date -u -d "$started_at" +%s 2>/dev/null || echo 0)
        if [ "$started_epoch" -gt 0 ] && \
           [ $((now_epoch - started_epoch)) -gt "$STARTING_STUCK_SECS" ]; then
          reason="stuck-in-starting ($((now_epoch - started_epoch))s)"
        fi
      fi
      ;;
    restarting)
      finished_epoch=$(date -u -d "$finished_at" +%s 2>/dev/null || echo 0)
      if [ "$finished_epoch" -gt 0 ] && \
         [ $((now_epoch - finished_epoch)) -gt "$RESTARTING_STUCK_SECS" ]; then
        reason="crash-loop ($((now_epoch - finished_epoch))s in restarting)"
      fi
      ;;
  esac

  if [ -n "$reason" ]; then
    to_restart+=("${container}|${reason}")
  fi
done < <(docker ps -a --filter "name=${PROJECT_NAME}_" --format '{{.Names}}')

if [ ${#to_restart[@]} -eq 0 ]; then
  echo "✅ All containers starting with '${PROJECT_NAME}_' look fine."
  exit 0
fi

echo "🚨 Containers needing restart for project '${PROJECT_NAME}':"
for entry in "${to_restart[@]}"; do
  echo "  ${entry%%|*} — ${entry#*|}"
done
echo

for entry in "${to_restart[@]}"; do
  container="${entry%%|*}"
  reason="${entry#*|}"
  echo "🔄 Restarting container: $container ($reason)"
  docker restart "$container"
done

echo
echo "✅ Restart process completed."
