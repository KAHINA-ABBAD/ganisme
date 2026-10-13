from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"
MODEL = APP.parent / "models" / "generator_portraits_64.pt"

pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="aucun generateur exporte dans models/")


def _app():
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    return at


def test_one_painting_navigation_and_schema():
    at = _app()
    assert at.session_state["seed"] == 42
    assert any("n° 000042" in m.value for m in at.markdown)
    assert any("4 × 4" in c.value for c in at.caption)  # le schema montre les couches du generateur
    assert len(at.get("progress")) == 1                  # score du discriminateur

    at.button(key="next").click().run()
    assert at.session_state["seed"] == 43
    at.button(key="prev").click().run()
    at.button(key="prev").click().run()
    assert at.session_state["seed"] == 41
    at.button(key="random").click().run()
    assert not at.exception


def test_switching_collection_keeps_working():
    at = _app()
    for name in at.segmented_control(key="collection").options:
        at.segmented_control(key="collection").set_value(name).run()
        assert not at.exception
