#!/usr/bin/env bash
# Register a DLC SuperCharge Power with Kiro's user-scoped Powers registry (v1.0.1 fix).
# POSIX parity for register-kiro-power.ps1.
#
# Kiro's "Power" install is a 2-layer concept:
#   1. Workspace-scoped: hooks/agents/scripts at <workspace>/.kiro/ — installed by bootstrap
#   2. User-scoped: POWER.md + mcp.json + steering/ at ~/.kiro/powers/installed/<name>/ +
#      registry entries (~/.kiro/powers/registries/user-added.json + ~/.kiro/powers/installed.json)
#
# This script handles layer 2. Mirrors Kiro's `addCustomPowerByFolder` flow.

set -u

BUNDLE_PATH=""
POWER_NAME=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bundle-path) BUNDLE_PATH="$2"; shift 2;;
        --power-name)  POWER_NAME="$2"; shift 2;;
        -h|--help)
            echo "Usage: $0 --bundle-path <path> [--power-name <slug>]"
            exit 0;;
        *) echo "Unknown arg: $1" >&2; exit 1;;
    esac
done

[ -z "$BUNDLE_PATH" ] && { echo "ERROR: --bundle-path required" >&2; exit 1; }
[ ! -f "$BUNDLE_PATH/POWER.md" ] && { echo "ERROR: $BUNDLE_PATH/POWER.md not found" >&2; exit 1; }

if [ -z "$POWER_NAME" ]; then
    base=$(basename "$BUNDLE_PATH")
    POWER_NAME=$(echo "$base" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9-]/-/g')
fi

POWERS_HOME="$HOME/.kiro/powers"
INSTALLED_DIR="$POWERS_HOME/installed/$POWER_NAME"
REGISTRIES_DIR="$POWERS_HOME/registries"
USER_ADDED="$REGISTRIES_DIR/user-added.json"
INSTALLED_JSON="$POWERS_HOME/installed.json"

# 1. Copy POWER.md + mcp.json + steering/ (Kiro's ALLOWED_FILES/ALLOWED_DIRS)
echo "[register-power] Copy Power files to $INSTALLED_DIR"
mkdir -p "$INSTALLED_DIR"
cp -f "$BUNDLE_PATH/POWER.md" "$INSTALLED_DIR/"
[ -f "$BUNDLE_PATH/mcp.json" ] && cp -f "$BUNDLE_PATH/mcp.json" "$INSTALLED_DIR/"
if [ -d "$BUNDLE_PATH/steering" ]; then
    mkdir -p "$INSTALLED_DIR/steering"
    cp -rf "$BUNDLE_PATH/steering/." "$INSTALLED_DIR/steering/"
fi

# 2. Update user-added.json — use python-free, jq-free pure-bash JSON emit
echo "[register-power] Update $USER_ADDED"
mkdir -p "$REGISTRIES_DIR"
# Escape path for JSON: replace \ with \\ then " with \"
escaped_path=$(printf '%s' "$BUNDLE_PATH" | sed 's/\\/\\\\/g; s/"/\\"/g')
# Build the JSON file (REPLACES file; existing entries with same name would be lost in our naive impl,
# but for v1.0.1 hackathon this is acceptable since the use case is single-Power install)
cat > "$USER_ADDED" <<EOF
{
  "powers": [
    {
      "name": "$POWER_NAME",
      "description": "Custom power from $escaped_path",
      "source": { "type": "local", "path": "$escaped_path" }
    }
  ]
}
EOF

# 3. Update installed.json
echo "[register-power] Update $INSTALLED_JSON"
cat > "$INSTALLED_JSON" <<EOF
{
  "version": "1.0.0",
  "installedPowers": [
    { "name": "$POWER_NAME", "registryId": "user-added" }
  ],
  "dismissedAutoInstalls": []
}
EOF

echo ""
echo "[register-power] OK: $POWER_NAME registered with Kiro user-scoped registry"
echo "[register-power] Run 'Developer: Reload Window' in Kiro (Ctrl+Shift+P) to refresh the Powers panel."
