#!/bin/sh
# build-all.sh - one command to check + build the GT evidence library.
#
# Runs the two content checkers, then the site builder. If EITHER checker
# fails, the script stops immediately and does NOT build (so a broken article
# never regenerates the site).
#
#   1. check_facts.py  - stats match the vetted canonical values (no conflicts)
#   2. check_style.py  - house rules (no competitor names, no em dashes, etc.)
#   3. build.py        - regenerates the site/ folder from the .md articles
#
# No deploy step here on purpose. Deploying is a separate, deliberate action.
#
# Usage:
#   ./build-all.sh
# (first time only, make it runnable:  chmod +x build-all.sh )

# Run from the repo root, wherever this script lives.
cd "$(dirname "$0")" || exit 1

echo "==> [1/3] Checking facts..."
if ! python3 check_facts.py; then
  echo ""
  echo "STOPPED: fact check failed. Nothing was built. Fix the items above and re-run."
  exit 1
fi

echo ""
echo "==> [2/3] Checking house rules..."
if ! python3 check_style.py; then
  echo ""
  echo "STOPPED: style check failed. Nothing was built. Fix the items above and re-run."
  exit 1
fi

echo ""
echo "==> [3/3] Building the site..."
if ! python3 build.py; then
  echo ""
  echo "STOPPED: the build failed. See the error above."
  exit 1
fi

echo ""
echo "Done. Both checks passed and the site/ folder is rebuilt."
echo "Nothing has been published yet - deploying is a separate step."
