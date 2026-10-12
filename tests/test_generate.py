import numpy as np
import torch

from ganisme.dcgan import Generator
from ganisme.generate import export_generator, generate, load_generator, to_grid


def _fake_run(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    G = Generator(z_dim=16, ngf=8)
    torch.save({"G": G.state_dict(), "config": {"z_dim": 16, "ngf": 8}, "epoch": 4}, run / "last.pt")
    return run, G


def test_export_and_load_roundtrip(tmp_path):
    run, G = _fake_run(tmp_path)

    path = export_generator(run, tmp_path / "models" / "g.pt", metrics={"fid": 123.0})
    loaded, info = load_generator(path)

    assert info["epochs"] == 5 and info["z_dim"] == 16 and info["metrics"] == {"fid": 123.0}
    for k, v in G.state_dict().items():
        assert torch.equal(v, loaded.state_dict()[k])


def test_generate_is_reproducible_per_seed(tmp_path):
    run, _ = _fake_run(tmp_path)
    G, info = load_generator(export_generator(run, tmp_path / "g.pt"))

    a, b = generate(G, 4, seed=7, z_dim=16), generate(G, 4, seed=7, z_dim=16)
    c = generate(G, 4, seed=8, z_dim=16)

    assert a.shape == (4, 64, 64, 3) and a.dtype == np.uint8
    assert np.array_equal(a, b) and not np.array_equal(a, c)


def test_to_grid_size_and_scale():
    images = np.zeros((4, 64, 64, 3), dtype=np.uint8)

    assert to_grid(images, ncols=2, pad=4).size == (2 * 68 + 4, 2 * 68 + 4)
    assert to_grid(images, ncols=2, scale=3, pad=4).size == (3 * 140, 3 * 140)
