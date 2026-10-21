# 02 · Setting up the local model

> **Using the desktop app?** You don't need any of the manual steps below. Open the **Control** tab, press
> *Install engine*, then *Download* a model. Both land in the app's own `home/` folder ([docs/08](08_DESKTOP_APP.md)).
> This page is for running from source or using a model server you installed yourself.

The agent talks to a **local model server** over HTTP. You only need one of these:

```
  hybrid_agent ──HTTP──► Ollama            (LOCAL_PROVIDER=ollama, port 11434)   ← recommended
               └─HTTP──► llama.cpp server  (LOCAL_PROVIDER=openai, port 8080)
               └─HTTP──► LM Studio         (LOCAL_PROVIDER=openai, port 1234)
               └─HTTP──► vLLM / LocalAI…   (LOCAL_PROVIDER=openai)
```

Analogy: the model file is a record and the server is a record player. The agent can't
play the record itself; it asks the player to.

## Option 1: Ollama (recommended)

```bash
# macOS / Windows: install the app from https://ollama.com/download
# Linux:
curl -fsSL https://ollama.com/install.sh | sh

ollama serve                 # skip this if the desktop app is already running
ollama pull qwen2.5:7b       # download a model
python3 -m hybrid_agent doctor
```

`.env`:
```
LOCAL_PROVIDER=ollama
LOCAL_BASE_URL=http://localhost:11434
LOCAL_MODEL=qwen2.5:7b
```

## Option 2: llama.cpp server

```bash
llama-server -m ./models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8080 --jinja -c 8192
```
`--jinja` turns on native tool calling for models whose chat template supports it.
```
LOCAL_PROVIDER=openai
LOCAL_BASE_URL=http://localhost:8080
LOCAL_MODEL=qwen2.5-7b-instruct
```

## Option 3: LM Studio

Load a model, open the **Developer** tab, and click **Start Server**. Then:
```
LOCAL_PROVIDER=openai
LOCAL_BASE_URL=http://localhost:1234
LOCAL_MODEL=<the model identifier shown in LM Studio>
```

## Choosing a model

The agent needs a model that follows instructions well and ideally has **native tool calling**.

| Model (Ollama tag) | Download | RAM needed (approx.) | Tool calling | Notes |
|---|---|---|---|---|
| `qwen2.5:3b` | ~2 GB | 4 GB | native | Low-end laptops; simple tasks only |
| `llama3.2:3b` | ~2 GB | 4 GB | native | Similar tier |
| **`qwen2.5:7b`** (default) | ~4.7 GB | 8 GB | native | Good balance |
| `llama3.1:8b` | ~4.9 GB | 8 GB | native | Solid general model |
| `mistral-nemo:12b` | ~7 GB | 12 GB | native | |
| `qwen2.5:14b` | ~9 GB | 16 GB | native | Much better at multi-step work |
| `qwen2.5:32b` | ~20 GB | 24–32 GB / GPU | native | Approaches hosted-model quality on many tasks |

Newer model families appear often. Any model Ollama marks with the **"tools"** tag
works in native mode. Any other instruction-tuned model works in prompt mode.

**Rule of thumb:** a model at 4-bit quantisation needs about 0.6 GB of memory per billion
parameters, plus room for the context.

## Tool-calling modes

| `LOCAL_TOOL_MODE` | Behaviour |
|---|---|
| `auto` (default) | Tries native tool calling. If the server says the model doesn't support tools, switches to `prompt` for the rest of the session |
| `native` | Always uses the server's tool-calling API |
| `prompt` | Lists the tools in the system prompt and reads `{"tool": ..., "arguments": ...}` JSON blocks from the reply. Works with any model |

If the model "talks about" a tool call without actually making one, set `LOCAL_TOOL_MODE=prompt`.

## Several models (for a council)

```bash
ollama pull qwen2.5:7b && ollama pull llama3.1:8b && ollama pull mistral-nemo
```
Then give council members different backends, e.g. `"backend": "local:llama3.1:8b"`
(see [05_COUNCIL.md](05_COUNCIL.md)). Ollama keeps recently used models in memory; set
`OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_NUM_PARALLEL` to match your RAM.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `local model server ... unreachable` | Start `ollama serve` (or your server); check `LOCAL_BASE_URL` |
| `model 'x' not found` | `ollama pull x`, or fix `LOCAL_MODEL` (check with `ollama list`) |
| Very slow | Use a smaller model, or a GPU; lower `LOCAL_NUM_CTX` |
| The model forgets earlier parts of the chat | Raise `LOCAL_NUM_CTX` (uses more RAM); use `/reset` between tasks |
| The model loops on the same tool | Lower `AGENT_MAX_STEPS`, or use a bigger model |
| Timeout on the first message | The model is still loading into memory; raise `LOCAL_TIMEOUT` |
