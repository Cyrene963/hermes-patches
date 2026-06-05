#!/bin/bash
# apply_hermes_patches.sh - Apply custom Hermes patch bundle after hermes update.
# Canonical path: ~/.hermes/patches/install.sh
# Keep this wrapper tiny so hermes-update-with-patches.sh cannot drift from the
# maintained patch installer.

set -e

PATCH_INSTALLER="$HOME/.hermes/patches/install.sh"

if [ ! -x "$PATCH_INSTALLER" ]; then
    echo "❌ Patch installer not found or not executable: $PATCH_INSTALLER"
    exit 1
fi

bash "$PATCH_INSTALLER" "$@"
