"""End-to-end feature check of the served endpoint.

Usage: verify.py BASE_URL MODEL   (VLLM_API_KEY from the environment; prints PASS/FAIL per feature)
"""
import json
import os
import sys
import time

from openai import OpenAI

base_url, model = sys.argv[1], sys.argv[2]
client = OpenAI(base_url=base_url, api_key=os.environ["VLLM_API_KEY"], timeout=900)
failures = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {detail}", flush=True)
    if not cond:
        failures.append(name)


def reasoning_of(msg):
    extra = msg.model_extra or {}
    return extra.get("reasoning") or extra.get("reasoning_content")


TOOLS = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "get_local_time",
        "description": "Get the current local time in a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
]
FAKE = {"get_weather": {"temp_c": 17, "sky": "light rain"}, "get_local_time": {"time": "21:42"}}

# 1. Plain chat completion.
r = client.chat.completions.create(model=model, reasoning_effort="low", max_tokens=4096,
    messages=[{"role": "user", "content": "What is 17 * 23? Reply with the number only."}])
m = r.choices[0].message
check("plain chat", "391" in (m.content or "") and r.choices[0].finish_reason == "stop",
      f"content={m.content!r} finish={r.choices[0].finish_reason} reasoning_chars={len(reasoning_of(m) or '')}")

# 2. Tool calling with two tools, parallel calls, results fed back.
msgs = [{"role": "user", "content": "I'm flying to Lisbon tonight. What's the weather there and what time is it there right now? Use the tools."}]
r = client.chat.completions.create(model=model, messages=msgs, tools=TOOLS, tool_choice="auto",
                                   reasoning_effort="low", max_tokens=4096)
m = r.choices[0].message
calls = m.tool_calls or []
names = sorted(c.function.name for c in calls)
args_ok = all(json.loads(c.function.arguments).get("city", "").lower() == "lisbon" for c in calls)
check("tool call (auto, parallel)", r.choices[0].finish_reason == "tool_calls" and names == ["get_local_time", "get_weather"] and args_ok,
      f"finish={r.choices[0].finish_reason} calls={[(c.function.name, c.function.arguments) for c in calls]}")
msgs.append({"role": "assistant", "content": m.content, "reasoning": reasoning_of(m),
             "tool_calls": [c.model_dump() for c in calls]})
for c in calls:
    msgs.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(FAKE[c.function.name])})
r = client.chat.completions.create(model=model, messages=msgs, tools=TOOLS, reasoning_effort="low", max_tokens=4096)
final = r.choices[0].message.content or ""
check("tool result fed back", "17" in final and "21:42" in final and not r.choices[0].message.tool_calls,
      f"final={final[:200]!r}")

r = client.chat.completions.create(model=model, tools=TOOLS, reasoning_effort="low", max_tokens=4096,
    tool_choice={"type": "function", "function": {"name": "get_weather"}},
    messages=[{"role": "user", "content": "Tell me something about Oslo."}])
calls = r.choices[0].message.tool_calls or []
check("named tool_choice", len(calls) >= 1 and all(c.function.name == "get_weather" for c in calls),
      f"calls={[(c.function.name, c.function.arguments) for c in calls]}")

r = client.chat.completions.create(model=model, tools=TOOLS, reasoning_effort="low", max_tokens=4096,
    tool_choice="required", messages=[{"role": "user", "content": "Hello there!"}])
calls = r.choices[0].message.tool_calls or []
check("tool_choice=required", len(calls) >= 1, f"calls={[(c.function.name, c.function.arguments) for c in calls]}")

# 3. reasoning_effort must reach the chat template, which adds an instruction for low and xhigh.
#    Reasoning length is printed for information only: on short puzzles sampling noise rivals the effect.
puzzle = ("How many ordered pairs (x, y) of positive integers satisfy x * y = 360 and gcd(x, y) = 1? "
          "Give the final number.")
