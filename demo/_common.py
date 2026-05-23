"""Shared utilities for demo scripts — formatted output, timing, and runner."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from dataclasses import field

from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow
from google.genai.types import Content
from google.genai.types import Part


# ─── Terminal formatting ───────────────────────────────────────────────────────

RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'
GREEN = '\033[32m'
RED = '\033[31m'
YELLOW = '\033[33m'
CYAN = '\033[36m'
MAGENTA = '\033[35m'
WHITE = '\033[97m'
BG_GREEN = '\033[42m'
BG_RED = '\033[41m'
BG_YELLOW = '\033[43m'
BG_CYAN = '\033[46m'


def header(text: str) -> str:
    return f'\n{BOLD}{CYAN}{"═" * 70}{RESET}\n{BOLD}{WHITE}  {text}{RESET}\n{BOLD}{CYAN}{"═" * 70}{RESET}\n'


def subheader(text: str) -> str:
    return f'\n{BOLD}{MAGENTA}  ─── {text} ───{RESET}\n'


def status_running(name: str) -> str:
    return f'  {YELLOW}⟳{RESET} {DIM}{name}{RESET} running...'


def status_done(name: str, elapsed: float) -> str:
    return f'  {GREEN}✓{RESET} {name} {DIM}({elapsed:.1f}s){RESET}'


def status_cancelled(name: str, elapsed: float) -> str:
    return f'  {RED}✗{RESET} {name} {DIM}(cancelled at {elapsed:.1f}s){RESET}'


def status_evaluator(sufficient: bool, reasoning: str) -> str:
    icon = f'{BG_GREEN}{BOLD} YES {RESET}' if sufficient else f'{BG_RED}{BOLD} NO {RESET}'
    return f'  {CYAN}🧠{RESET} Evaluator → {icon} {DIM}{reasoning[:80]}{RESET}'


def status_reconciliation(action: str, severity: str, reasoning: str) -> str:
    if action == 'merge':
        icon = f'{BG_GREEN}{BOLD} MERGE {RESET}'
    else:
        icon = f'{BG_RED}{BOLD} CONTRADICT {RESET}'
    return f'  {MAGENTA}🔄{RESET} Reconciler → {icon} severity={severity} {DIM}{reasoning[:70]}{RESET}'


def metric_row(label: str, standard: str, blackboard: str) -> str:
    return f'  {label:<24} {standard:<28} {blackboard}'


def metrics_table(
    standard_time: float | None,
    blackboard_time: float,
    cancelled_count: int,
) -> str:
    lines = []
    lines.append(f'\n{BOLD}{WHITE}  ┌{"─" * 68}┐{RESET}')
    lines.append(f'{BOLD}{WHITE}  │{"METRICS":^68}│{RESET}')
    lines.append(f'{BOLD}{WHITE}  ├{"─" * 22}┬{"─" * 22}┬{"─" * 22}┤{RESET}')
    lines.append(f'{BOLD}{WHITE}  │{"Metric":^22}│{"Standard (WaitAll)":^22}│{"Blackboard (Ours)":^22}│{RESET}')
    lines.append(f'{BOLD}{WHITE}  ├{"─" * 22}┼{"─" * 22}┼{"─" * 22}┤{RESET}')

    std_time_str = f'{standard_time:.1f}s' if standard_time else '—'
    bb_time_str = f'{blackboard_time:.1f}s'
    if standard_time:
        pct = (1 - blackboard_time / standard_time) * 100
        bb_time_str += f' ({pct:.0f}% faster)'

    lines.append(f'{BOLD}{WHITE}  │{RESET}{"Time to result":^22}{BOLD}{WHITE}│{RESET}{std_time_str:^22}{BOLD}{WHITE}│{RESET}{GREEN}{bb_time_str:^22}{RESET}{BOLD}{WHITE}│{RESET}')
    lines.append(f'{BOLD}{WHITE}  │{RESET}{"Agents cancelled":^22}{BOLD}{WHITE}│{RESET}{"0":^22}{BOLD}{WHITE}│{RESET}{RED}{str(cancelled_count):^22}{RESET}{BOLD}{WHITE}│{RESET}')
    lines.append(f'{BOLD}{WHITE}  │{RESET}{"Evaluator overhead":^22}{BOLD}{WHITE}│{RESET}{"—":^22}{BOLD}{WHITE}│{RESET}{"~0.5s, ~50 tokens":^22}{BOLD}{WHITE}│{RESET}')
    lines.append(f'{BOLD}{WHITE}  └{"─" * 22}┴{"─" * 22}┴{"─" * 22}┘{RESET}')
    return '\n'.join(lines)


# ─── Runner helper ─────────────────────────────────────────────────────────────


@dataclass
class DemoResult:
    """Captures the output of a single workflow run."""
    workflow_name: str
    elapsed: float = 0.0
    final_output: str = ''
    synthesizer_outputs: list[tuple[float, str]] = field(default_factory=list)
    reconciliation_action: str = ''
    reconciliation_severity: str = ''
    reconciliation_reasoning: str = ''
    events_log: list[str] = field(default_factory=list)
    cancelled_count: int = 0


async def run_workflow(
    workflow: Workflow,
    user_message: str,
    *,
    log_events: bool = True,
) -> DemoResult:
    """Run a workflow end-to-end and capture results + timing."""
    session_service = InMemorySessionService()
    runner = Runner(
        agent=workflow,
        app_name='demo',
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name='demo',
        user_id='demo_user',
    )

    user_content = Content(
        role='user',
        parts=[Part(text=user_message)],
    )

    result = DemoResult(workflow_name=workflow.name)
    start = time.perf_counter()

    async for event in runner.run_async(
        user_id='demo_user',
        session_id=session.id,
        new_message=user_content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    entry = f'[{event.author}] {part.text}'
                    result.events_log.append(entry)

                    # Detect evaluator output
                    if 'SufficientJoin' in part.text:
                        sufficient = 'sufficient=True' in part.text
                        reason = part.text.split('reason:')[-1].strip() if 'reason:' in part.text else ''
                        if log_events:
                            print(status_evaluator(sufficient, reason))

                    # Detect reconciliation output
                    if 'Reconciliation' in part.text and 'action=' in part.text:
                        action = 'merge' if 'action=merge' in part.text else 'contradict'
                        severity = 'low'
                        for s in ('low', 'medium', 'high'):
                            if f'severity={s}' in part.text:
                                severity = s
                                break
                        reason = part.text.split('reason:')[-1].strip() if 'reason:' in part.text else ''
                        result.reconciliation_action = action
                        result.reconciliation_severity = severity
                        result.reconciliation_reasoning = reason
                        if log_events:
                            print(status_reconciliation(action, severity, reason))

                    # Detect synthesizer output (may fire multiple times in pessimistic)
                    if event.author == 'synthesizer':
                        elapsed_now = time.perf_counter() - start
                        result.synthesizer_outputs.append((elapsed_now, part.text))
                        result.final_output = part.text

    result.elapsed = time.perf_counter() - start

    # Check for cancellations in the log
    for entry in result.events_log:
        if 'cancelling' in entry.lower():
            # Parse count from "cancelling N leftover tasks"
            import re
            m = re.search(r'cancelling (\d+)', entry.lower())
            if m:
                result.cancelled_count = int(m.group(1))

    return result
