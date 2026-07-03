#!/usr/bin/env bash
# scripts/run_real_benchmarks.sh — run benchmarks with real LLM embeddings
# Requires OPENAI_API_KEY or DEEPSEEK_API_KEY in environment
set -euo pipefail

if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo "ERROR: Neither OPENAI_API_KEY nor DEEPSEEK_API_KEY set" >&2
    echo "Export one of them and re-run" >&2
    exit 1
fi

REPORTS_DIR="reports"
mkdir -p "$REPORTS_DIR"
DOCS_DIR="docs/benchmarks"
mkdir -p "$DOCS_DIR"

# Run 1: real embeddings, deterministic relationships (baseline)
echo "Running benchmarks with real embeddings (no LLM rel classification)..."
python scripts/run_benchmarks.py --real

# Locate newest auto-generated report
LATEST=$(ls -1t "$REPORTS_DIR"/benchmark-*.json 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    echo "ERROR: No benchmark report generated" >&2
    exit 1
fi
echo "Latest report: $LATEST"

# Convert to Markdown
python scripts/benchmark_to_markdown.py \
    "$LATEST" \
    "$DOCS_DIR/real-llm-results.md"

echo "Baseline report: $DOCS_DIR/real-llm-results.md"

# Run 2: real embeddings + LLM relationship classification (if DeepSeek available)
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
    echo "Running with LLM relationship classification (DeepSeek)..."
    python scripts/run_benchmarks.py --real --llm
    LATEST_LLM=$(ls -1t "$REPORTS_DIR"/benchmark-*.json 2>/dev/null | head -1)
    python scripts/benchmark_to_markdown.py \
        "$LATEST_LLM" \
        "$DOCS_DIR/real-llm-deepseek-results.md"
    echo "DeepSeek report: $DOCS_DIR/real-llm-deepseek-results.md"
fi

echo "Done. Reports:"
ls -la "$REPORTS_DIR"/benchmark-*.json 2>/dev/null || echo "  (no JSON reports)"
ls -la "$DOCS_DIR"/*.md 2>/dev/null || echo "  (no MD reports)"
