#!/usr/bin/env bash
# Remove everything the qmstrace deploy scripts created, so nothing can accrue
# charges.
#
#   ./deploy/teardown.sh
#
# Deleting the Lambda function also removes its Function URL config and
# resource-based permissions. The CloudFront distribution (if one was created)
# costs nothing while idle but is not auto-deleted here, because deletion
# requires a disable-and-wait cycle; instructions are printed at the end.
set -uo pipefail

FUNC="${QMSTRACE_FUNCTION_NAME:-qmstrace-demo}"
REGION="${AWS_REGION:-us-east-1}"
ROLE_NAME="${FUNC}-role"
API_NAME="${FUNC}-http"

echo "==> Delete API Gateway HTTP API (if any)"
API_ID="$(aws apigatewayv2 get-apis --region "$REGION" \
  --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text 2>/dev/null)"
if [ -n "$API_ID" ] && [ "$API_ID" != "None" ]; then
  aws apigatewayv2 delete-api --region "$REGION" --api-id "$API_ID" && echo "   deleted API $API_ID"
fi

echo "==> Delete Lambda function (removes Function URL + permissions)"
aws lambda delete-function --function-name "$FUNC" --region "$REGION" 2>/dev/null \
  && echo "   deleted $FUNC" || echo "   (no function)"

echo "==> Detach policy and delete execution role"
aws iam detach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true
aws iam delete-role --role-name "$ROLE_NAME" 2>/dev/null \
  && echo "   deleted role $ROLE_NAME" || echo "   (no role)"

echo ""
echo "==> Core resources removed."

DIST_ID="$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='qmstrace demo'].Id | [0]" --output text 2>/dev/null)"
if [ -n "$DIST_ID" ] && [ "$DIST_ID" != "None" ]; then
  echo ""
  echo "A CloudFront distribution ($DIST_ID) still exists. It costs nothing idle."
  echo "To remove it: disable it (console or update-distribution Enabled=false),"
  echo "wait for it to finish deploying, then:"
  echo "    aws cloudfront delete-distribution --id $DIST_ID --if-match <ETag>"
  echo "and delete the Origin Access Control from the CloudFront console."
fi
