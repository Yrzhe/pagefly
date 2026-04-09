#!/bin/bash
# PageFly frontend deploy script
# Usage: ./deploy-frontend.sh

set -e

cd "$(dirname "$0")"

# Load Cloudflare credentials from .env if not set
if [ -z "$CLOUDFLARE_API_TOKEN" ]; then
  export CLOUDFLARE_API_TOKEN=$(grep CLOUDFLARE_API_TOKEN .env 2>/dev/null | cut -d= -f2)
fi
if [ -z "$CLOUDFLARE_ACCOUNT_ID" ]; then
  export CLOUDFLARE_ACCOUNT_ID=$(grep CLOUDFLARE_ACCOUNT_ID .env 2>/dev/null | cut -d= -f2)
fi

if [ -z "$CLOUDFLARE_API_TOKEN" ] || [ -z "$CLOUDFLARE_ACCOUNT_ID" ]; then
  echo "Error: CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must be set in .env or environment"
  exit 1
fi

echo "==> Pulling latest code..."
git pull

echo "==> Installing dependencies..."
cd frontend
npm install --silent

echo "==> Building frontend..."
VITE_API_URL=https://api.pagefly.ink npm run build

echo "==> Deploying to Cloudflare Pages..."
npx wrangler pages deploy dist --project-name pagefly --branch main --commit-dirty=true

echo "==> Done!"
