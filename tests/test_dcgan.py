import numpy as np
import torch

from ganisme.dcgan import Config, Discriminator, Generator, to_tensor, train


def test_shapes():
    G, D = Generator(z_dim=100, ngf=8), Discriminator(ndf=8)
    images = G(torch.randn(4, 100, 1, 1))

    assert images.shape == (4, 3, 64, 64)
    assert images.min() >= -1 and images.max() <= 1
    assert D(images).shape == (4,)


def test_to_tensor_range():
    t = to_tensor(np.array([[[[0, 255, 128]]]], dtype=np.uint8))

    assert t.shape == (1, 3, 1, 1)
    assert t.min() == -1 and t.max() == 1


def _fake_dataset(tmp_path, n=40):
    rng = np.random.default_rng(0)
    path = tmp_path / "data.npz"
    np.savez(path, images=rng.integers(0, 256, (n, 64, 64, 3), dtype=np.uint8),
             image_id=np.arange(n), split=np.array(["train"] * (n - 4) + ["eval"] * 4))
    return path


def _config(tmp_path, data, epochs):
    return Config(data=str(data), run_dir=str(tmp_path / "run"), epochs=epochs, batch_size=8, ngf=8, ndf=8, n_fixed=4)


def test_train_updates_weights_saves_and_resumes(tmp_path):
    data = _fake_dataset(tmp_path)
    first = train(_config(tmp_path, data, epochs=1))

    run = tmp_path / "run"
    assert (run / "last.pt").exists() and (run / "samples" / "epoch_000.png").exists()
    assert first["iterations"] == 36 // 8  # lots complets uniquement
    ckpt1 = torch.load(run / "last.pt", weights_only=False)
    assert all(np.isfinite([h["loss_d"], h["loss_g"]]).all() for h in first["history"])

    # Reprise : l'epoque 1 continue apres l'epoque 0, sans recommencer.
    second = train(_config(tmp_path, data, epochs=2))

    assert second["iterations"] == 2 * (36 // 8)
    assert [h["epoch"] for h in second["history"]].count(0) == 36 // 8
    assert (run / "samples" / "epoch_001.png").exists()
    ckpt2 = torch.load(run / "last.pt", weights_only=False)
    for net in ("G", "D"):  # les poids du meme reseau ont bien bouge pendant l'epoque 1
        assert any(not torch.equal(ckpt1[net][k], v) for k, v in ckpt2[net].items() if v.dtype.is_floating_point)


def test_train_on_finished_run_does_nothing(tmp_path):
    data = _fake_dataset(tmp_path)
    train(_config(tmp_path, data, epochs=1))

    again = train(_config(tmp_path, data, epochs=1))

    assert again["epochs_done"] == 1
    assert again["iterations"] == 36 // 8
