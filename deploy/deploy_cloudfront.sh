#!/usr/bin/env bash
# Put a public CloudFront distribution in front of the qmstrace Lambda Function
# URL. CloudFront signs requests to the origin (Origin Access Control), so the
# Function URL is switched to IAM auth and is no longer relied on for anonymous
# access. Result: a public https://<id>.cloudfront.net URL, always-free tier.
#
#   ./deploy/deploy_cloudfront.sh
#
# Prints the CloudFront domain and the distribution id. The distribution takes a
# few minutes to finish deploying after this returns.
set -euo pipefail

FUNC="${QMSTRACE_FUNCTION_NAME:-qmstrace-demo}"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

FUNC_URL="$(aws lambda get-function-url-config --function-name "$FUNC" --region "$REGION" --query FunctionUrl --output text)"
ORIGIN_DOMAIN="$(echo "$FUNC_URL" | sed -E 's#^https?://##; s#/$##')"
echo "==> Origin (Function URL host): $ORIGIN_DOMAIN"

echo "==> Switch Function URL to IAM auth (CloudFront will sign)"
aws lambda update-function-url-config --function-name "$FUNC" --region "$REGION" --auth-type AWS_IAM >/dev/null
aws lambda remove-permission --function-name "$FUNC" --region "$REGION" --statement-id FunctionURLAllowPublicAccess 2>/dev/null || true
aws lambda remove-permission --function-name "$FUNC" --region "$REGION" --statement-id public-url 2>/dev/null || true

echo "==> Create Origin Access Control (lambda, sigv4, always)"
OAC_ID="$(aws cloudfront create-origin-access-control --origin-access-control-config '{
  "Name":"qmstrace-oac-'"$(date +%s)"'",
  "OriginAccessControlOriginType":"lambda",
  "SigningBehavior":"always",
  "SigningProtocol":"sigv4",
  "Description":"qmstrace Lambda OAC"
}' --query 'OriginAccessControl.Id' --output text)"
echo "   OAC: $OAC_ID"

CONFIG="$(mktemp)"
cat > "$CONFIG" <<JSON
{
  "CallerReference": "qmstrace-$(date +%s)",
  "Comment": "qmstrace demo",
  "Enabled": true,
  "PriceClass": "PriceClass_100",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "qmstrace-lambda",
        "DomainName": "$ORIGIN_DOMAIN",
        "OriginPath": "",
        "OriginAccessControlId": "$OAC_ID",
        "CustomHeaders": { "Quantity": 0 },
        "CustomOriginConfig": {
          "HTTPPort": 80,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "https-only",
          "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] },
          "OriginReadTimeout": 60,
          "OriginKeepaliveTimeout": 5
        },
        "ConnectionAttempts": 3,
        "ConnectionTimeout": 10,
        "OriginShield": { "Enabled": false }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "qmstrace-lambda",
    "ViewerProtocolPolicy": "redirect-to-https",
    "Compress": true,
    "AllowedMethods": {
      "Quantity": 7,
      "Items": ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"],
      "CachedMethods": { "Quantity": 2, "Items": ["GET","HEAD"] }
    },
    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
    "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }
}
JSON

echo "==> Create CloudFront distribution"
read -r DIST_ID DIST_DOMAIN <<<"$(aws cloudfront create-distribution --distribution-config "file://$CONFIG" \
  --query '[Distribution.Id,Distribution.DomainName]' --output text)"
rm -f "$CONFIG"
echo "   Distribution: $DIST_ID"

echo "==> Allow CloudFront to invoke the Function URL"
aws lambda add-permission --function-name "$FUNC" --region "$REGION" \
  --statement-id cloudfront-oac \
  --action lambda:InvokeFunctionUrl \
  --principal cloudfront.amazonaws.com \
  --source-arn "arn:aws:cloudfront::${ACCOUNT}:distribution/${DIST_ID}" \
  --function-url-auth-type AWS_IAM >/dev/null

echo ""
echo "Distribution id: $DIST_ID"
echo "Public URL: https://$DIST_DOMAIN/"
echo "(CloudFront takes a few minutes to finish deploying.)"