stats = {}
for effort in ("low", "medium", "xhigh"):
    stats[effort] = []
    for _ in range(3 if effort != "xhigh" else 1):
        r = client.chat.completions.create(model=model, reasoning_effort=effort, max_tokens=32768,
                                           messages=[{"role": "user", "content": puzzle}])
        rc = reasoning_of(r.choices[0].message) or ""
        stats[effort].append((r.usage.prompt_tokens, len(rc), r.usage.completion_tokens))
        check(f"reasoning returned ({effort})", bool(rc) and "8" in (r.choices[0].message.content or ""),
              f"prompt_tokens={r.usage.prompt_tokens} reasoning_chars={len(rc)} completion_tokens={r.usage.completion_tokens}")
mean_chars = {k: sum(x[1] for x in v) / len(v) for k, v in stats.items()}
prompt = {k: v[0][0] for k, v in stats.items()}
check("reasoning_effort reaches template", prompt["low"] > prompt["medium"] and prompt["xhigh"] > prompt["medium"],
      f"prompt_tokens {prompt}")
print(f"[INFO] mean reasoning chars per effort: {mean_chars}")

# 4. Thinking disabled.
r = client.chat.completions.create(model=model, max_tokens=1024,
    messages=[{"role": "user", "content": "Name the capital of Japan in one word."}],
    extra_body={"chat_template_kwargs": {"enable_thinking": False}})
m = r.choices[0].message
check("enable_thinking=false", not reasoning_of(m) and "tokyo" in (m.content or "").lower(),
      f"content={m.content!r} reasoning={reasoning_of(m)!r} completion_tokens={r.usage.completion_tokens}")

# 5. Streaming with tool calls.
stream = client.chat.completions.create(model=model, stream=True, tools=TOOLS, reasoning_effort="low",
    max_tokens=4096, stream_options={"include_usage": True},
    messages=[{"role": "user", "content": "Check the weather in Nairobi and in Lima, please."}])
acc, reasoning_chunks, finish, t0, first = {}, 0, None, time.time(), None
for chunk in stream:
    if not chunk.choices:
        continue
    d = chunk.choices[0].delta
    if first is None and (d.content or (d.model_extra or {}).get("reasoning") or d.tool_calls):
        first = time.time() - t0
    if (d.model_extra or {}).get("reasoning"):
        reasoning_chunks += 1
    for tc in d.tool_calls or []:
        slot = acc.setdefault(tc.index, {"name": "", "args": ""})
        if tc.function and tc.function.name:
            slot["name"] += tc.function.name
        if tc.function and tc.function.arguments:
            slot["args"] += tc.function.arguments
    finish = chunk.choices[0].finish_reason or finish
parsed = [(v["name"], json.loads(v["args"]).get("city")) for v in acc.values()]
check("streaming tool calls", finish == "tool_calls" and sorted(c for _, c in parsed) == ["Lima", "Nairobi"]
      and all(n == "get_weather" for n, _ in parsed) and reasoning_chunks > 0,
      f"finish={finish} calls={parsed} reasoning_chunks={reasoning_chunks} ttft={first:.2f}s")

# 6. Prefix caching: identical long prefix twice, pinned to one data-parallel replica so both reach the same cache.
system = "You are a careful archivist. " + " ".join(f"Record {i}: item {i * 7919 % 1000} stored on shelf {i % 37}." for i in range(400))
hdr = {"X-data-parallel-rank": "0"}
cached = []
for q in ("Which shelf holds record 12?", "Which shelf holds record 99?"):
    r = client.chat.completions.create(model=model, max_tokens=256, extra_headers=hdr,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": q}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    det = r.usage.prompt_tokens_details
    cached.append((r.usage.prompt_tokens, det.cached_tokens if det else None))
check("prefix cache hit", cached[1][1] is not None and cached[1][1] > 0.8 * cached[1][0],
      f"(prompt_tokens, cached_tokens) per request: {cached}")

print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
