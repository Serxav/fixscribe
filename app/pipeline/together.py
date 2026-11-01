"""Work on several steps at the same time, because most of a step's time is waiting for Meta."""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor


def in_parallel[T, R](items: Iterable[T], work: Callable[[T], R], workers: int) -> list[R]:
    """Run ``work`` on every item and return the answers in the items' order.

    ``work`` handles its own errors: one exception that gets out here stops the stage.
    """
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(work, items))
