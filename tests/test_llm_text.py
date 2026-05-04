from aituber_partner.llm.prompts import REPLY_SYSTEM_PROMPT, build_reply_prompt
from aituber_partner.llm.text import strip_thinking_text
from aituber_partner.models import InputEvent, SafetyDecision


def test_strip_thinking_text_removes_tagged_blocks() -> None:
    text = strip_thinking_text("<think>考え中</think>\nナイスプレイ！")

    assert text == "ナイスプレイ！"


def test_strip_thinking_text_removes_internal_analysis_lines() -> None:
    text = strip_thinking_text("思考: コメントを褒める\nこれは拾いやすいね！")

    assert text == "これは拾いやすいね！"


def test_reply_prompt_anchors_on_viewer_input_and_avoids_invention() -> None:
    prompt = build_reply_prompt(
        InputEvent(source="youtube_chat", text="音量大丈夫？"),
        SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        streamer_name="つてん",
    )

    assert "streamer name: つてん" in prompt
    assert "relaying to the streamer" in prompt
    assert "main anchor" in prompt
    assert "answer the check directly" in prompt
    assert "sound, visibility, latency, or setup" in prompt
    assert "Avoid stock phrases" in prompt


def test_reply_system_prompt_forbids_invented_stream_state() -> None:
    assert "main conversation partner is the human streamer" in REPLY_SYSTEM_PROMPT
    assert "not as a generic chatbot" in REPLY_SYSTEM_PROMPT
    assert "Do not invent stream state" in REPLY_SYSTEM_PROMPT


def test_voice_reply_prompt_addresses_streamer_directly() -> None:
    prompt = build_reply_prompt(
        InputEvent(source="voice", text="この曲むずいね"),
        SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        streamer_name="つてん",
    )

    assert "streamer name: つてん" in prompt
    assert "addressed directly to the human streamer" in prompt
    assert "streamer's speech" in prompt
    assert "instead of summarizing for viewers" in prompt


def test_idle_reply_prompt_uses_recent_input_metadata() -> None:
    prompt = build_reply_prompt(
        InputEvent(
            source="idle_topic",
            text="少し話題を振る",
            metadata={
                "recent_input_source": "youtube_chat",
                "recent_input_author": "@viewer",
                "recent_input_text": "音量大丈夫",
            },
        ),
        SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        streamer_name="つてん",
    )

    assert "streamer name: つてん" in prompt
    assert "topic prompt addressed to the human streamer" in prompt
    assert "recent input text: 音量大丈夫" in prompt


def test_deflect_reply_prompt_uses_streamer_name() -> None:
    prompt = build_reply_prompt(
        InputEvent(source="youtube_chat", text="危ない話題"),
        SafetyDecision(status="deflect", reasons=["unsafe"], safe_topic="音ゲー配信", confidence=0.8),
        streamer_name="つてん",
    )

    assert "Address the human streamer as つてん." in prompt
