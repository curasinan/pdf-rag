"""Does the locally served model actually call the tool server, and answer from it?

Open WebUI sits between the model and ``tool_server.py``, so when a chat answer
comes back without a tool call it is unclear which side failed. This script plays
Open WebUI's part directly: it turns the tool server's OpenAPI schema into
OpenAI-style tool definitions, sends eval questions to the model's
OpenAI-compatible endpoint (vLLM, llama.cpp, Ollama), runs every tool call the
model makes against the tool server, and prints each call next to the eval set's
expected answer. A question answered without a single search_documents call is
flagged: that answer came from the model's own memory, not the documents.

Usage (tool server and model server both running):
    python tools/probe_local_model.py                       # h01, h14, h22
    python tools/probe_local_model.py --ids h02 h15 h23
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "questions_hard.json"
DEFAULT_IDS = ["h01", "h14", "h22"]   # page lookup, number, negative (answer is "no")
HEADER = re.compile(r"^\[.+, pages? [\d, \-]+\]$")


def tools_from_openapi(spec: dict) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """OpenAI tool definitions for every operation, plus name -> (method, path)."""
    schemas = spec.get("components", {}).get("schemas", {})
    tools, routes = [], {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            if body:
                ref = body["schema"].get("$ref", "")
                params = schemas[ref.rsplit("/", 1)[-1]] if ref else body["schema"]
                properties, required = params.get("properties", {}), params.get("required", [])
            else:
                query = op.get("parameters", [])
                properties = {p["name"]: p.get("schema", {}) for p in query}
                required = [p["name"] for p in query if p.get("required")]
            name = op["operationId"]
            tools.append({"type": "function", "function": {
                "name": name,
                "description": op.get("description") or op.get("summary", ""),
                "parameters": {"type": "object", "properties": properties,
                               "required": required},
            }})
            routes[name] = (method.upper(), path)
    return tools, routes


def call_tool(client: httpx.Client, tool_url: str, headers: dict,
              route: tuple[str, str], args: dict) -> str:
    """Run one tool call. Error bodies (e.g. a 404 listing valid names) go back to the
    model as text, so it can correct itself the way it would inside Open WebUI."""
    method, path = route
    if method == "GET":
        r = client.get(tool_url + path, headers=headers,
                       params={k: v for k, v in args.items() if v is not None})
    else:
        r = client.post(tool_url + path, headers=headers, json=args)
    return r.text if r.is_success else f"HTTP {r.status_code}: {r.text}"


def describe(result: str) -> str:
    """One line on what a tool call returned: passage count and their headers."""
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return result[:200]
    if "context" not in data:
        return json.dumps(data, ensure_ascii=False)[:300]
    headers = [ln for ln in data["context"].splitlines() if HEADER.match(ln)]
    return f"{data['chunks']} passages, truncated={data['truncated']}: " + "; ".join(headers)


def ask(client: httpx.Client, args, tools, routes, question: str) -> tuple[str, list, str]:
    """Run the tool loop for one question. Returns (answer, calls, reasoning tail)."""
    messages = [{"role": "user", "content": question}]
    calls: list[tuple[str, str, str]] = []
    reasoning = ""
    for _ in range(args.max_rounds):
        r = client.post(f"{args.model_url}/chat/completions", timeout=args.timeout, json={
            "model": args.model, "messages": messages, "tools": tools,
            "tool_choice": "auto", "max_tokens": args.max_tokens,
        })
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        # vLLM's reasoning parser moves the thinking out of `content`. Kept so a tool
        # call the model wrote inside its thinking (never parsed) is visible.
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return msg.get("content") or "", calls, reasoning
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": tool_calls})
        for tc in tool_calls:
            name, raw = tc["function"]["name"], tc["function"].get("arguments") or "{}"
            try:
                tool_args = json.loads(raw)
            except json.JSONDecodeError:
                tool_args = None
            if name not in routes:
                result = json.dumps({"error": f"unknown tool {name!r}"})
            elif not isinstance(tool_args, dict):
                result = json.dumps({"error": "tool arguments are not a JSON object"})
            else:
                result = call_tool(client, args.tool_url, args.tool_headers,
                                   routes[name], tool_args)
            calls.append((name, raw, describe(result)))
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    return f"(no final answer after {args.max_rounds} rounds)", calls, reasoning


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model-url", default="http://127.0.0.1:8000/v1",
                        help="OpenAI-compatible base URL of the model server.")
    parser.add_argument("--tool-url", default="http://127.0.0.1:8765",
                        help="Base URL of tool_server.py.")
    parser.add_argument("--model", default=None,
                        help="Model name (default: the first one the server lists).")
    parser.add_argument("--ids", nargs="+", default=DEFAULT_IDS,
                        help="Question ids from eval/questions_hard.json.")
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    by_id = {q["id"]: q for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))}
    unknown = [i for i in args.ids if i not in by_id]
    if unknown:
        parser.error(f"unknown question ids: {unknown}")

    token = os.environ.get("PDFRAG_SERVER_TOKEN")
    args.tool_headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=args.timeout) as client:
        spec = client.get(f"{args.tool_url}/openapi.json").json()
        tools, routes = tools_from_openapi(spec)
        if args.model is None:
            args.model = client.get(f"{args.model_url}/models").json()["data"][0]["id"]
        print(f"model: {args.model}   tools: {', '.join(routes)}\n")

        missed = 0
        for qid in args.ids:
            q = by_id[qid]
            start = time.monotonic()
            answer, calls, reasoning = ask(client, args, tools, routes, q["question"])
            print(f"=== {qid} ({q['question_type']}) {time.monotonic() - start:.0f}s")
            print(f"Q: {q['question']}")
            for n, (name, raw, result) in enumerate(calls, 1):
                print(f"  call {n}: {name} {raw}\n          -> {result}")
            if not any(name == "search_documents" for name, _, _ in calls):
                missed += 1
                print("  !! no search_documents call: this answer did not come from the documents")
                if reasoning:
                    print(f"  reasoning tail: ...{reasoning[-400:]}")
            print(f"A: {answer.strip()}")
            print(f"expected: {q['expected_answer']}\n")
    print(f"{len(args.ids) - missed}/{len(args.ids)} questions searched the documents.")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
