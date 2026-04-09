#!/bin/bash
# PageFly Docker update script
# Usage: ./update.sh

set -e

cd "$(dirname "$0")"

echo "==> Pulling latest code..."
git pull

# Graceful stop: send SIGTERM and wait up to 30s for running tasks to finish
echo "==> Stopping container (graceful, 30s timeout)..."
docker compose stop -t 30

echo "==> Removing container..."
docker compose rm -f

echo "==> Rebuilding image..."
docker compose build

echo "==> Cleaning old images and build cache..."
docker image prune -f
docker builder prune -f

echo "==> Starting container..."
docker compose up -d

echo "==> Waiting for health check..."
sleep 8
docker compose ps

echo "==> Recent logs:"
docker compose logs --tail 10

echo "==> Done!"
