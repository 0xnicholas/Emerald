#!/usr/bin/env bash
# scripts/verify_k8s_manifests.sh — static verification of K8s manifests
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="$REPO_ROOT/k8s"

echo "Verifying K8s manifests in $K8S_DIR..."

# Required manifests
REQUIRED=(
    "namespace.yaml"
    "deployment.yaml"
    "service.yaml"
    "configmap.yaml"
    "secret.yaml"
    "hpa.yaml"
    "ingress.yaml"
    "backup-cronjob.yaml"
)

for m in "${REQUIRED[@]}"; do
    if [ ! -f "$K8S_DIR/$m" ]; then
        echo "ERROR: Missing manifest: $m" >&2
        exit 1
    fi
    echo "✓ $m present"
done

# Validate YAML syntax (try venv Python first, then system)
_PYTHON=$( (command -v .venv/bin/python3 2>/dev/null || command -v python3.12 2>/dev/null || echo python3) | head -1)
$_PYTHON <<'PYEOF'
import sys
from pathlib import Path

import yaml

k8s_dir = Path("k8s")
errors = []

for yaml_file in sorted(k8s_dir.glob("*.yaml")):
    try:
        docs = list(yaml.safe_load_all(yaml_file.read_text()))
        for i, doc in enumerate(docs):
            if doc is None:
                continue
            if "apiVersion" not in doc:
                errors.append(f"{yaml_file.name}: doc {i} missing apiVersion")
            if "kind" not in doc:
                errors.append(f"{yaml_file.name}: doc {i} missing kind")
            if "metadata" not in doc or "name" not in doc.get("metadata", {}):
                errors.append(f"{yaml_file.name}: doc {i} missing metadata.name")
    except yaml.YAMLError as e:
        errors.append(f"{yaml_file.name}: YAML parse error: {e}")

if errors:
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)

print("✓ All manifests valid YAML with required fields")
PYEOF

# Validate namespace consistency (all resources must use 'emerald' namespace)
echo "Checking namespace consistency..."
NON_NS_RAW=$(grep "namespace:" k8s/*.yaml | grep -v "namespace: emerald" || true)
if [ -n "$NON_NS_RAW" ]; then
    echo "ERROR: These manifests don't use 'emerald' namespace:" >&2
    echo "$NON_NS_RAW" >&2
    exit 1
fi
echo "✓ All manifests use 'emerald' namespace"

echo "All K8s manifests validated."
