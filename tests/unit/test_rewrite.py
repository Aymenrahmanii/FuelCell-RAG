"""Follow-up rewriting: history formatting, output cleaning, fallbacks."""

from collections.abc import Iterator

from fcrag.generation.rewrite import MAX_TURNS, Turn, clean, format_history, rewrite
from fcrag.llm.client import Message

PROMPT = {"system": "Rewrite.", "user": "{history}\nLast question: {question}"}
QUESTION = "And for System C?"


class Replies:
    def __init__(self, *outputs: str | Exception) -> None:
        self.outputs = list(outputs)
        self.model = "fake/replies"
        self.calls: list[list[Message]] = []

    def stream(self, messages: list[Message]) -> Iterator[str]:
        self.calls.append(messages)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        yield output


HISTORY: list[Turn] = [
    {"role": "user", "content": "What is the maximum coolant outlet temperature of System B?"},
    {"role": "assistant", "content": "It is 90 °C [S1], short-term [S2]."},
]


def test_history_keeps_recent_turns_without_citations() -> None:
    long: list[Turn] = [{"role": "user", "content": f"question {n}"} for n in range(10)]
    text = format_history([*long, {"role": "assistant", "content": "x" * 2000}])
    assert text.count("\n") == MAX_TURNS - 1 and "question 4" not in text
    assert text.endswith(" …") and "Assistant: " in text
    assert format_history(HISTORY).endswith("Assistant: It is 90 °C, short-term.")


def test_clean_takes_the_question_line() -> None:
    assert clean('"What is X of System C?"\n', QUESTION) == "What is X of System C?"
    assert clean("Standalone question: What is X?", QUESTION) == "What is X?"
    assert clean("   \n", QUESTION) == QUESTION
    assert clean("word " * 200, QUESTION) == QUESTION  # an answer, not a question


def test_rewrite_resolves_the_follow_up() -> None:
    llm = Replies("What is the maximum coolant outlet temperature of System C?")
    result = rewrite(llm, QUESTION, HISTORY, PROMPT)
    assert result == "What is the maximum coolant outlet temperature of System C?"
    assert "System B" in llm.calls[0][1]["content"] and QUESTION in llm.calls[0][1]["content"]


def test_no_history_means_no_call_and_failures_fall_back() -> None:
    llm = Replies()
    assert rewrite(llm, QUESTION, [], PROMPT) == QUESTION and llm.calls == []
    assert rewrite(Replies(RuntimeError("rate limit")), QUESTION, HISTORY, PROMPT) == QUESTION
