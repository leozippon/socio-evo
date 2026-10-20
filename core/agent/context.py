"""Priority packing and a final guard on every enabled call, including repair attempts."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from core.agent.config import ContextBudgetConfig
from infrastructure.llm.base import LLMCallError, LLMClient, LLMRequest, LLMResponse, Message


class ContextOverflow(LLMCallError):
    """Required material cannot fit; never silently drop the task or reply contract."""


@lru_cache(maxsize=4)
def _tokenizer(path: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)


class Counter:
    def __init__(self, config: ContextBudgetConfig):
        self.tokenizer = _tokenizer(config.tokenizer_path) if config.tokenizer_path else None
        self.method = "local-tokenizer" if self.tokenizer else "utf8-byte-estimate"

    def text(self, value: str) -> int:
        if self.tokenizer is not None:
            return len(self.tokenizer.encode(value, add_special_tokens=False))
        return len(value.encode("utf-8"))

    def _chat_tokens(self, messages: list[dict]) -> int:
        encoded = self.tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True
        )
        # Transformers may return BatchEncoding rather than a flat token list.
        return len(encoded["input_ids"] if isinstance(encoded, Mapping) else encoded)

    def request(self, request: LLMRequest) -> int:
        messages = [m.model_dump() for m in request.messages]
        if self.tokenizer is not None:
            size = self._chat_tokens(messages)
            reasoning = sum(self.text(m.reasoning_content or "") for m in request.messages)
            if reasoning:
                # Some chat templates omit reasoning history; count it regardless, while
                # avoiding a second charge when the template already includes it.
                plain = [{k: v for k, v in m.items() if k != "reasoning_content"} for m in messages]
                baseline = self._chat_tokens(plain)
                size = max(size, baseline + reasoning)
        else:
            size = (
                sum(
                    self.text(m.content) + self.text(m.reasoning_content or "") + 16
                    for m in request.messages
                )
                + 16
            )
        # Account for the response schema even when the backend enforces it out-of-band.
        if request.json_schema is not None:
            size += self.text(json.dumps(request.json_schema, ensure_ascii=False))
        return size

    def clip(self, text: str, allowance: int) -> str:
        if self.text(text) <= allowance:
            return text
        marker = "\n[excerpt shortened]"
        if allowance < self.text(marker) + 16:
            return ""
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            # Keep both the start (command/context) and end (exit/error) of evidence.
            head = (mid + 1) // 2
            tail = mid // 2
            sample = text[:head] + marker + (text[-tail:] if tail else "")
            if self.text(sample) <= allowance:
                low = mid
            else:
                high = mid - 1
        head, tail = (low + 1) // 2, low // 2
        return text[:head] + marker + (text[-tail:] if tail else "")


def input_limit(config: ContextBudgetConfig, request: LLMRequest) -> int:
    output = request.sampling.max_tokens or config.output_tokens
    return min(config.input_tokens, config.context_tokens - output - config.safety_tokens)


@dataclass(frozen=True)
class Block:
    source: str
    text: str
    priority: int


class BudgetPrompt(str):
    """A mandatory prompt plus separately budgeted evidence; ordinary callers see a str."""

    def __new__(cls, text: str, blocks: list[Block]):
        value = super().__new__(cls, text)
        value.blocks = blocks
        return value


def pack(request: LLMRequest, blocks: list[Block], config: ContextBudgetConfig) -> LLMRequest:
    """Request contains mandatory identity/situation/format; allocate the rest by priority.

    Render selected blocks in original chronological order. Do not modify stored memories.
    """
    counter = Counter(config)
    limit = input_limit(config, request)
    if counter.request(request) > limit:
        raise ContextOverflow("Required task/identity/reply format exceeds input budget")
    chosen: dict[int, str] = {}

    def assemble() -> LLMRequest:
        context = "\n\n".join(chosen[i] for i in sorted(chosen))
        user = request.messages[-1].content
        if context:
            user = context + "\n\n" + user
        return request.model_copy(
            update={"messages": (*request.messages[:-1], Message(role="user", content=user))}
        )

    ordered = sorted(range(len(blocks)), key=lambda i: (-blocks[i].priority, -i))
    critical = [i for i in ordered if blocks[i].priority >= 75]
    # Give current evidence and requested recollections a small shared foothold first.
    # Otherwise one verbose traceback could consume every byte and hide the answer to a
    # just-issued memory query. These are floors, not fixed category partitions.
    floor = min(192, max(0, (limit - counter.request(request)) // max(1, len(critical)) - 16))
    for i in critical:
        text = counter.clip(blocks[i].text, floor)
        if text:
            chosen[i] = text
            if counter.request(assemble()) > limit:
                chosen.pop(i)
    report = []
    for i in ordered:
        block = blocks[i]
        previous = chosen.pop(i, None)
        remaining = limit - counter.request(assemble()) - 16
        text = counter.clip(block.text, max(0, remaining))
        if text:
            chosen[i] = text
            # Full-message tokenization can differ at boundaries; verify the actual request.
            while counter.request(assemble()) > limit:
                text = counter.clip(text, max(0, counter.text(text) - 32))
                if not text:
                    chosen.pop(i)
                    break
                chosen[i] = text
        if i not in chosen and previous is not None:
            chosen[i] = previous
        report.append(
            {
                "source": block.source,
                "priority": block.priority,
                "status": "kept"
                if chosen.get(i) == block.text
                else "shortened"
                if i in chosen
                else "omitted",
            }
        )
    result = assemble()
    return result.model_copy(
        update={
            "metadata": {
                **result.metadata,
                "context_budget": {
                    "method": counter.method,
                    "input_limit": limit,
                    "input_count": counter.request(result),
                    "blocks": report,
                },
            }
        }
    )


class BudgetClient:
    """Enforce the same ceiling after structured-output retries add correction messages."""

    def __init__(self, client: LLMClient, config: ContextBudgetConfig):
        self.client, self.config = client, config

    async def complete(self, request: LLMRequest) -> LLMResponse:
        counter = Counter(self.config)
        if request.sampling.max_tokens is None:
            request = request.model_copy(
                update={
                    "sampling": request.sampling.model_copy(
                        update={"max_tokens": self.config.output_tokens}
                    )
                }
            )
        limit = input_limit(self.config, request)
        messages = list(request.messages)
        # Repair messages are disposable; the packed original request is not. Keep the
        # latest correction if possible, never a dangling old assistant reply.
        while counter.request(request) > limit and len(messages) > 2:
            if len(messages) >= 4:
                del messages[2:4]
            else:
                messages.pop()
            request = request.model_copy(update={"messages": tuple(messages)})
        count = counter.request(request)
        if count > limit:
            raise ContextOverflow(f"Input budget exceeded: {count} > {limit} ({counter.method})")
        request = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "context_usage": {
                        "method": counter.method,
                        "input_count": count,
                        "input_limit": limit,
                        "output_reserve": request.sampling.max_tokens,
                    },
                }
            }
        )
        return await self.client.complete(request)
