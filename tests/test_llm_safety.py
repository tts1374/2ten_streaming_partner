from aituber_partner.llm.safety import parse_safety_decision


def test_parse_safety_decision_accepts_valid_json() -> None:
    decision = parse_safety_decision(
        '{"status":"allow","reasons":["ok"],"safe_topic":null,"confidence":0.9}'
    )

    assert decision.status == "allow"
    assert decision.reasons == ["ok"]
    assert decision.confidence == 0.9


def test_parse_safety_decision_accepts_json_fence() -> None:
    decision = parse_safety_decision(
        """
```json
{"status":"deflect","reasons":["heated"],"safe_topic":"曲の話題","confidence":0.7}
```
""".strip()
    )

    assert decision.status == "deflect"
    assert decision.safe_topic == "曲の話題"


def test_parse_safety_decision_fails_closed_on_malformed_json() -> None:
    decision = parse_safety_decision("これはJSONではありません")

    assert decision.status == "block"
    assert decision.reasons == ["malformed_safety_json"]
    assert decision.confidence == 0.0


def test_parse_safety_decision_fails_closed_on_invalid_schema() -> None:
    decision = parse_safety_decision('{"status":"allow","confidence":2.0}')

    assert decision.status == "block"
    assert decision.reasons == ["malformed_safety_json"]

