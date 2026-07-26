#!/usr/bin/env bash
# Put a public API Gateway HTTP API in front of the qmstrace Lambda. API Gateway
# invokes the function through the standard Invoke API (not the Function URL),
# which this account allows. Gives a public https://<id>.execute-api...amazonaws.com
# URL that serves both the SPA and the API.
#
#   ./deploy/deploy_apigateway.sh
set -euo pipefail

FUNC="${QMSTRACE_FUNCTION_NAME:-qmstrace-demo}"
REGION="${AWS_REGION:-us-east-1}"
API_NAME="${FUNC}-http"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
FUNC_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNC}"

# Reuse an existing API of this name if present.
API_ID="$(aws apigatewayv2 get-apis --region "$REGION" \
  --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text)"

if [ "$API_ID" = "None" ] || [ -z "$API_ID" ]; then
  echo "==> Create HTTP API with Lambda proxy integration"
  API_ID="$(aws apigatewayv2 create-api --region "$REGION" \
    --name "$API_NAME" --protocol-type HTTP \
    --target "$FUNC_ARN" \
    --query ApiId --output text)"
  echo "   API: $API_ID"
else
  echo "==> Reusing existing API: $API_ID"
fi

echo "==> Allow API Gateway to invoke the function"
aws lambda add-permission --function-name "$FUNC" --region "$REGION" \
  --statement-id apigw-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT}:${API_ID}/*/*" \
  >/dev/null 2>&1 || true

ENDPOINT="$(aws apigatewayv2 get-api --region "$REGION" --api-id "$API_ID" \
  --query ApiEndpoint --output text)"
echo ""
echo "API id: $API_ID"
echo "Public URL: ${ENDPOINT}/"
