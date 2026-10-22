"""Transient model errors are retried inside the turn and shown to the chat."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402
import retry  # noqa: E402
import runner  # noqa: E402

# what the gateway sent inside a 200 stream (2026-10-22)
OVERLOADED = ("ResponseError(code='server_error', message='Our servers are currently overloaded. Please try again "
              "later.', misalignment=None, type='service_unavailable_error', param=None, headers={'retry-after': '6', "
              "'retry-after-ms': '6000'})")


class _Status(Exception):
    def __init__(self, status):
        super().__init__(f"Error code: {status}")
        self.status_code = status


def test_transient_and_retry_after():
    assert retry.transient(ValueError(OVERLOADED))
    assert retry.retry_after(ValueError(OVERLOADED)) == 6.0
    assert retry.transient(_Status(529)) and retry.transient(_Status(429))
    assert not retry.transient(_Status(404))           # unknown model: retrying will not help
    assert not retry.transient(_Status(400))
    assert not retry.transient(ValueError("context_length_exceeded"))
    assert retry.retry_after(ValueError("nothing here")) is None
    assert 2 <= retry.delay_s(1, ValueError("x")) <= 2.5
    assert retry.delay_s(1, ValueError(OVERLOADED)) >= 6


class Flaky(BaseChatModel):
    fails: int = 1
    calls: int = 0
    error: str = OVERLOADED

    @property
    def _llm_type(self) -> str:
        return "flaky"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls <= self.fails:
            raise ValueError(self.error)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="SPY closed at 500."))])

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def no_tools_no_wait(monkeypatch):
    @asynccontextmanager
    async def tools(as_of):
        yield []

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(agent, "get_tools", tools)
    monkeypatch.setattr(retry.asyncio, "sleep", no_sleep)


async def _events(llm):
    msgs = [SystemMessage("You are a test."), HumanMessage("SPY?")]
    return [ev async for ev in agent.run_agent_stream(llm, msgs)]


@pytest.mark.asyncio
async def test_overloaded_model_call_is_retried(no_tools_no_wait):
    llm = Flaky(fails=2)
    evs = await _events(llm)
    kinds = [e["type"] for e in evs]
    assert llm.calls == 3
    assert [e["attempt"] for e in evs if e["type"] == "retry"] == [1, 2]
    assert kinds[-1] == "step_end" and evs[-1]["text"] == "SPY closed at 500."
    # the turn record keeps one step, with the retries it needed
    record = {"steps": [], "content": "", "usage": None}
    for ev in evs:
        runner._apply(record, ev, {})
    assert len(record["steps"]) == 1
    assert record["steps"][0]["retries"] == 2 and "retry" not in record["steps"][0]


@pytest.mark.asyncio
async def test_permanent_errors_and_exhausted_retries_raise(no_tools_no_wait, monkeypatch):
    with pytest.raises(ValueError, match="model not found"):
        await _events(Flaky(fails=5, error="model not found"))
    monkeypatch.setattr(retry, "MAX_RETRIES", 1)
    llm = Flaky(fails=5)
    with pytest.raises(ValueError, match="overloaded"):
        await _events(llm)
    assert llm.calls == 2


def test_restarted_step_drops_partial_text():
    record = {"steps": [], "content": "", "usage": None}
    for ev in ({"type": "step_start", "t": 1}, {"type": "llm_chunk", "content": "half an ans"},
               {"type": "retry", "attempt": 1, "of": 4, "delay_s": 6.0, "error": "overloaded", "t": 2},
               {"type": "step_start", "t": 3}, {"type": "llm_chunk", "content": "Whole answer."},
               {"type": "step_end", "t": 4, "text": "Whole answer.", "tool_calls": [], "usage": None}):
        out = runner._apply(record, ev, {})
    assert out["step"] == 0
    assert record["steps"] == [{"text": "Whole answer.", "tool_calls": [], "started_at": 3, "ended_at": 4,
                                "usage": None, "retries": 1}]
