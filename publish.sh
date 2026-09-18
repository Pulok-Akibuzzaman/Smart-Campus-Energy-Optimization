#!/usr/bin/env bash
# Publish the GridWise image to Docker Hub.
#
# Before running, ensure your Docker Hub credentials are available:
#
# To find your Docker Hub username:
#   1. Visit https://hub.docker.com/
#   2. Sign in with the credentials your team registered.
#   3. Click your avatar (top right) → "Account Settings".
#   4. Your username is shown under "Username". Copy it.
#
# To create an access token (safer than your password):
#   1. https://hub.docker.com/ → Account Settings → Security → New Access Token.
#   2. Copy the token; use it as the password when `docker login` prompts.
#
# Usage:
#   export DOCKER_USERNAME=ashikonik
#   export DOCKER_REPOSITORY=gridwise-bup-2026
#   export TAG=1.0.0           # default
#   ./publish.sh
#
# Or override on the command line:
#   DOCKER_USERNAME=myuser TAG=2.0.0 ./publish.sh
#
set -euo pipefail

: "${DOCKER_USERNAME:?Set DOCKER_USERNAME (see header comment)}"
: "${DOCKER_REPOSITORY:=gridwise-bup-2026}"
TAG="${TAG:-1.0.0}"
IMAGE="${DOCKER_USERNAME}/${DOCKER_REPOSITORY}:${TAG}"

cd "$(dirname "$0")"

echo ">> Building ${IMAGE}"
docker build -t "${IMAGE}" .

echo ">> Logging in to Docker Hub"
# `docker login` reads creds from ~/.docker/config.json if present,
# otherwise prompts for username + password (use your access token).
docker login

echo ">> Pushing ${IMAGE}"
docker push "${IMAGE}"

echo ">> Done. Judges can now:"
echo "     docker pull ${IMAGE}"
echo "     docker run -p 8000:8000 ${IMAGE}"
