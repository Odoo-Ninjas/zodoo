#!/bin/bash

# Find all unhealthy containers starting with the project name
unhealthy_containers=$(docker ps \
  --filter "health=unhealthy" \
  --filter "name=${PROJECT_NAME}_" \
  --format "{{.Names}}" )

if [ -z "$unhealthy_containers" ]; then
  echo "✅ All containers starting with '${PROJECT_NAME}-' are healthy."
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