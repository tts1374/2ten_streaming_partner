# Repository Guidelines

## Project Goal

This repository builds a Phase 1 local AITuber streaming partner for YouTube Live.

The Phase 1 target is a locally demonstrable co-host that can:

- read YouTube Live Chat,
- accept microphone speech through local STT,
- generate idle topics when there is no input,
- select safe and useful prompts,
- generate short Japanese co-host replies with local LLMs,
- speak through AivisSpeech,
- show subtitles through an OBS browser overlay,
- persist events, decisions, replies, and model usage.

## Phase 1 Scope

Keep Phase 1 focused on the local text/audio/subtitle loop.

In scope:

- YouTube Live Chat input.
- Local Whisper-family STT.
- Idle topic generation.
- Local Ollama LLM routing.
- Safety checks before and after reply generation.
- AivisSpeech TTS.
- OBS browser-source subtitle overlay.
- SQLite event history.
- LanceDB-based retrieval for a small number of related memories.

Out of scope for Phase 1:

- Full autonomous live operation.
- Live2D or 3D model control.
- Lip sync, expressions, and motion control.
- Advanced OBS scene control.
- Qwen3-TTS production integration.
- Automatic long-term persona mutation.
- Always-on vision model usage in the real-time path.

## LLM Routing Rules

Use Ollama as the local LLM runtime.

Default model roles:

- `qwen3.5:4b`: classification, safety, comment extraction, input routing.
- `qwen3:8b`: normal real-time Japanese reply generation.
- `qwen3.5:9b`: vision-related input only, such as OBS capture analysis.
- `pakachan/elyza-llama3-8b`: non-real-time Japanese/persona quality review and future memory-review validation.

Important constraints:

- All Qwen model calls for streaming output must pass `think: false`.
- Thinking, reasoning tags, or internal-analysis-like text must never reach subtitles or TTS.
- `qwen3.5:9b` must not be used for normal text chat replies without image input.
- Keep real-time paths on `qwen3.5:4b` and `qwen3:8b` unless a task explicitly changes the architecture.
- Log which model handled each decision or generation step.

## Safety Rules

Safety is part of the runtime design, not only a prompt detail.

Before generating a reply:

- classify the input,
- reject or deflect unsafe content,
- avoid personally identifying information,
- avoid discriminatory, sexual, violent, illegal, harassing, inflammatory, or streamer/viewer-attacking content.

After generating a reply:

- run a final safety check before TTS or subtitles,
- drop, rewrite, or deflect if the output is unsafe,
- persist the safety decision.

For malformed LLM JSON in safety or selection steps, fail closed and do not answer.

## Persona Rules

The initial character is a bright, casual Japanese co-host for music game streams.

The assistant should:

- help pick up comments,
- expand topics briefly,
- react to the human streamer's play or remarks,
- keep the stream moving when there is silence,
- support the human streamer without taking over,
- avoid harsh teasing, provocation, and aggressive jokes.

Replies should be short enough for TTS and live subtitles.

## Architecture Preferences

Prefer a loosely coupled local architecture.

Recommended backend direction:

- Python-first backend.
- `asyncio` for input, LLM, TTS, overlay, and storage orchestration.
- Pydantic models for shared event and decision shapes.
- SQLite for durable event history.
- LanceDB for vector retrieval.
- AivisSpeech API for TTS.

Recommended frontend direction:

- Minimal OBS browser overlay.
- Use WebSocket or Server-Sent Events for overlay state updates.
- Prefer a simple subtitle-first UI over a large application shell.

Keep generated runtime data out of Git:

- local config,
- SQLite databases,
- LanceDB data,
- generated audio,
- logs.

## Python Environment

The machine has Python 3.13, but STT libraries may lag behind it.

For implementation, prefer Python 3.11 or 3.12 unless dependency checks show 3.13 is safe.

When introducing tooling:

- keep the initial dependency set small,
- prefer reproducible project configuration,
- avoid adding heavyweight frameworks before the local closed-loop PoC needs them.

## Implementation Order

Follow this order unless a user request clearly changes the priority:

1. Add or update repository guidance and design documents.
2. Create the Python project skeleton.
3. Define config loading and Pydantic data models.
4. Implement a fake input source and local closed-loop orchestrator.
5. Implement Ollama client and LLM router.
6. Add SQLite persistence and model-call logging.
7. Add AivisSpeech integration.
8. Add OBS subtitle overlay.
9. Add YouTube Chat input.
10. Add microphone STT.
11. Add LanceDB retrieval.
12. Promote stable project-specific workflows into Codex skills or subagent templates.

## Testing Priorities

Prioritize tests that catch routing and safety regressions.

Initial tests should cover:

- correct model selection by LLM purpose,
- `think: false` on Qwen calls,
- no `qwen3.5:9b` call for image-free normal chat,
- safety JSON parse failure fails closed,
- unsafe comments are ignored, blocked, or deflected,
- generated replies do not expose thinking text,
- TTS failure does not prevent subtitle state updates,
- SQLite records inputs, decisions, replies, TTS jobs, and LLM calls,
- idle topic events fire after configured inactivity.

## Documentation

Keep `docs/requirements.md` as the product requirement source.

Keep `docs/architecture.md` as the technical design source.

When implementation decisions change model roles, process boundaries, persistence, or Phase 1 scope, update the docs in the same change.

