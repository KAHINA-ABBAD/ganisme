import io
import time

import pandas as pd
import pytest
from PIL import Image

from ganisme import download
from ganisme.download import DownloadError, center_square, init_manifest, process_bytes, run, save_manifest


def _jpeg(width, height, color=(200, 30, 30), mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, (width, height), color if mode == "RGB" else 128).save(out, format="PNG")
    return out.getvalue()


def test_center_square_crops_the_middle():
    image = Image.new("RGB", (300, 100))
    image.paste((255, 0, 0), (100, 0, 200, 100))  # bande centrale rouge

    square = center_square(image, size=50)

    assert square.size == (50, 50)
    assert square.getpixel((0, 0)) == (255, 0, 0)


def test_process_bytes_converts_to_rgb_square():
    jpeg, info = process_bytes(_jpeg(400, 300, mode="L"))

    image = Image.open(io.BytesIO(jpeg))
    assert image.size == (256, 256) and image.mode == "RGB"
    assert info == {"orig_width": 400, "orig_height": 300, "orig_mode": "L"}


def test_process_bytes_rejects_bad_images():
    with pytest.raises(ValueError, match="illisible"):
        process_bytes(b"not an image")
    with pytest.raises(ValueError, match="trop petite"):
        process_bytes(_jpeg(100, 100))
    with pytest.raises(ValueError, match="ratio") as caught:
        process_bytes(_jpeg(1200, 300))
    assert caught.value.skip


def test_read_with_deadline_stops_a_trickling_server():
    class Trickle:
        def read(self, size):
            time.sleep(0.02)
            return b"x"  # ne se termine jamais

    start = time.monotonic()
    with pytest.raises(DownloadError, match="delai"):
        download._read_with_deadline(Trickle(), deadline=start + 0.2)
    assert time.monotonic() - start < 1


def test_read_with_deadline_returns_full_content():
    assert download._read_with_deadline(io.BytesIO(b"a" * 200_000), time.monotonic() + 5) == b"a" * 200_000


def _manifest(tmp_path, n=4):
    selection = pd.DataFrame({"image_id": range(n), "image_url": [f"img{i}" for i in range(n)]})
    path = tmp_path / "manifest.csv"
    save_manifest(init_manifest(selection), path)
    return path


def test_run_processes_detects_duplicates_and_resumes(tmp_path, monkeypatch):
    responses = {
        "img0": _jpeg(300, 300, (10, 10, 10)),
        "img1": _jpeg(300, 300, (10, 10, 10)),  # doublon exact de img0
        "img2": DownloadError("HTTP 404", 404, retryable=False),
        "img3": _jpeg(300, 300, (90, 90, 90)),
    }

    def fake_fetch(url):
        if isinstance(responses[url], Exception):
            raise responses[url]
        return responses[url]

    monkeypatch.setattr(download, "fetch", fake_fetch)
    path, images = _manifest(tmp_path), tmp_path / "images"

    first = run(path, images, delay=0, workers=1)

    statuses = first.set_index("image_id")["status"].to_dict()
    assert statuses == {0: "processed", 1: "skipped", 2: "failed", 3: "processed"}
    assert sorted(p.name for p in images.iterdir()) == ["00000.jpg", "00003.jpg"]

    # Reprise : un fichier perdu est retraite, l'echec est retente, le reste n'est pas refait.
    (images / "00003.jpg").unlink()
    calls = []
    monkeypatch.setattr(download, "fetch", lambda url: calls.append(url) or fake_fetch(url))

    second = run(path, images, delay=0, workers=1)

    assert sorted(calls) == ["img2", "img3"]
    assert (images / "00003.jpg").exists()
    assert second.set_index("image_id").loc[2, "attempts"] == 2


def test_run_respects_limit_and_max_attempts(tmp_path, monkeypatch):
    def always_fails(url):
        raise DownloadError("reseau")

    monkeypatch.setattr(download, "fetch", always_fails)
    path, images = _manifest(tmp_path, n=3), tmp_path / "images"

    run(path, images, limit=2, delay=0, workers=1)
    assert (pd.read_csv(path)["attempts"] > 0).sum() == 2

    for _ in range(4):
        run(path, images, delay=0, workers=1)
    assert pd.read_csv(path)["attempts"].max() == 3
