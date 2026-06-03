#!/bin/bash

# In DEVMODE, skip restart logic unless explicitly forced via FORCE_RESTART_UNHEALTHY_CONTAINERS=1
# (robot tests set FORCE_RESTART_UNHEALTHY_CONTAINERS=1 to ensure restarts work even in dev)
if [ "$DEVMODE" = "1" ] && [ "$FORCE_RESTART_UNHEALTHY_CONTAINERS" != "1" ]; then
  echo "⚙️  DEVMODE=1 and FORCE_RESTART_UNHEALTHY_CONTAINERS!=1 → Skipping healthcheck and restart logic."
  exit 0
fi

# Filtering on health=unhealthy alone misses three real failure modes:
#   1. crash-loop: supervisor exits before StartPeriod, Docker keeps
#      reviving the container, the healthcheck never runs, status never
#      becomes 'unhealthy'. The 2026-05-23 MANIFEST=0B incident sat here
#      for days.
#   2. stuck-in-starting: container is up but health stays 'starting'
#      (e.g. a hanging healthcheck command).
#   3. crashed-and-exited: without a restart policy (RESTART_CONTAINERS=0
#      strips it), a crashed container sits in 'exited' forever.
# Thresholds are deliberately generous so normal boot / brief restarts
# don't trip them.
#
# NOTE on coverage: only container-level failures are visible here. A role
# crash-looping INSIDE the odoo container (supervisor.py respawns it with
# backoff while PID 1 stays alive — RestartCount stays 0, no healthcheck)
# cannot be detected by this script.
RESTARTING_STUCK_SECS=${RESTARTING_STUCK_SECS:-300}
STARTING_STUCK_SECS=${STARTING_STUCK_SECS:-300}
EXITED_STUCK_SECS=${EXITED_STUCK_SECS:-300}

# Crash-loops cannot be detected from a single snapshot: docker's restart
# backoff is capped at 60s, so while a container crash-loops,
# 'now - FinishedAt' never exceeds ~60s and a timestamp threshold would
# never fire. Instead we track .RestartCount across cron ticks on the
# writable cronjobs volume (${HOST_RUN_DIR}/cronjobs -> /opt/cronjobs):
# the count only grows while the restart policy keeps reviving the
# container. An episode whose count keeps growing for longer than
# RESTARTING_STUCK_SECS is a genuine crash-loop.
# State file per container: "<episode_start_epoch> <last_restart_count>"
STATE_DIR=${RESTART_UNHEALTHY_STATE_DIR:-/opt/cronjobs/restart_unhealthy_state}
if ! mkdir -p "$STATE_DIR" 2>/dev/null || [ ! -w "$STATE_DIR" ]; then
  echo "⚠️  State dir '$STATE_DIR' is not writable (cronjobs volume missing?) — falling back to /tmp; crash-loop episodes won't survive container restarts."
  STATE_DIR=/tmp/restart_unhealthy_state
  mkdir -p "$STATE_DIR"
fi

# Only one instance at a time: a tick that restarts several containers can
# exceed the 1-minute cron interval (docker restart blocks up to 10s per
# container) and run.py spawns job threads without a lock. Overlapping
# instances would double-restart containers and race on the episode state
# files. (.lock starts with a dot so the stale-state cleanup glob below
# never touches it.)
exec 9>"$STATE_DIR/.lock"
if ! flock -n 9; then
  echo "⏭️  Previous run still active — skipping this tick."
  exit 0
fi

now_epoch=$(date -u +%s)
to_restart=()
declare -A seen_containers

