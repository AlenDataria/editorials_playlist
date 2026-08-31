#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <ecr_repository_url> [tag]"
  echo "Example: $0 123456789012.dkr.ecr.eu-west-1.amazonaws.com/editorials-playlist-app latest"
  exit 1
fi

ECR_REPOSITORY_URL="$1"
TAG="${2:-latest}"
AWS_REGION="${AWS_REGION:-eu-west-1}"
IMAGE_URI="${ECR_REPOSITORY_URL}:${TAG}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Build a Linux image compatible with ECS Fargate.
docker buildx build --platform linux/amd64 -t "${IMAGE_URI}" --load .
docker push "${IMAGE_URI}"

echo "Pushed image: ${IMAGE_URI}"
