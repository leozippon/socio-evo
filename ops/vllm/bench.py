"""Throughput probes for the served endpoint (VLLM_API_KEY from the environment).

Usage: bench.py BASE_URL MODEL load CONCURRENCY [TOTAL]   (~6k-token agentic prompts, 1024 output tokens)
       bench.py BASE_URL MODEL long PROMPT_KTOKENS         (needle question over a long prompt)
       bench.py BASE_URL MODEL multiturn SESSIONS TURNS [DP] (growing agent sessions; DP pins session -> rank)
"""
import asyncio
import os
import random
import statistics
import sys
import time

from openai import AsyncOpenAI

base_url, model, mode = sys.argv[1], sys.argv[2], sys.argv[3]
RUN = random.SystemRandom().randrange(10**9)  # fresh prompts per run, so no run reuses another's prefix cache
client = AsyncOpenAI(base_url=base_url, api_key=os.environ["VLLM_API_KEY"], timeout=3600, max_retries=0)

NAMES = ["Ada", "Bo", "Chen", "Dara", "Eli", "Femi", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lena"]
PLACES = ["market", "workshop", "town hall", "bakery", "dock", "library", "clinic", "farm"]
VERBS = ["offered", "refused", "promised", "delivered", "borrowed", "repaid", "reported", "negotiated"]
ITEMS = ["grain", "tools", "a loan", "fish", "medicine", "lumber", "a contract", "wool"]
TOOLS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {"target": {"type": "string"}, "detail": {"type": "string"}},
    "required": ["target"]}}} for n, d in [
    ("send_message", "Send a private message to another resident."),
    ("make_offer", "Propose a trade or contract to another resident."),
    ("accept_offer", "Accept a pending offer by id."),
    ("move_to", "Walk to a named place in town."),
    ("write_note", "Write a private note to your own memory."),
]]


def history(rng, approx_tokens):
    lines, n = [], 0
    while n < approx_tokens:
        a, b = rng.sample(NAMES, 2)
        line = (f"[day {rng.randint(1, 90)} {rng.randint(6, 21):02d}:{rng.randint(0, 59):02d}] At the "
                f"{rng.choice(PLACES)}, {a} {rng.choice(VERBS)} {rng.choice(ITEMS)} to {b} for "
                f"{rng.randint(2, 400)} coins; {b} said the reputation ledger shows {rng.randint(0, 100)} "
                f"kept promises out of {rng.randint(100, 200)}.")
        lines.append(line)
        n += len(line) // 4 + 2
    return "\n".join(lines)


def agentic_messages(seed):
    rng = random.Random(seed)
    me = rng.choice(NAMES)
    system = (f"Session {seed}. You are {me}, a resident of a small trading town. You earn a living by working, "
              "trading and cooperating with other residents. Decide your next action using the tools. "
              "Think about your long-term reputation and your current needs.")
    obs = history(rng, 4100)
    user = (f"Recent events you observed:\n{obs}\n\nIt is now morning. You have 120 coins and need lumber "
            "to finish a commission. Decide what to do next and explain your reasoning before acting.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def one(messages, max_tokens, headers=None, **extra):
    t0 = time.perf_counter()
    ttft, usage, text = None, None, []
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, stream=True,
        stream_options={"include_usage": True}, extra_headers=headers, **extra)
    async for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if chunk.choices:
            d = chunk.choices[0].delta
            piece = d.content or (d.model_extra or {}).get("reasoning") or (d.tool_calls and "tool")
            if piece and ttft is None:
                ttft = time.perf_counter() - t0
            if d.content:
                text.append(d.content)
    details = usage.prompt_tokens_details
    return {"ttft": ttft, "latency": time.perf_counter() - t0, "prompt": usage.prompt_tokens,
            "cached": details.cached_tokens if details else 0,
            "output": usage.completion_tokens, "text": "".join(text)}


async def load(concurrency, total):
    queue = [RUN * 1000 + i for i in range(total)]
    results = []

    async def worker():
        while queue:
            seed = queue.pop()
            results.append(await one(agentic_messages(seed), 1024, tools=TOOLS, reasoning_effort="low",
                                     extra_body={"ignore_eos": True}))

    t0 = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    wall = time.perf_counter() - t0
    out = sum(r["output"] for r in results)
    lat = sorted(r["latency"] for r in results)
    print(f"concurrency={concurrency} requests={total} wall={wall:.1f}s "
          f"mean_prompt_tokens={statistics.mean(r['prompt'] for r in results):.0f} "
          f"mean_output_tokens={out / total:.0f}")
    print(f"  aggregate output throughput = {out / wall:.0f} tok/s; "
          f"total (prompt+output) = {(out + sum(r['prompt'] for r in results)) / wall:.0f} tok/s")
    print(f"  TTFT mean={statistics.mean(r['ttft'] for r in results):.2f}s "
          f"max={max(r['ttft'] for r in results):.2f}s")
    print(f"  latency mean={statistics.mean(lat):.1f}s p50={lat[len(lat) // 2]:.1f}s "
          f"p90={lat[int(len(lat) * 0.9)]:.1f}s; per-request decode "
          f"{statistics.mean(r['output'] / (r['latency'] - r['ttft']) for r in results):.1f} tok/s")


async def long(ktokens):
    rng = random.Random(RUN)
    body = history(rng, int(ktokens * 750)).split("\n")
    body.insert(len(body) // 2, "[day 45 12:00] Note: the vault code agreed by the council is 4817.")
    msgs = [{"role": "user", "content": "\n".join(body) + "\n\nWhat vault code did the council agree on? "
             "Answer with the four digits only."}]
    r = await one(msgs, 512, reasoning_effort="low")
    print(f"long-context prompt_tokens={r['prompt']} TTFT={r['ttft']:.1f}s total_latency={r['latency']:.1f}s "
          f"output_tokens={r['output']} answer={r['text'].strip()!r} correct={'4817' in r['text']}")


async def multiturn(sessions, turns, dp):
    results = []

    async def session(i):
        rng = random.Random(RUN * 1000 + i)
        msgs = agentic_messages(RUN * 1000 + i)
        headers = {"X-data-parallel-rank": str(i % dp)} if dp else None
        for _ in range(turns):
            r = await one(msgs, 512, headers=headers, tools=TOOLS, reasoning_effort="low",
                          extra_body={"ignore_eos": True})
            results.append(r)
            msgs = msgs + [{"role": "assistant", "content": r["text"]},
                           {"role": "user", "content": "New events:\n" + history(rng, 300)}]

    t0 = time.perf_counter()
    await asyncio.gather(*(session(i) for i in range(sessions)))
    wall = time.perf_counter() - t0
    out = sum(r["output"] for r in results)
    print(f"multiturn sessions={sessions} turns={turns} pinned_dp={dp or 'no'} wall={wall:.1f}s "
          f"mean_prompt_tokens={statistics.mean(r['prompt'] for r in results):.0f} "
          f"prefix_cache_hit={sum(r['cached'] for r in results) / sum(r['prompt'] for r in results):.1%}")
    print(f"  aggregate output throughput = {out / wall:.0f} tok/s; "
          f"TTFT mean={statistics.mean(r['ttft'] for r in results):.2f}s; "
          f"latency mean={statistics.mean(r['latency'] for r in results):.1f}s")


if mode == "multiturn":
    asyncio.run(multiturn(int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]) if len(sys.argv) > 6 else 0))
elif mode == "load":
    c = int(sys.argv[4])
    asyncio.run(load(c, int(sys.argv[5]) if len(sys.argv) > 5 else 2 * c))
else:
    asyncio.run(long(int(sys.argv[4])))
