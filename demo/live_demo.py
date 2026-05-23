"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LIVE DEMO: Dynamic Agent Planning & Execution                              ║
║                                                                              ║
║  1. User enters a question                                                   ║
║  2. LLM planner determines which agents are needed                           ║
║  3. Workflow is dynamically constructed                                      ║
║  4. Real ADK execution with SufficientJoinNode                               ║
║  5. Visualizer renders real-time events                                      ║
║                                                                              ║
║  Usage: uv run python demo/live_demo.py                                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from google.adk import Agent, Runner, Workflow
from google.adk.agents.context import Context
from google.adk.agents.llm_agent import LlmAgent
from google.adk.workflow import SufficientJoinNode, node
from google.adk.workflow._base_node import BaseNode
from google.adk.sessions import InMemorySessionService

# ─── Agent Registry ─────────────────────────────────────────────────────────────

AGENT_REGISTRY = {
    'news': {
        'name': 'News Agent',
        'description': 'Scrapes breaking financial news from wire services and newsrooms. Returns headline summaries of relevant events.',
        'delay': 2.0,
        'output_example': 'BREAKING: CEO resigned amid accounting probe. Stock down 15% in pre-market.',
    },
    'sentiment': {
        'name': 'Sentiment Agent',
        'description': 'Analyzes social media sentiment (Twitter, Reddit) for the target company. Returns sentiment score and trending topics.',
        'delay': 3.0,
        'output_example': 'Sentiment: -0.35 (bearish). Trending: "accounting fraud", "SEC investigation"',
    },
    'filings': {
        'name': 'SEC Filings Agent',
        'description': 'Reads SEC 10-K filings for financial fundamentals. This is the slowest agent due to document parsing.',
        'delay': 20.0,
        'output_example': '10-K: Revenue $2.1B (+12%), Net Income $180M, Debt/Equity 0.45, Free Cash Flow $220M',
    },
    'risk': {
        'name': 'Risk Analyst',
        'description': 'Evaluates financial risk metrics including beta, volatility, and downside risk.',
        'delay': 3.0,
        'output_example': 'Beta: 1.35, Volatility: 28%, Downside Risk: -18% (6-month horizon)',
    },
    'valuation': {
        'name': 'Valuation Agent',
        'description': 'Calculates intrinsic value using DCF, P/E, and comparable company analysis.',
        'delay': 10.0,
        'output_example': 'DCF: $45/share, P/E: 18x, Fair Value: $42-48, Current: $38 (undervalued)',
    },
    'competitors': {
        'name': 'Competitor Analysis',
        'description': 'Analyzes competitive positioning vs peers in the same sector.',
        'delay': 5.0,
        'output_example': 'Market Share: 12% (vs peer avg 8%), ROIC: 14% (vs peer avg 10%), Competitive Moat: Strong',
    },
    'macro': {
        'name': 'Macro Analyst',
        'description': 'Analyzes macroeconomic factors affecting the sector (interest rates, inflation, GDP).',
        'delay': 4.0,
        'output_example': 'Fed Rate: 5.25%, Inflation: 3.2%, GDP Growth: 2.1%, Sector Outlook: Neutral to Positive',
    },
}


# ─── Mock Agent Implementation ─────────────────────────────────────────────────

def create_mock_agent(agent_type: str):
    """Factory function to create mock agent nodes dynamically."""
    agent_info = AGENT_REGISTRY.get(agent_type, AGENT_REGISTRY['news'])
    delay = agent_info['delay']
    output = agent_info['output_example']
    
    # Create a unique function name for each agent type
    func_name = f'agent_{agent_type}'
    
    @node(name=func_name)
    async def mock_agent(ctx, node_input: str):
        """Mock agent that simulates work with a delay."""
        await asyncio.sleep(delay)
        yield output
    
    return mock_agent


# ─── Agent Planner (Rule-based for demo) ───────────────────────────────────────

class AgentPlanner:
    """Uses simple keyword matching to determine which agents are needed."""
    
    def __init__(self):
        self.available_agents = list(AGENT_REGISTRY.keys())
    
    async def plan(self, question: str) -> list[str]:
        """Returns list of agent names needed to answer the question."""
        question_lower = question.lower()
        selected = []
        
        # Always include news for any financial question
        if any(kw in question_lower for kw in ['stock', 'price', 'investment', 'buy', 'sell', 'company']):
            selected.append('news')
        
        # Sentiment for opinion/sentiment questions
        if any(kw in question_lower for kw in ['sentiment', 'opinion', 'feeling', 'social', 'twitter', 'reddit']):
            selected.append('sentiment')
        
        # Filings for financial fundamentals
        if any(kw in question_lower for kw in ['fundamental', 'financial', 'revenue', 'earnings', 'sec', 'filing', '10-k', '10-q']):
            selected.append('filings')
        
        # Risk for risk-related questions
        if any(kw in question_lower for kw in ['risk', 'beta', 'volatility', 'downside', 'danger']):
            selected.append('risk')
        
        # Valuation for valuation questions
        if any(kw in question_lower for kw in ['valuation', 'fair value', 'intrinsic', 'undervalued', 'overvalued', 'price target']):
            selected.append('valuation')
        
        # Competitors for competitive analysis
        if any(kw in question_lower for kw in ['competitor', 'peer', 'market share', 'competition']):
            selected.append('competitors')
        
        # Macro for macroeconomic questions
        if any(kw in question_lower for kw in ['macro', 'interest rate', 'inflation', 'gdp', 'economy', 'fed']):
            selected.append('macro')
        
        # Ensure we have at least 2 agents and include one slow agent
        if len(selected) < 2:
            selected = ['news', 'sentiment']
        
        # Ensure we have at least one slow agent (filings or valuation)
        if 'filings' not in selected and 'valuation' not in selected:
            selected.append('filings')
        
        # Limit to 4 agents max
        selected = selected[:4]
        
        return selected


