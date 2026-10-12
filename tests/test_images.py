import numpy as np
from PIL import Image

from ganisme.images import (
    average_hash,
    brightness,
    confirm_pairs,
    hamming,
    load_images,
    near_duplicate_pairs,
    saturation,
)


def test_load_images_resizes_and_converts(tmp_path):
    path = tmp_path / "a.png"
    Image.new("L", (40, 40), 200).save(path)

    images = load_images([path], size=16)

    assert images.shape == (1, 16, 16, 3) and images.dtype == np.uint8
    assert images[0, 0, 0].tolist() == [200, 200, 200]


def test_saturation_and_brightness():
    gray = np.full((1, 8, 8, 3), 128, dtype=np.uint8)
    red = np.zeros((1, 8, 8, 3), dtype=np.uint8)
    red[..., 0] = 255

    assert saturation(gray)[0] == 0
    assert saturation(red)[0] == 1
    assert np.isclose(brightness(gray)[0], 128 / 255, atol=1e-3)


def test_average_hash_matches_near_duplicates_only():
    rng = np.random.default_rng(0)
    base = rng.integers(0, 256, (64, 64, 3)).astype(np.uint8)
    noisy = np.clip(base.astype(int) + rng.integers(-5, 6, base.shape), 0, 255).astype(np.uint8)
    other = rng.integers(0, 256, (64, 64, 3)).astype(np.uint8)

    hashes = average_hash(np.stack([base, noisy, other]))

    assert hamming(hashes[1:2], hashes[0])[0] <= 4
    assert hamming(hashes[2:3], hashes[0])[0] > 16


def test_confirm_pairs_rejects_same_layout_different_paintings():
    # Deux "paysages" : ciel clair en haut, sol sombre en bas -> meme aHash, pixels differents.
    a = np.zeros((64, 64, 3), dtype=np.uint8)
    a[:32] = 220
    a[32:] = 40
    b = a.copy()
    b[:32] = 160  # autre ciel
    b[32:] = 90   # autre sol
    images = np.stack([a, a.copy(), b])
    hashes = average_hash(images)
    assert hashes[0] == hashes[2]  # l'empreinte seule les confond

    pairs = near_duplicate_pairs(hashes, max_distance=0)

    assert sorted(map(tuple, confirm_pairs(images, pairs).tolist())) == [(0, 1)]


def test_near_duplicate_pairs():
    hashes = np.array([0b0000, 0b0001, 0b1111_0000_1111, 0b0000], dtype=np.uint64)

    pairs = near_duplicate_pairs(hashes, max_distance=1, chunk=2)

    assert sorted(map(tuple, pairs.tolist())) == [(0, 1), (0, 3), (1, 3)]
