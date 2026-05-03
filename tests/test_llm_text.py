from aituber_partner.llm.text import strip_thinking_text


def test_strip_thinking_text_removes_tagged_blocks() -> None:
    text = strip_thinking_text("<think>考え中</think>\nナイスプレイ！")

    assert text == "ナイスプレイ！"


def test_strip_thinking_text_removes_internal_analysis_lines() -> None:
    text = strip_thinking_text("思考: コメントを褒める\nこれは拾いやすいね！")

    assert text == "これは拾いやすいね！"

