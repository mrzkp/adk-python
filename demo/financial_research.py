"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEMO: Financial Research — Semantic Early-Exit                             ║
║                                                                              ║
║  3 research agents investigate why a stock is dropping:                       ║
║    • agent_news (2s)       — scrapes breaking news                           ║
║    • agent_sentiment (3s)  — analyzes social media                           ║
║    • agent_filings (20s)   — reads SEC 10-K filings (THE STALLER)            ║
║                                                                              ║
║  After agents A+B return, the evaluator says "sufficient" and the            ║
║  synthesizer fires immediately. Agent C gets cancelled.                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Add repo root to path
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
from _common import status_evaluator
from _common import subheader

# ─── Mock Agents ───────────────────────────────────────────────────────────────


@node()
async def agent_news(ctx, node_input: str):
    """Fast news scraper (~2s)."""
    await asyncio.sleep(2)
    yield (
        'BREAKING: Acme Corp CEO John Smith unexpectedly resigned yesterday,'
        ' effective immediately. The board cited "irreconcilable strategic'
        ' differences." Three senior VPs departed the same day.'
    )


@node()
async def agent_sentiment(ctx, node_input: str):
    """Fast sentiment analyzer (~3s)."""
    await asyncio.sleep(3)
    yield (
        'Social sentiment: 84% negative across Twitter/Reddit in the past 24h.'
        ' Top trending tags: #AcmeMeltdown, #CEOResigns, #SellAcme.'
        ' Retail investor forums show a surge in sell orders.'
    )


@node()
async def agent_filings(ctx, node_input: str):
    """Slow SEC filing reader (~20s) — THE STALLER."""
    await asyncio.sleep(20)
    yield (
        'SEC 10-K (FY2025): Revenue declined 38% YoY to $1.2B.'
        ' Net loss of $340M. Significant covenant breach on $800M revolving'
        ' credit facility. Auditors issued a going-concern qualification.'
    )


# ─── Workflow Definition ───────────────────────────────────────────────────────

QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."

synthesizer = Agent(
    name='synthesizer',
    instruction=(
        'You are a financial analyst. You will receive research data collected'
        ' by your team as the user message. Write a concise, well-structured'
        f' briefing (3-5 sentences) answering: "{QUESTION}"'
    ),
)

sufficient_join = SufficientJoinNode(
    name='sufficient_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
)

workflow = Workflow(
    name='financial_research',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news, sufficient_join),
        (agent_sentiment, sufficient_join),
        (agent_filings, sufficient_join),
        (sufficient_join, synthesizer),
    ],
)


# ─── Run ───────────────────────────────────────────────────────────────────────


async def main():
    print(header('FINANCIAL RESEARCH — Semantic Early-Exit Demo'))

    print(f'{BOLD}  Question:{RESET} {QUESTION}')
    print(subheader('Agents'))
    print(f'  {GREEN}●{RESET} agent_news        {DIM}(~2s, fast){RESET}')
    print(f'  {GREEN}●{RESET} agent_sentiment   {DIM}(~3s, fast){RESET}')
    print(f'  {RED}●{RESET} agent_filings     {DIM}(~20s, STALLER){RESET}')
    print(subheader('Execution'))

    start = time.perf_counter()
    result = await run_workflow(workflow, QUESTION, log_events=True)

    print(f'\n  {GREEN}✓{RESET} Synthesizer output:')
    print(f'  {DIM}"{result.final_output[:200]}"{RESET}')

    print(metrics_table(
        standard_time=20.0 + 3.0,  # estimated if we waited for all
        blackboard_time=result.elapsed,
        cancelled_count=1,
    ))
    print()


if __name__ == '__main__':
    asyncio.run(main())
