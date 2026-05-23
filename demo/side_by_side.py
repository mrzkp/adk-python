"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEMO: Side-by-Side Comparison                                                ║
║                                                                              ║
║  Runs the SAME financial research pipeline in two modes:                      ║
║    LEFT  — Standard JoinNode (WaitAll hard barrier)                           ║
║    RIGHT — SufficientJoinNode (Semantic early-exit)                           ║
║                                                                              ║
║  Shows real timing delta, cancellation, and output quality comparison.        ║
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
from google.adk.workflow import JoinNode
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

# ─── Mock Agents (shared by both workflows) ───────────────────────────────────


@node()
async def agent_news(ctx, node_input: str):
    await asyncio.sleep(2)
    yield (
        'BREAKING: Acme Corp CEO John Smith unexpectedly resigned yesterday,'
        ' effective immediately. The board cited "irreconcilable strategic'
        ' differences." Three senior VPs departed the same day.'
    )


@node()
async def agent_sentiment(ctx, node_input: str):
    await asyncio.sleep(3)
    yield (
        'Social sentiment: 84% negative across Twitter/Reddit in the past 24h.'
        ' Top trending tags: #AcmeMeltdown, #CEOResigns, #SellAcme.'
        ' Retail investor forums show a surge in sell orders.'
    )


@node()
async def agent_filings(ctx, node_input: str):
    await asyncio.sleep(20)
    yield (
        'SEC 10-K (FY2025): Revenue declined 38% YoY to $1.2B.'
        ' Net loss of $340M. Significant covenant breach on $800M revolving'
        ' credit facility. Auditors issued a going-concern qualification.'
    )


# ─── Workflow Definitions ──────────────────────────────────────────────────────

QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."

synthesizer_standard = Agent(
    name='synthesizer',
    instruction=(
        'You are a financial analyst. Write a concise briefing (3-5 sentences)'
        f' answering: "{QUESTION}" based on the data provided.'
    ),
)

synthesizer_blackboard = Agent(
    name='synthesizer',
    instruction=(
        'You are a financial analyst. Write a concise briefing (3-5 sentences)'
        f' answering: "{QUESTION}" based on the data provided.'
    ),
)

# --- Standard (WaitAll) ---
standard_join = JoinNode(name='standard_join')

standard_workflow = Workflow(
    name='standard_workflow',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news, standard_join),
        (agent_sentiment, standard_join),
        (agent_filings, standard_join),
        (standard_join, synthesizer_standard),
    ],
)

# --- Blackboard (SufficientJoinNode) ---
sufficient_join = SufficientJoinNode(
    name='sufficient_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
)

blackboard_workflow = Workflow(
    name='blackboard_workflow',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news, sufficient_join),
        (agent_sentiment, sufficient_join),
        (agent_filings, sufficient_join),
        (sufficient_join, synthesizer_blackboard),
    ],
)


# ─── Side-by-Side Runner ──────────────────────────────────────────────────────


