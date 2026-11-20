"""Cancellation boundary shared by model requests and their retries."""

from typing import Callable, TypeVar


_Response = TypeVar("_Response")


class GenerationCancelled(RuntimeError):
    """A stopped task is not a provider failure or an invalid model response."""


def run_cancellable_model_request(
    request: Callable[[], _Response], check_cancelled: Callable[[], None] | None = None,
) -> _Response:
    if check_cancelled:
        check_cancelled()
    try:
        return request()
    finally:
        if check_cancelled:
            check_cancelled()
