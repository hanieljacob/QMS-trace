#!/usr/bin/env bash
# Build the qmstrace Lambda deployment package (a zip), entirely locally.
#
#   ./deploy/build_lambda.sh
#
# Produces deploy/build/qmstrace-lambda.zip containing:
#   - Linux (manylinux) wheels for the runtime dependencies
#   - the backend application code (app/)
#   - the built React SPA (web/)
#   - a pre-seeded, signed SQLite database (seed.db)
#   - the Lambda entrypoint (lambda_function.py)
set -euo pipefail

ARCH="${LAMBDA_ARCH:-x86_64}"           # x86_64 or aarch64
PY="${LAMBDA_PYTHON_VERSION:-3.12}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/deploy/build"
PKG="$BUILD/package"

case "$ARCH" in
  x86_64)  PLATFORM="manylinux2014_x86_64" ;;
  aarch64) PLATFORM="manylinux2014_aarch64" ;;
  *) echo "unknown LAMBDA_ARCH: $ARCH" >&2; exit 1 ;;
esac

echo "==> Clean build dir"
rm -rf "$BUILD"
mkdir -p "$PKG"

echo "==> Build frontend (Vite)"
( cd "$ROOT/frontend" && npm install --no-fund --no-audit && npm run build )

echo "==> Seed + sign the demo database"
( cd "$ROOT/backend" && .venv/bin/python "$ROOT/deploy/make_seed_db.py" "$PKG/seed.db" )

echo "==> Download Linux dependency wheels ($PLATFORM, py$PY)"
python3 -m pip install \
  --platform "$PLATFORM" \
  --implementation cp \
  --python-version "$PY" \
  --only-binary=:all: \
  --upgrade \
  --target "$PKG" \
  -r "$ROOT/deploy/requirements-lambda.txt"

echo "==> Copy application code, SPA, and entrypoint"
cp -R "$ROOT/backend/app" "$PKG/app"
cp -R "$ROOT/frontend/dist" "$PKG/web"
cp "$ROOT/deploy/lambda_function.py" "$PKG/lambda_function.py"

echo "==> Strip caches (keep dist-info: some libs read it at import)"
find "$PKG" -type d -name '__pycache__' -prune -exec rm -rf {} +

echo "==> Zip"
( cd "$PKG" && zip -q -r -X "$BUILD/qmstrace-lambda.zip" . )
echo "==> Wrote $BUILD/qmstrace-lambda.zip ($(du -h "$BUILD/qmstrace-lambda.zip" | cut -f1))"
