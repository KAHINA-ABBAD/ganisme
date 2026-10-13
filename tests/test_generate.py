import numpy as np
import torch

from ganisme.dcgan import Generator
from ganisme.generate import (
    export_generator,
    generate,
    load_discriminator,
    load_generator,
    realism,
    to_grid,
    trace,
)


def _fake_run(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    G = Generator(z_dim=16, ngf=8)
    from ganisme.dcgan import Discriminator
    D = Discriminator(ndf=8)
    torch.save({"G": G.state_dict(), "D": D.state_dict(), "config": {"z_dim": 16, "ngf": 8, "ndf": 8}, "epoch": 4},
               run / "last.pt")
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


def test_trace_and_discriminator_score(tmp_path):
    run, _ = _fake_run(tmp_path)
    path = export_generator(run, tmp_path / "g.pt")
    G, info = load_generator(path)
    D = load_discriminator(path)

    z, maps, image = trace(G, seed=3, z_dim=16)

    assert z.shape == (16,)
    assert [s for s, _ in maps] == [4, 8, 16, 32]
    assert all(m.min() >= 0 and m.max() <= 1 for _, m in maps)
    assert image.shape == (1, 3, 64, 64)
    assert 0 <= realism(D, image) <= 1
    assert load_discriminator(export_generator(run, tmp_path / "g2.pt", with_discriminator=False)) is None
