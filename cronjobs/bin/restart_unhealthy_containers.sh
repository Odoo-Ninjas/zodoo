#!/bin/bash

# In DEVMODE, skip restart logic unless explicitly forced via FORCE_RESTART_UNHEALTHY_CONTAINERS=1
# (robot tests set FORCE_RESTART_UNHEALTHY_CONTAINERS=1 to ensure restarts work even in dev)
if [ "$DEVMODE" = "1" ] && [ "$FORCE_RESTART_UNHEALTHY_CONTAINERS" != "1" ]; then
  echo "⚙️  DEVMODE=1 and FORCE_RESTART_UNHEALTHY_CONTAINERS!=1 → Skipping healthcheck and restart logic."
  exit 0
fi

# Find all unhealthy containers starting with the project name
unhealthy_containers=$(docker ps \
  --filter "health=unhealthy" \
  --filter "name=${PROJECT_NAME}_" \
  --format "{{.Names}}" )

if [ -z "$unhealthy_containers" ]; then
  echo "✅ All containers starting with '${PROJECT_NAME}_' are healthy."
  exit 0
fi

echo "🚨 Unhealthy containers for project '${PROJECT_NAME}':"
echo "$unhealthy_containers"
echo

# Restart each unhealthy container
for container in $unhealthy_containers; do
  echo "🔄 Restarting container: $container"
  docker restart "$container"
done

echo
echo "✅ Restart process completed."
