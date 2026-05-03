from pydantic import ValidationError

from aituber_partner.models import InputEvent, OverlayState, SafetyDecision


def test_input_event_defaults_are_populated() -> None:
    event = InputEvent(source="youtube_chat", text="こんにちは")

    assert event.id.startswith("input_")
    assert event.metadata == {}
    assert event.timestamp.tzinfo is not None


def test_safety_confidence_must_be_probability() -> None:
    try:
        SafetyDecision(status="allow", confidence=1.5)
    except ValidationError:
        return

    raise AssertionError("confidence above 1.0 should fail validation")


def test_overlay_state_defaults_to_idle() -> None:
    state = OverlayState()

    assert state.status == "idle"
    assert state.text == ""