while IFS= read -r container; do
  [ -z "$container" ] && continue
  seen_containers["$container"]=1

  read -r status health restart_count started_at exit_code oom_killed finished_at <<<"$(
    timeout 60 docker inspect "$container" --format \
      '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}} {{.State.StartedAt}} {{.State.ExitCode}} {{.State.OOMKilled}} {{.State.FinishedAt}}' \
      2>/dev/null
  )"
  if [ -z "$status" ]; then
    echo "⚠️  Could not inspect container '$container' — skipping."
    continue
  fi

  state_file="$STATE_DIR/$container"
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
    exited)
      # Distinguish crashes from intentional stops by exit code:
      #   0 / 130 / 143 = clean exit / SIGINT / SIGTERM ('odoo kill',
      #     'docker stop' and restores all stop via SIGTERM) → hands off.
      #   137 = SIGKILL: only a crash if the kernel OOM-killed it
      #     (manual 'docker kill' also yields 137, but without OOMKilled).
      # CONTRACT: this relies on every service's PID 1 exiting 0 or 143 on
      # SIGTERM (supervisor.py exits 0; official postgres/nginx/redis
      # images exit 0/143). A service whose SIGTERM handler exits with any
      # other code would be wrongly revived here — keep shutdown paths
      # clean-exiting.
      crashed=0
      case "$exit_code" in
        0 | 130 | 143) ;;
        137) [ "$oom_killed" = "true" ] && crashed=1 ;;
        *) crashed=1 ;;
      esac
      if [ "$crashed" = "1" ]; then
        finished_epoch=$(date -u -d "$finished_at" +%s 2>/dev/null || echo 0)
        if [ "$finished_epoch" -gt 0 ] && \
           [ $((now_epoch - finished_epoch)) -gt "$EXITED_STUCK_SECS" ]; then
          oom_note=""
          [ "$oom_killed" = "true" ] && oom_note=", OOM-killed"
          reason="crashed (exit ${exit_code}${oom_note}, down $((now_epoch - finished_epoch))s)"
        fi
      fi
      ;;
  esac

  # Crash-loop episode tracking. A crash-looping container alternates
  # between 'running' (brief) and 'restarting' (backoff), so check both
  # states instead of keying on the momentary status.
  if [ -z "$reason" ] && { [ "$status" = "running" ] || [ "$status" = "restarting" ]; }; then
    if [ "${restart_count:-0}" -gt 0 ]; then
      if [ -f "$state_file" ]; then
        read -r first_epoch last_count <"$state_file"
        if [[ ! "$first_epoch" =~ ^[0-9]+$ ]] || [[ ! "$last_count" =~ ^[0-9]+$ ]]; then
          # Corrupt state file (e.g. partial write) → restart the episode.
          echo "$now_epoch $restart_count" >"$state_file"
        elif [ "$restart_count" -gt "$last_count" ]; then
          # Count grew since the last tick → still crashing.
          if [ $((now_epoch - first_epoch)) -gt "$RESTARTING_STUCK_SECS" ]; then
            reason="crash-loop (${restart_count} restarts over $((now_epoch - first_epoch))s)"
          else
            echo "$first_epoch $restart_count" >"$state_file"
          fi
        else
          # Count stable for a full tick → container recovered; end episode.
          rm -f "$state_file"
        fi
      else
        # First sighting of a non-zero count → start an episode. It only
        # escalates if the count is still growing on later ticks.
        echo "$now_epoch $restart_count" >"$state_file"
      fi
    else
      rm -f "$state_file"
    fi
  fi

  if [ -n "$reason" ]; then
    to_restart+=("${container}|${reason}")
  fi
# The name filter is a regex SUBSTRING match — anchor it so project 'foo'
# does not also manage the containers of project 'foo_staging' (container
# names carry a leading '/', same pattern as zodoo tools.docker_list_containers).
done < <(timeout 60 docker ps -a --filter "name=^/${PROJECT_NAME}_" --format '{{.Names}}')

# Drop episode state of containers that no longer exist.
for state_file in "$STATE_DIR"/*; do
  [ -e "$state_file" ] || continue
  [ -n "${seen_containers[$(basename "$state_file")]:-}" ] || rm -f "$state_file"
done

if [ ${#to_restart[@]} -eq 0 ]; then
  echo "✅ All containers starting with '${PROJECT_NAME}_' look fine."
  exit 0
fi

echo "🚨 Containers needing restart for project '${PROJECT_NAME}':"
for entry in "${to_restart[@]}"; do
  echo "  ${entry%%|*} — ${entry#*|}"
done
echo

failed=0
for entry in "${to_restart[@]}"; do
  container="${entry%%|*}"
  reason="${entry#*|}"
  echo "🔄 Restarting container: $container ($reason)"
  if ! timeout 180 docker restart "$container"; then
    echo "❌ Restart of '$container' FAILED."
    failed=$((failed + 1))
  fi
  # Manual restart resets docker's RestartCount — start a fresh episode so
  # a persistent crash escalates again only after RESTARTING_STUCK_SECS
  # (natural rate limit instead of restarting every tick). Cleared even on
  # failure for the same reason: keeping the state would re-fire every tick.
  rm -f "$STATE_DIR/$container"
done

echo
if [ "$failed" -gt 0 ]; then
  echo "⚠️  Restart process completed with $failed failure(s)."
else
  echo "✅ Restart process completed."
fi
