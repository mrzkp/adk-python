"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEMO: Customer Support Triage — Semantic Early-Exit                         ║
║                                                                              ║
║  A customer asks "Why was I charged twice?"                                   ║
║  3 agents investigate in parallel:                                            ║
║    • agent_crm (2s)            — checks customer billing records              ║
║    • agent_knowledge_base (3s) — searches known issues                        ║
║    • agent_escalation (15s)    — reviews manager escalation logs (SLOW)       ║
║                                                                              ║
║  CRM + KB are enough to explain the issue. Escalation log is cancelled.       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from google.adk import Agent
from google.adk import Workflow
from google.adk.workflow import SufficientJoinNode
from google.adk.workflow import node

from _common import BOLD
from _common import CYAN
from _common import DIM
from _common import GREEN
from _common import RED
from _common import RESET
from _common import WHITE
from _common import YELLOW
from _common import header
from _common import metrics_table
from _common import run_workflow
from _common import subheader

# ─── Mock Agents ───────────────────────────────────────────────────────────────


@node()
async def agent_crm(ctx, node_input: str):
    """CRM lookup — fast (~2s)."""
    await asyncio.sleep(2)
    yield (
        'CRM Record for customer #4892: Two charges of $49.99 on 2026-05-20.'
        ' First charge: subscription renewal (auto-pay). Second charge: manual'
        ' retry triggered by payment gateway timeout at 14:32 UTC.'
        ' Status: both charges SETTLED. No refund issued yet.'
    )


@node()
async def agent_knowledge_base(ctx, node_input: str):
    """Knowledge base search — fast (~3s)."""
    await asyncio.sleep(3)
    yield (
        'KB Article #1847: "Duplicate charges during gateway timeouts."'
        ' Root cause: Payment processor retries on 504 timeout without'
        ' idempotency key. Known issue since 2026-03. Workaround: manual'
        ' refund via billing dashboard. Fix ETA: Sprint 47 (June 2026).'
    )


@node()
async def agent_escalation(ctx, node_input: str):
    """Escalation log review — slow (~15s)."""
    await asyncio.sleep(15)
    yield (
        'Escalation Log: No prior escalations for customer #4892.'
        ' Similar pattern seen in 12 other tickets this month.'
        ' Manager note: "Prioritize gateway idempotency fix."'
    )


# ─── Workflow Definition ───────────────────────────────────────────────────────

QUESTION = 'Why was I charged twice for my subscription? Please explain and help.'

synthesizer = Agent(
    name='synthesizer',
    instruction=(
        'You are a customer support specialist. You will receive investigation'
        ' data from your team. Write a friendly, clear response to the customer'
        f' addressing their concern: "{QUESTION}"'
        ' Include: what happened, why, and what you will do to fix it.'
    ),
)

sufficient_join = SufficientJoinNode(
    name='sufficient_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
)

workflow = Workflow(
    name='customer_support',
    edges=[
        ('START', agent_crm),
        ('START', agent_knowledge_base),
        ('START', agent_escalation),
        (agent_crm, sufficient_join),
        (agent_knowledge_base, sufficient_join),
        (agent_escalation, sufficient_join),
        (sufficient_join, synthesizer),
    ],
)

# ─── Run ───────────────────────────────────────────────────────────────────────


async def main():
    print(header('CUSTOMER SUPPORT TRIAGE — Semantic Early-Exit Demo'))

    print(f'{BOLD}  Customer Question:{RESET} {QUESTION}')
    print(subheader('Agents'))
    print(f'  {GREEN}●{RESET} agent_crm             {DIM}(~2s, CRM billing lookup){RESET}')
    print(f'  {GREEN}●{RESET} agent_knowledge_base  {DIM}(~3s, known issues search){RESET}')
    print(f'  {RED}●{RESET} agent_escalation      {DIM}(~15s, escalation log — STALLER){RESET}')
    print(subheader('Execution'))

    start = time.perf_counter()
    result = await run_workflow(workflow, QUESTION, log_events=True)

    print(f'\n  {GREEN}✓{RESET} Customer response:')
    print(f'  {DIM}"{result.final_output[:250]}"{RESET}')

    print(metrics_table(
        standard_time=15.0 + 3.0,
        blackboard_time=result.elapsed,
        cancelled_count=1,
    ))
    print()


if __name__ == '__main__':
    asyncio.run(main())
