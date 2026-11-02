import re
from collections.abc import Sequence
from typing import Protocol


class SpokenTurn(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def content(self) -> str: ...


def normalized_speech(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def require_spoken_confirmation(
    turns: Sequence[SpokenTurn], readback: str, action: str = "confirm these requirements"
) -> None:
    if len(turns) < 2 or turns[-1].role != "user":
        raise ValueError("Read back the current requirements and wait for the caller's answer")
    accepted = {
        "yes",
        "yes please",
        "yes that is correct",
        "yes thats correct",
        "yes that s correct",
        "yes correct",
        "confirm",
        "confirmed",
        "i confirm",
        "yes i confirm",
        f"yes {action}",
    }
    if normalized_speech(turns[-1].content) not in accepted:
        raise ValueError("A clear yes or confirm after the full readback is required")
    agent_turns: list[str] = []
    for turn in reversed(turns[:-1]):
        if turn.role != "agent":
            break
        agent_turns.insert(0, turn.content)
    if not normalized_speech(" ".join(agent_turns)).endswith(
        normalized_speech(readback)
    ):
        raise ValueError("Read the complete current requirements before asking for confirmation")

