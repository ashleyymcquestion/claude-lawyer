"""One agent loop that every team member runs on."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic

from . import config

ToolHandler = Callable[[dict[str, Any]], str]


@dataclass
class Agent:
    name: str
    system: str
    effort: str = "high"
    # Client tools: name -> (definition, handler). Server tools go in server_tools.
    tools: dict[str, tuple[dict[str, Any], ToolHandler]] = field(default_factory=dict)
    server_tools: list[dict[str, Any]] = field(default_factory=list)
    max_turns: int = 30


class AgentError(RuntimeError):
    pass


def run_agent(
    agent: Agent,
    prompt: str | list[dict[str, Any]],
    client: anthropic.Anthropic | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> str:
    """Run the agent until it stops calling tools, and return its final text."""
    client = client or anthropic.Anthropic()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_defs = [d for d, _ in agent.tools.values()] + agent.server_tools

    for _ in range(agent.max_turns):
        with client.beta.messages.stream(
            model=config.MODEL,
            max_tokens=64000,
            system=agent.system,
            messages=messages,
            tools=tool_defs,
            output_config={"effort": agent.effort},
            cache_control={"type": "ephemeral"},
            betas=[config.FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise AgentError(f"{agent.name} declined the request.")

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason != "tool_use":
            if response.stop_reason == "max_tokens":
                log(f"[{agent.name}] warning: answer was cut off at max_tokens")
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            log(f"[{agent.name}] -> {block.name}")
            results.append(_call_tool(agent, block))
        messages.append({"role": "user", "content": results})

    raise AgentError(f"{agent.name} did not finish within {agent.max_turns} turns.")


def _call_tool(agent: Agent, block: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id}
    entry = agent.tools.get(block.name)
    if entry is None:
        return result | {"content": f"Unknown tool {block.name!r}.", "is_error": True}
    tool_input = block.input
    if isinstance(tool_input, str):
        tool_input = json.loads(tool_input)
    try:
        return result | {"content": entry[1](tool_input)}
    except Exception as exc:  # report the failure to the model instead of crashing
        return result | {"content": f"Tool failed: {exc}", "is_error": True}
