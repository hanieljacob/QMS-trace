#!/usr/bin/env bash
# Create (or update) the qmstrace Lambda + a public Function URL, then print the
# URL. Requires AWS credentials in the environment and that build_lambda.sh has
# already produced the zip.
#
#   ./deploy/deploy_lambda.sh
#
# Everything here is within the AWS always-free tier for demo traffic: Lambda
# (1M req/mo, always free) and a Function URL (no API Gateway). No ECR, no VPC.
set -euo pipefail

FUNC="${QMSTRACE_FUNCTION_NAME:-qmstrace-demo}"
REGION="${AWS_REGION:-us-east-1}"
ARCH="${LAMBDA_ARCH:-x86_64}"
RUNTIME="python3.12"
ROLE_NAME="${FUNC}-role"
ZIP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/build/qmstrace-lambda.zip"

[ -f "$ZIP" ] || { echo "missing $ZIP — run deploy/build_lambda.sh first" >&2; exit 1; }
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"

echo "==> Ensure IAM execution role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null
  echo "   created $ROLE_NAME; waiting for propagation"
  sleep 12
fi

if aws lambda get-function --function-name "$FUNC" --region "$REGION" >/dev/null 2>&1; then
  echo "==> Update function code"
  aws lambda update-function-code --function-name "$FUNC" --region "$REGION" \
    --zip-file "fileb://$ZIP" >/dev/null
else
  echo "==> Create function"
  aws lambda create-function --function-name "$FUNC" --region "$REGION" \
    --runtime "$RUNTIME" --architectures "$ARCH" \
    --handler lambda_function.handler \
    --role "$ROLE_ARN" \
    --timeout 30 --memory-size 512 \
    --zip-file "fileb://$ZIP" >/dev/null
fi

echo "==> Wait for function to be ready"
aws lambda wait function-updated --function-name "$FUNC" --region "$REGION"

echo "==> Ensure public Function URL"
if ! aws lambda get-function-url-config --function-name "$FUNC" --region "$REGION" >/dev/null 2>&1; then
  aws lambda create-function-url-config --function-name "$FUNC" --region "$REGION" \
    --auth-type NONE >/dev/null
  aws lambda add-permission --function-name "$FUNC" --region "$REGION" \
    --statement-id public-url --action lambda:InvokeFunctionUrl \
    --principal '*' --function-url-auth-type NONE >/dev/null
fi

URL="$(aws lambda get-function-url-config --function-name "$FUNC" --region "$REGION" --query FunctionUrl --output text)"
echo ""
echo "Public URL: $URL"
