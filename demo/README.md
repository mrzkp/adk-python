# SufficientJoinNode Demo — Semantic Early-Exit for Multi-Agent Workflows

## The Problem

Every multi-agent AI framework uses a hard synchronization barrier: when you
fan out to multiple research agents and one stalls, your entire pipeline
freezes. We replaced that with a **semantic gate** — a single fast LLM call
that asks "is this enough?" — and wired it into Google ADK's existing join
node abstraction.

## Three Modes

| Mode | Internal Name | Behavior | Trade-off |
|------|---------------|----------|-----------|
| **Pessimistic** (Standard) | `strategy='standard'` | WaitAll at every join | Slowest, 100% data |
| **Blind Optimism** (Optimistic) | `strategy='optimistic'` | Cancels stragglers on sufficiency | Fastest, discards late data |
| **Pessimistic Optimism** (Pessimistic) | `strategy='pessimistic'` | Speculates, reconciles late arrivals | Fast draft + eventual completeness |

## Quick Start

```bash
# From the adk-python repo root:
export GOOGLE_API_KEY=<your-gemini-api-key>

# The showstopper — all three modes side-by-side
uv run python demo/three_way_comparison.py

# Pessimistic optimism in detail (speculative → reconcile flow)
uv run python demo/pessimistic_optimism.py

# Original optimistic demos
uv run python demo/side_by_side.py
uv run python demo/financial_research.py
uv run python demo/customer_support.py
uv run python demo/academic_review.py
```

## Demo Scenarios

| Demo | Mode | What It Shows |
|------|------|---------------|
| `multilayer_pipeline.py` | All 3 | Pessimistic vs Blind Optimism vs Pessimistic Optimism (visualizer) |
| `three_way_comparison.py` | All 3 | Pessimistic vs Blind Optimism vs Pessimistic Optimism side-by-side |
| `pessimistic_optimism.py` | Pessimistic Optimism | Speculative Report v1 → Reconciliation → Report v2 |
| `side_by_side.py` | Std vs Opt | Pessimistic vs Blind Optimism A/B comparison |
| `financial_research.py` | Blind Optimism | Single optimistic run with metrics |
| `customer_support.py` | Blind Optimism | CRM/KB/Escalation scenario |
| `academic_review.py` | Blind Optimism | Abstract/Citations/Full-text scenario |

## Architecture

### Blind Optimism (cancel stragglers)

```
Agent A (2s) ──┐
Agent B (3s) ──┤→ SufficientJoinNode → Evaluator: "Sufficient?" → YES
Agent C (20s) ─┘     │                                    │
                      │                              ❌ C CANCELLED
                      ▼
               Synthesizer → Report (one shot, ~5s)
```

### Pessimistic Optimism (speculate + reconcile)

```
Agent A (2s) ──┐
Agent B (3s) ──┤→ SufficientJoinNode → Evaluator: "Sufficient?" → YES
Agent C (15s) ─┘     │            │                          │
                     │            │                    C keeps running
                     ▼            │
              Synthesizer         │
              → Report v1 (~5s)   │
                                  │
         C finishes (15s) ────────┘
                     │
              SufficientJoinNode (re-triggered)
              → Reconciler: "Merge or Contradict?" → MERGE
                     │
                     ▼
              Synthesizer (re-runs)
              → Report v2 (~20s, full data)
```

## Key Files

- `demo/` — This directory (standalone demo scripts)
- `src/google/adk/workflow/_sufficient_join_node.py` — Core implementation (both strategies)
- `src/google/adk/workflow/_workflow.py` — Modified `_buffer_downstream_triggers` + early-exit
- `src/google/adk/workflow/_base_node.py` — Added `_requires_partial_predecessors`