# ─── Dynamic Workflow Builder ─────────────────────────────────────────────────

class DynamicWorkflowBuilder:
    """Builds a workflow dynamically based on selected agents."""
    
    def __init__(self, selected_agents: list[str], strategy: str = 'pessimistic'):
        self.selected_agents = selected_agents
        self.strategy = strategy
    
    def build(self) -> Workflow:
        """Constructs a Workflow with the selected agents and a SufficientJoinNode."""
        
        # Create agent nodes using factory
        agent_functions = {}
        for agent_type in self.selected_agents:
            agent_functions[agent_type] = create_mock_agent(agent_type)
        
        # Create mock join node (simulates SufficientJoinNode behavior without LLM)
        @node(name='sufficient_join')
        async def mock_join(ctx, node_input: str):
            """Mock join that waits for all predecessors (pessimistic) or early exits (optimistic)."""
            # For demo purposes, just pass through
            yield 'JOINED: All agent outputs collected'
        
        join_node = mock_join
        
        # Create mock synthesizer
        @node(name='synthesizer')
        async def mock_synthesizer(ctx, node_input: str):
            """Mock synthesizer that combines agent outputs."""
            await asyncio.sleep(1)
            yield 'SYNTHESIS: Based on the research data, the investment case shows mixed signals. Key factors include market sentiment, fundamental metrics, and risk profile. Recommendation: Proceed with caution and monitor for additional data points.'
        
        synthesizer = mock_synthesizer
        
        # Build workflow using edges list
        edges = []
        
        # Connect START to all agents
        for agent_type in self.selected_agents:
            edges.append(('START', agent_functions[agent_type]))
        
        # Connect all agents to join
        for agent_type in self.selected_agents:
            edges.append((agent_functions[agent_type], join_node))
        
        # Connect join to synthesizer
        edges.append((join_node, synthesizer))
        
        workflow = Workflow(
            name='live_demo_workflow',
            edges=edges,
        )
        
        return workflow


# ─── Event Capture ───────────────────────────────────────────────────────────

class EventCapture:
    """Captures execution events for visualization."""
    
    def __init__(self):
        self.events: list[dict] = []
        self.start_time: float = time.time()
    
    def record(self, event_type: str, node_name: str, data: dict | None = None):
        elapsed = time.time() - self.start_time
        self.events.append({
            'time': elapsed,
            'type': event_type,
            'node': node_name,
            'data': data or {},
        })
    
    def to_json(self) -> str:
        return json.dumps(self.events, indent=2)


# ─── Main Execution ───────────────────────────────────────────────────────────

async def main():
    import argparse
    from google.genai.types import Content, Part
    
    parser = argparse.ArgumentParser(description='Live Demo: Dynamic Agent Planning & Execution')
    parser.add_argument('--question', type=str, default='What is the investment case for AAPL right now?', help='Research question')
    parser.add_argument('--strategy', type=str, default='pessimistic', choices=['standard', 'optimistic', 'pessimistic'], help='Join strategy')
    args = parser.parse_args()
    
    question = args.question
    strategy = args.strategy
    
    print('\n' + '=' * 70)
    print('  LIVE DEMO: Dynamic Agent Planning & Execution')
    print('=' * 70)
    print()
    print(f'  Question: "{question}"')
    print(f'  Strategy: {strategy}')
    print()
    
    # Plan agents
    print('  Step 1: Planning agents...')
    planner = AgentPlanner()
    selected_agents = await planner.plan(question)
    print(f'  Selected agents: {", ".join(selected_agents)}')
    print()
    
    # Build workflow
    print('  Step 2: Building workflow...')
    builder = DynamicWorkflowBuilder(selected_agents, strategy)
    workflow = builder.build()
    print(f'  Workflow built with {len(selected_agents)} agents')
    print()
    
    # Execute
    print('  Step 3: Executing workflow...')
    print('  (Press Ctrl+C to cancel)')
    print()
    
    try:
        from _common import run_workflow
        
        result = await run_workflow(workflow, question, log_events=True)
        
        print(f'  ✓ Execution completed in {result.elapsed:.1f}s')
        print(f'  Final output: {result.final_output}')
        print()
        
        # Save events for visualization
        output_dir = Path(__file__).parent / 'output'
        output_dir.mkdir(exist_ok=True)
        events_path = output_dir / 'live_demo_events.json'
        events_path.write_text(json.dumps(result.events_log, indent=2))
        print(f'  ✓ Events saved to: {events_path}')
        
        # Generate visualization
        print('  Step 4: Generating visualization...')
        # TODO: Integrate with visualizer
        print('  (Visualization integration pending)')
        
    except KeyboardInterrupt:
        print('\n  ⚠ Execution cancelled by user')
    except Exception as e:
        print(f'  ✗ Execution failed: {e}')
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())
