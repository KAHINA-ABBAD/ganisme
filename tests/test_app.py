from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"
MODEL = APP.parent / "models" / "generator.pt"

pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="aucun generateur exporte dans models/")


def _app():
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    return at


def test_one_painting_and_navigation():
    at = _app()
    assert at.session_state["seed"] == 42
    assert any("n° 000042" in m.value for m in at.markdown)

    at.button(key="next").click().run()
    assert at.session_state["seed"] == 43
    at.button(key="prev").click().run()
    at.button(key="prev").click().run()
    assert at.session_state["seed"] == 41
    assert not at.exception


def test_switching_collection_keeps_working():
    at = _app()
    options = at.segmented_control(key="collection").options
    for name in options:
        at.segmented_control(key="collection").set_value(name).run()
        assert not at.exception


def test_random_and_chosen_painting():
    at = _app()
    at.button(key="random").click().run()
    assert not at.exception and at.session_state["seed"] != 42

    at.number_input(key="seed").set_value(1234).run()
    assert not at.exception
    assert any("n° 001234" in m.value for m in at.markdown)
