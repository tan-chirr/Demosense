import asyncio
import sys


def use_selector_event_loop_on_windows() -> None:
    """psycopg3's async mode requires SelectorEventLoop; Windows defaults to
    ProactorEventLoop. Call this before any asyncio.run() in an entrypoint.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
