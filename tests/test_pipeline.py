import numpy as np
import pandas as pd
import torch
from PIL import Image

from ganisme.dcgan import Config, Discriminator, Generator, train
from ganisme.pipeline import PaintingDataset, export_folder, folder_to_array, make_transform


def test_transform_follows_course_pipeline():
    img = Image.new("RGB", (300, 150), (255, 0, 0))  # paysage rouge

    x = make_transform(64, hflip=False)(img)

    assert x.shape == (3, 64, 64)  # petit cote -> 64 puis carre central, sans deformation
    assert torch.allclose(x[0], torch.ones(64, 64)) and torch.allclose(x[1], -torch.ones(64, 64))  # [-1, 1]


def test_dataset_converts_to_rgb_and_skips_corrupted_files(tmp_path):
    Image.new("L", (80, 80), 128).save(tmp_path / "a.jpg")
    (tmp_path / "b.jpg").write_bytes(b"pas une image")

    ds = PaintingDataset(tmp_path, make_transform(64, hflip=False))

    assert len(ds) == 2
    assert ds[0].shape == (3, 64, 64)
    assert ds[1].shape == (3, 64, 64)  # le fichier illisible est remplace par le suivant


def _manifest(tmp_path, n=12):
    src = tmp_path / "src"
    src.mkdir()
    rows = []
    for i in range(n):
        Image.new("RGB", (256, 256), (i * 20, 50, 100)).save(src / f"{i:05d}.jpg")
        rows.append({"image_id": i, "status": "processed", "split": "eval" if i < 3 else "train",
                     "local_path": f"x/{i:05d}.jpg"})
    rows.append({"image_id": 99, "status": "failed", "split": "train", "local_path": None})
    pd.DataFrame(rows).to_csv(tmp_path / "manifest.csv", index=False)
    return tmp_path / "manifest.csv", src


def test_export_folder_writes_resized_split(tmp_path):
    manifest, src = _manifest(tmp_path)

    counts = export_folder(manifest, src, tmp_path / "out", 128)

    assert counts == {"train": 9, "eval": 3}
    with Image.open(next((tmp_path / "out" / "train").glob("*.jpg"))) as img:
        assert img.size == (128, 128)
    arr = folder_to_array(tmp_path / "out" / "eval", 64)
    assert arr.shape == (3, 64, 64, 3) and arr.dtype == np.uint8


def test_dcgan_128_shapes():
    G, D = Generator(16, 8, image_size=128), Discriminator(8, image_size=128)
    images = G(torch.randn(2, 16, 1, 1))

    assert images.shape == (2, 3, 128, 128)
    assert D(images).shape == (2,)


def test_64_architecture_unchanged_for_existing_checkpoints():
    keys = list(Generator(100, 64).state_dict())
    assert keys[0] == "net.0.weight" and keys[-1] == "net.12.weight"
    assert Generator(100, 64).net[0].out_channels == 512


def test_train_from_image_folder(tmp_path):
    manifest, src = _manifest(tmp_path, n=20)
    export_folder(manifest, src, tmp_path / "imgs", 64)
    cfg = Config(images=str(tmp_path / "imgs"), run_dir=str(tmp_path / "run"), epochs=1, batch_size=8,
                 ngf=8, ndf=8, n_fixed=4, image_size=64)

    result = train(cfg)

    assert result["n_train"] == 17 and result["iterations"] == 17 // 8
    assert (tmp_path / "run" / "last.pt").exists()
