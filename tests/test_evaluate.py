import numpy as np

from ganisme.evaluate import fid, grid, kid


def test_fid_is_zero_for_identical_sets_and_grows_with_shift():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(500, 8))

    assert abs(fid(a, a)) < 1e-6
    assert fid(a, a + 0.5) > fid(a, a + 0.1) > 0


def test_kid_is_near_zero_for_same_distribution():
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=(600, 8)), rng.normal(size=(600, 8))
    shifted = rng.normal(loc=1.0, size=(600, 8))

    same, _ = kid(a, b, subsets=10, size=200)
    different, _ = kid(a, shifted, subsets=10, size=200)

    assert abs(same) < 0.02
    assert different > 10 * abs(same)


def test_grid_layout():
    images = np.zeros((5, 4, 4, 3), dtype=np.uint8)

    assert grid(images, ncols=2, pad=1).size == (2 * 5 + 1, 3 * 5 + 1)
