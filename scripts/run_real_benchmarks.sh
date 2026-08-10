#!/usr/bin/env bash
# scripts/run_real_benchmarks.sh — run benchmarks with real LLM embeddings
# Requires OPENAI_API_KEY or DEEPSEEK_API_KEY in environment
#
# Runs the suite twice — text-embedding-3-small then text-embedding-3-large —
# and merges both JSON reports into a per-dimension two-column Markdown
# report (issue #18, T2).  If the 3-large run fails, the script keeps going
# and the renderer falls back to a single-column report instead of crashing.
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

# Run 1: real embeddings, text-embedding-3-small (baseline, current behavior)
# Explicit model selection needs OPENAI_API_KEY; without it we keep the
# historical behavior: --real goes through the provider factory fallback
# chain (fastembed / mock) so a DeepSeek-only env can still reach Run 3.
if [ -n "${OPENAI_API_KEY:-}" ]; then
    echo "Running benchmarks with text-embedding-3-small (1536 dims)..."
    python scripts/run_benchmarks.py --real --embedding-model text-embedding-3-small
else
    echo "OPENAI_API_KEY not set — running with provider factory fallback..."
    python scripts/run_benchmarks.py --real
fi
SMALL_REPORT=$(ls -1t "$REPORTS_DIR"/benchmark-*.json 2>/dev/null | head -1)
if [ -z "$SMALL_REPORT" ]; then
    echo "ERROR: No benchmark report generated for 3-small" >&2
    exit 1
fi
echo "3-small report: $SMALL_REPORT"

# Run 2: real embeddings, text-embedding-3-large (tolerate failure;
# also skipped when OPENAI_API_KEY is absent)
LARGE_REPORT=""
if [ -n "${OPENAI_API_KEY:-}" ]; then
    echo "Running benchmarks with text-embedding-3-large (3072 dims)..."
    if python scripts/run_benchmarks.py --real --embedding-model text-embedding-3-large; then
        LARGE_REPORT=$(ls -1t "$REPORTS_DIR"/benchmark-*.json 2>/dev/null | head -1)
        # Guard against the (unlikely) same-second filename collision
        if [ "$LARGE_REPORT" = "$SMALL_REPORT" ]; then
            echo "WARNING: 3-large run produced no new report; treating it as failed" >&2
            LARGE_REPORT=""
        fi
        echo "3-large report: $LARGE_REPORT"
    else
        echo "WARNING: 3-large run failed; rendering single-column report" >&2
    fi
else
    echo "OPENAI_API_KEY not set — skipping 3-large run" >&2
fi

# Convert to Markdown: two-column comparison, or single-column fallback
if [ -n "$LARGE_REPORT" ]; then
    python scripts/benchmark_to_markdown.py \
        --dual \
        --small "$SMALL_REPORT" \
        --large "$LARGE_REPORT" \
        --output "$DOCS_DIR/real-llm-results.md"
else
    python scripts/benchmark_to_markdown.py \
        "$SMALL_REPORT" \
        "$DOCS_DIR/real-llm-results.md"
fi
echo "Baseline report: $DOCS_DIR/real-llm-results.md"

# Run 3: real embeddings + LLM relationship classification (if DeepSeek available)
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
