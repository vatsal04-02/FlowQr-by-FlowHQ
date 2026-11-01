#!/usr/bin/env bash
# OPTIONAL helper for building behind a TLS-inspecting HTTP(S) proxy (corporate network / CI sandbox).
# Normal environments just run `docker compose build` (or `up --build`). This builds the SAME images with the same tags.
#   PROXY_CA=/path/to/proxy-ca.pem deploy/staging/build-behind-proxy.sh
set -euo pipefail
: "${PROXY_CA:?set PROXY_CA to the proxy CA bundle}"
TAG=${FLOWQR_TAG:-local}
ARGS=(--network host --secret "id=proxyca,src=$PROXY_CA"
      --build-arg "HTTP_PROXY=${HTTP_PROXY:-}" --build-arg "HTTPS_PROXY=${HTTPS_PROXY:-}" --build-arg "NO_PROXY=${NO_PROXY:-}")
DOCKER_BUILDKIT=1 docker build "${ARGS[@]}" -t "flowqr-backend:$TAG" backend
DOCKER_BUILDKIT=1 docker build "${ARGS[@]}" --build-arg BACKEND_URL=http://api:8000 -t "flowqr-frontend:$TAG" frontend
