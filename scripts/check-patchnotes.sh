#!/usr/bin/env bash
# Pre-commit hook: ensure at least one .patchnotes/*.yml file exists
# when committing changes (skip if only .patchnotes/ files are changed).

set -euo pipefail

# Get the default branch
DEFAULT_BRANCH="main"

# If we're on the default branch, skip the check (merge commits)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ "$CURRENT_BRANCH" = "$DEFAULT_BRANCH" ]; then
    exit 0
fi

# Check if any .patchnotes/*.yml files exist in the staging area or working tree
PATCHNOTES=$(git ls-files -- '.patchnotes/*.yml' 2>/dev/null || true)
if [ -z "$PATCHNOTES" ]; then
    # Also check staged but not yet tracked files
    PATCHNOTES=$(git diff --cached --name-only -- '.patchnotes/*.yml' 2>/dev/null || true)
fi

if [ -z "$PATCHNOTES" ]; then
    echo ""
    echo "ERROR: No patchnote found!"
    echo ""
    echo "Please create a .patchnotes/<branch-name>.yml file:"
    echo ""
    echo "  type: feature    # feature | fix | breaking | docs | internal"
    echo "  description: \"Short description of the change\""
    echo "  breaking: false"
    echo ""
    echo "See .patchnotes/example.yml.template for reference."
    echo ""
    exit 1
fi
