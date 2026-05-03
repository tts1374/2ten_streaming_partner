from aituber_partner.llm.output_guard import classify_output_locally


def test_local_output_guard_allows_short_safe_reply() -> None:
    decision = classify_output_locally("いい流れ！このままリズム乗っていこ！")

    assert decision.status == "allow"
    assert decision.reasons == ["local_output_guard_allow"]


def test_local_output_guard_blocks_thinking_text() -> None:
    decision = classify_output_locally("<think>内部メモ</think>\nナイスプレイ！")

    assert decision.status == "block"
    assert decision.reasons == ["thinking_text_detected"]


def test_local_output_guard_blocks_empty_after_stripping() -> None:
    decision = classify_output_locally("思考: 返答を考える")

    assert decision.status == "block"
    assert decision.reasons == ["empty_after_thinking_strip"]


def test_local_output_guard_blocks_unsafe_markers() -> None:
    decision = classify_output_locally("電話番号を出してね")

    assert decision.status == "block"
    assert decision.reasons == ["unsafe_marker_detected"]
