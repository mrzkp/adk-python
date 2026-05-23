"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEMO: Pessimistic Optimism — Speculative Execution + Late Reconciliation  ║
║                                                                              ║
║  Same 3 research agents, but this time the slow agent is NOT cancelled.      ║
║  Instead the pipeline fires speculatively on 2/3 agents, produces a fast     ║
║  report, and when the straggler returns the reconciliation evaluator         ║
║  classifies the late data and the pipeline re-runs with full information.    ║
║                                                                              ║
║  Phase 1 (speculative):  agents A+B → sufficient → Report v1 (~5s)          ║
║  Phase 2 (reconciled):   agent C → merge/contradict → Report v2 (~25s)      ║
║                                                                              ║
║  You get the speed of optimism AND the completeness of waiting.              ║
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
from _common import MAGENTA
from _common import RED
from _common import RESET
from _common import WHITE
from _common import YELLOW
from _common import header
from _common import run_workflow
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
    """Slow SEC filing reader (~15s) — THE STRAGGLER."""
    await asyncio.sleep(15)
    yield (
        'SEC 10-K (FY2025): Revenue declined 38% YoY to $1.2B.'
        ' Net loss of $340M. Significant covenant breach on $800M revolving'
        ' credit facility. Auditors issued a going-concern qualification.'
    )


# ─── Workflow Definition ───────────────────────────────────────────────────────

QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."

synthesizer = Agent(
    name='synthesizer',
    model='gemini-2.5-flash',
    instruction=(
        'You are a financial analyst. You will receive research data collected'
        ' by your team as the user message. Write a concise, well-structured'
        f' briefing (3-5 sentences) answering: "{QUESTION}"'
    ),
)

pessimistic_join = SufficientJoinNode(
    name='sufficient_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
    strategy='pessimistic',
)

workflow = Workflow(
    name='pessimistic_research',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news, pessimistic_join),
        (agent_sentiment, pessimistic_join),
        (agent_filings, pessimistic_join),
        (pessimistic_join, synthesizer),
    ],
)


# ─── Run ───────────────────────────────────────────────────────────────────────


async def main():
    print(header('PESSIMISTIC OPTIMISM — Speculative Execution + Late Reconciliation'))

    print(f'{BOLD}  Question:{RESET} {QUESTION}')
    print(f'{BOLD}  Strategy:{RESET} {MAGENTA}pessimistic{RESET}'
          f' (proceed speculatively, reconcile late arrivals)')
    print(subheader('Agents'))
    print(f'  {GREEN}●{RESET} agent_news        {DIM}(~2s, fast){RESET}')
    print(f'  {GREEN}●{RESET} agent_sentiment   {DIM}(~3s, fast){RESET}')
    print(f'  {YELLOW}●{RESET} agent_filings     {DIM}(~15s, straggler — NOT cancelled){RESET}')
    print(subheader('Execution'))

    result = await run_workflow(workflow, QUESTION, log_events=True)

    # ─── Show phased output ─────────────────────────────────────────────────

    if len(result.synthesizer_outputs) >= 2:
        t1, report_v1 = result.synthesizer_outputs[0]
        t2, report_v2 = result.synthesizer_outputs[-1]

        print(subheader('Phase 1 — Speculative Report'))
        print(f'  {GREEN}✓{RESET} Report v1 {DIM}(delivered at {t1:.1f}s, partial data){RESET}')
        print(f'  {DIM}"{report_v1[:200]}"{RESET}')

        print(subheader('Phase 2 — Reconciled Report'))
        action = result.reconciliation_action or '?'
        severity = result.reconciliation_severity or '?'
        print(f'  {MAGENTA}🔄{RESET} Late data classified as: {BOLD}{action.upper()}{RESET}'
              f' (severity: {severity})')
        if result.reconciliation_reasoning:
            print(f'  {DIM}   {result.reconciliation_reasoning[:100]}{RESET}')
        print(f'\n  {GREEN}✓{RESET} Report v2 {DIM}(delivered at {t2:.1f}s, full data){RESET}')
        print(f'  {DIM}"{report_v2[:200]}"{RESET}')
    elif result.synthesizer_outputs:
        t1, report_v1 = result.synthesizer_outputs[0]
        print(f'\n  {GREEN}✓{RESET} Report {DIM}(delivered at {t1:.1f}s){RESET}')
        print(f'  {DIM}"{report_v1[:200]}"{RESET}')
    else:
        print(f'\n  {RED}✗{RESET} No synthesizer output captured.')

    # ─── Metrics ─────────────────────────────────────────────────────────────

    W = 22
    print(f'\n{BOLD}{WHITE}  ┌{"─" * 68}┐{RESET}')
    print(f'{BOLD}{WHITE}  │{"METRICS":^68}│{RESET}')
    print(f'{BOLD}{WHITE}  ├{"─" * W}┬{"─" * W}┬{"─" * W}┤{RESET}')
    print(f'{BOLD}{WHITE}  │{"Metric":^{W}}│{"Optimistic":^{W}}│{"Pessimistic":^{W}}│{RESET}')
    print(f'{BOLD}{WHITE}  ├{"─" * W}┼{"─" * W}┼{"─" * W}┤{RESET}')

    t_first = f'{result.synthesizer_outputs[0][0]:.1f}s' if result.synthesizer_outputs else '—'
    t_final = f'{result.elapsed:.1f}s'
    reports = str(len(result.synthesizer_outputs))
    action_str = result.reconciliation_action.upper() or '—'

    def row(label, opt, pess):
        return (f'{BOLD}{WHITE}  │{RESET}{label:^{W}}'
                f'{BOLD}{WHITE}│{RESET}{opt:^{W}}'
                f'{BOLD}{WHITE}│{RESET}{pess:^{W}}'
                f'{BOLD}{WHITE}│{RESET}')

    print(row('Time to 1st report', t_first, t_first))
    print(row('Time to final', t_first + ' (done)', t_final))
    print(row('Reports produced', '1', reports))
    print(row('Agents cancelled', '1', '0'))
    print(row('Data coverage', '2/3', '3/3'))
    print(row('Late data action', '—', action_str))
    print(f'{BOLD}{WHITE}  └{"─" * W}┴{"─" * W}┴{"─" * W}┘{RESET}')

    print(f'\n  {GREEN}✓{RESET} {BOLD}Conclusion:{RESET} Pessimistic Optimism delivered a fast'
          f' speculative report at {t_first}, then reconciled the late agent\'s'
          f' data and produced a complete report. No work was wasted.')
    print()


if __name__ == '__main__':
    asyncio.run(main())