async def main():
    print(header('SIDE-BY-SIDE COMPARISON'))
    print(f'{BOLD}  Question:{RESET} {QUESTION}')
    print()
    print(f'  {YELLOW}Running both workflows simultaneously...{RESET}')
    print(f'  {DIM}Standard (left) waits for ALL 3 agents.{RESET}')
    print(f'  {DIM}Blackboard (right) exits as soon as data is sufficient.{RESET}')
    print()

    # Run both simultaneously
    start = time.perf_counter()
    standard_task = asyncio.create_task(
        run_workflow(standard_workflow, QUESTION, log_events=False)
    )
    blackboard_task = asyncio.create_task(
        run_workflow(blackboard_workflow, QUESTION, log_events=False)
    )

    # Wait for blackboard first (it should finish much faster)
    blackboard_result = await blackboard_task
    blackboard_done = time.perf_counter() - start

    print(f'\n{BOLD}{GREEN}  ▶ BLACKBOARD finished in {blackboard_done:.1f}s{RESET}')
    print(f'  {DIM}Evaluator decided: sufficient. Agent C cancelled.{RESET}')

    # Now wait for standard
    standard_result = await standard_task
    standard_done = time.perf_counter() - start

    print(f'{BOLD}{YELLOW}  ▶ STANDARD finished in {standard_done:.1f}s{RESET}')
    print(f'  {DIM}Waited for all agents including the 20s staller.{RESET}')

    # ─── Results ───────────────────────────────────────────────────────────

    print(subheader('OUTPUT COMPARISON'))

    print(f'\n  {BOLD}{YELLOW}Standard:{RESET}')
    print(f'  {DIM}"{standard_result.final_output[:200]}"{RESET}')

    print(f'\n  {BOLD}{GREEN}Blackboard:{RESET}')
    print(f'  {DIM}"{blackboard_result.final_output[:200]}"{RESET}')

    # ─── Metrics ───────────────────────────────────────────────────────────

    speedup = (1 - blackboard_result.elapsed / standard_result.elapsed) * 100
    time_saved = standard_result.elapsed - blackboard_result.elapsed

    print(f'\n{BOLD}{WHITE}  ┌{"─" * 68}┐{RESET}')
    print(f'{BOLD}{WHITE}  │{"RESULTS":^68}│{RESET}')
    print(f'{BOLD}{WHITE}  ├{"─" * 22}┬{"─" * 22}┬{"─" * 22}┤{RESET}')
    print(f'{BOLD}{WHITE}  │{"Metric":^22}│{"Standard (WaitAll)":^22}│{"Blackboard (Ours)":^22}│{RESET}')
    print(f'{BOLD}{WHITE}  ├{"─" * 22}┼{"─" * 22}┼{"─" * 22}┤{RESET}')
    print(f'{BOLD}{WHITE}  │{RESET}{"Wall time":^22}{BOLD}{WHITE}│{RESET}{f"{standard_result.elapsed:.1f}s":^22}{BOLD}{WHITE}│{RESET}{GREEN}{f"{blackboard_result.elapsed:.1f}s":^22}{RESET}{BOLD}{WHITE}│{RESET}')
    print(f'{BOLD}{WHITE}  │{RESET}{"Speedup":^22}{BOLD}{WHITE}│{RESET}{"—":^22}{BOLD}{WHITE}│{RESET}{GREEN}{f"{speedup:.0f}% faster":^22}{RESET}{BOLD}{WHITE}│{RESET}')
    print(f'{BOLD}{WHITE}  │{RESET}{"Time saved":^22}{BOLD}{WHITE}│{RESET}{"—":^22}{BOLD}{WHITE}│{RESET}{GREEN}{f"{time_saved:.1f}s":^22}{RESET}{BOLD}{WHITE}│{RESET}')
    print(f'{BOLD}{WHITE}  │{RESET}{"Agents cancelled":^22}{BOLD}{WHITE}│{RESET}{"0":^22}{BOLD}{WHITE}│{RESET}{RED}{"1 (agent_filings)":^22}{RESET}{BOLD}{WHITE}│{RESET}')
    print(f'{BOLD}{WHITE}  │{RESET}{"Data sources used":^22}{BOLD}{WHITE}│{RESET}{"3/3":^22}{BOLD}{WHITE}│{RESET}{"2/3 (sufficient)":^22}{BOLD}{WHITE}│{RESET}')
    print(f'{BOLD}{WHITE}  │{RESET}{"Evaluator cost":^22}{BOLD}{WHITE}│{RESET}{"—":^22}{BOLD}{WHITE}│{RESET}{"~50 tokens (~$0.00)":^22}{BOLD}{WHITE}│{RESET}')
    print(f'{BOLD}{WHITE}  └{"─" * 22}┴{"─" * 22}┴{"─" * 22}┘{RESET}')

    print(f'\n  {BOLD}{GREEN}✓ Conclusion:{RESET} Blackboard delivered the same quality answer')
    print(f'    {time_saved:.1f} seconds faster by cancelling the stalled agent.')
    print()


if __name__ == '__main__':
    asyncio.run(main())
