"""Minimal OpenAI-compatible chat client with tool calling. Works with Ollama / vLLM / llama.cpp server
(open-weights, runs in-country) or any hosted frontier API. No SDK dependency."""
import os, httpx

class LLM:
    def __init__(self):
        self.base = os.environ.get("CSA_LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        self.model = os.environ.get("CSA_LLM_MODEL", "qwen2.5:7b-instruct")
        self.key = os.environ.get("CSA_LLM_API_KEY", "ollama")
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    async def chat(self, messages, tools):
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{self.base}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                             json={"model": self.model, "messages": messages, "tools": tools, "temperature": 0, "seed": 7})
            r.raise_for_status(); j = r.json()
        u = j.get("usage") or {}
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0); self.usage["completion_tokens"] += u.get("completion_tokens", 0); self.usage["calls"] += 1
        return j["choices"][0]["message"]

def mcp_tools_to_openai(tools, allow: set[str]):
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.input_schema}}
            for t in tools if t.name in allow]
