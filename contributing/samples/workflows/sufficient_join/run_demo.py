"""Quick script to run the blackboard_workflow end-to-end and print events."""

import asyncio
import sys
import time
from pathlib import Path

# Ensure the sample directory is on sys.path for direct script execution.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from google.adk import Runner
from google.adk.sessions import InMemorySessionService

from agent_standalone import blackboard_workflow


async def main():
    session_service = InMemorySessionService()
    runner = Runner(
        agent=blackboard_workflow,
        app_name='sufficient_join_demo',
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name='sufficient_join_demo',
        user_id='demo_user',
    )

    from google.genai.types import Content, Part

    user_msg = Content(
        role='user',
        parts=[Part(text="Why is Acme Corp's stock dropping?")],
    )

    start = time.perf_counter()
    print('--- Running blackboard_workflow ---')
    print(f'User: Why is Acme Corp\'s stock dropping?\n')

    async for event in runner.run_async(
        user_id='demo_user',
        session_id=session.id,
        new_message=user_msg,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f'[{event.author}] {part.text[:200]}')

    elapsed = time.perf_counter() - start
    print(f'\n--- Done in {elapsed:.1f}s ---')


if __name__ == '__main__':
    asyncio.run(main())
