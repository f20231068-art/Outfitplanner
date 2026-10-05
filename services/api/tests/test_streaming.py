"""A reply that takes a minute must not look like a dead connection: the stream sends keep-alives while it works."""

import threading
import time

import pytest

from api.routes.chat import BEAT, KEEP_ALIVE, stream_with_heartbeat


def slow(items, pause):
    def make():
        for item in items:
            time.sleep(pause)
            yield item

    return make


def test_items_arrive_in_order_with_beats_while_nothing_is_ready():
    finished = threading.Event()
    got = list(stream_with_heartbeat(slow(["a", "b"], 0.12), finished.set, interval=0.03))
    assert [g for g in got if g is not BEAT] == ["a", "b"]
    assert got.count(BEAT) >= 3  # it was quiet for 0.12 s before each item, with a beat every 0.03 s
    assert finished.is_set()


def test_a_fast_stream_has_no_beats():
    got = list(stream_with_heartbeat(lambda: iter([1, 2, 3]), lambda: None, interval=5))
    assert got == [1, 2, 3]


def test_a_failure_in_the_work_reaches_the_consumer_and_still_frees_the_conversation():
    freed = []

    def boom():
        yield "first"
        raise RuntimeError("model exploded")

    stream = stream_with_heartbeat(boom, lambda: freed.append(1), interval=5)
    assert next(stream) == "first"
    with pytest.raises(RuntimeError, match="model exploded"):
        next(stream)
    assert freed == [1]


def test_the_conversation_stays_busy_until_the_work_really_ends_even_if_the_browser_leaves():
    release_work, freed = threading.Event(), threading.Event()

    def long_work():
        release_work.wait(5)  # the agent is still thinking
        yield "late"

    stream = stream_with_heartbeat(long_work, freed.set, interval=0.02)
    assert next(stream) is BEAT
    stream.close()  # the browser disconnected
    assert not freed.is_set()  # the agent is still working, so a second message must still be refused
    release_work.set()
    assert freed.wait(2)  # and it is freed the moment the work finishes


def test_the_keep_alive_is_an_sse_comment_that_the_stream_parsers_skip():
    assert KEEP_ALIVE.startswith(":") and KEEP_ALIVE.endswith("\n\n")
    assert "event:" not in KEEP_ALIVE and "data:" not in KEEP_ALIVE  # the web and Mastra parsers need one of these
