#!/usr/bin/env bash
# scripts/build_prod_image.sh — build and verify production image
# Usage: ./scripts/build_prod_image.sh [tag]
set -euo pipefail

TAG="${1:-emerald:dev}"
echo "Building production image: $TAG"

docker build --target production -t "$TAG" .

# Verify image size
SIZE=$(docker image inspect "$TAG" --format '{{.Size}}')
SIZE_MB=$((SIZE / 1024 / 1024))
echo "Image size: ${SIZE_MB}MB"

if [ "$SIZE_MB" -gt 1200 ]; then
    echo "ERROR: Image size ${SIZE_MB}MB exceeds 1.2GB target" >&2
    exit 1
fi

# Smoke test: start container, check imports, stop
echo "Running health check smoke test..."
CONTAINER_ID=$(docker run -d --rm "$TAG" sleep 60)
sleep 3

if docker exec "$CONTAINER_ID" python -c "from emerald.api.app import app; print('import OK')"; then
    echo "✓ Container app importable"
else
    docker kill "$CONTAINER_ID" >/dev/null
    echo "ERROR: Container app import failed" >&2
    exit 1
fi

docker kill "$CONTAINER_ID" >/dev/null
echo "✓ Production image verified: $TAG (${SIZE_MB}MB)"
