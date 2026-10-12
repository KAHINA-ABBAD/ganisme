"""Pipeline image du cours « Traitement d'images » (La Plateforme, how-to GAN, slides 10 et 11).

- ``make_transform`` : Resize (petit cote) -> CenterCrop -> RandomHorizontalFlip -> ToTensor -> Normalize ;
- ``PaintingDataset`` : dataset « lazy » (lit les images une par une), robuste aux fichiers corrompus ;
- ``export_folder`` : sauvegarde un dossier dedie a la taille d'entrainement (« redimensionner des le
  download »), separe en ``train/`` et ``eval/`` selon le decoupage par oeuvre du manifeste.

La classe est definie dans un module (et non dans un notebook) pour que le DataLoader puisse utiliser
plusieurs processus (``num_workers > 0``) sous Windows.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms


def make_transform(image_size: int, hflip: bool = True) -> transforms.Compose:
    """Pipeline de la slide 10. L'ordre importe : jamais Normalize avant ToTensor."""
    steps = [
        transforms.Resize(image_size, interpolation=transforms.InterpolationMode.BILINEAR),  # petit cote -> S
        transforms.CenterCrop(image_size),  # carre S x S
    ]
    if hflip:
        steps.append(transforms.RandomHorizontalFlip(p=0.5))  # augmentation sans danger
    steps += [
        transforms.ToTensor(),  # [0, 1], (3, H, W)
        transforms.Normalize(mean=[0.5] * 3, std=[0.5] * 3),  # -> [-1, 1], aligne sur le tanh de G
    ]
    return transforms.Compose(steps)


class PaintingDataset(Dataset):
    """Images d'un dossier, chargees a la demande (slide 11)."""

    def __init__(self, img_dir: str | Path, transform=None):
        self.paths = sorted(Path(img_dir).glob("*.jpg"))
        self.transform = transform

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx):
        try:
            img = Image.open(self.paths[idx]).convert("RGB")  # toujours 3 canaux
        except Exception:
            return self.__getitem__((idx + 1) % len(self))  # image illisible : on passe a la suivante
        return self.transform(img) if self.transform else img


def export_folder(manifest: str | Path, source_dir: str | Path, out_dir: str | Path, size: int) -> dict:
    """Ecrit les images ``processed`` du manifeste en ``size`` x ``size`` dans ``out_dir/train`` et ``out_dir/eval``."""
    man = pd.read_csv(manifest)
    ok = man[man["status"] == "processed"]
    counts = {"train": 0, "eval": 0}
    for split in counts:
        (Path(out_dir) / split).mkdir(parents=True, exist_ok=True)
    for _, row in ok.iterrows():
        src = Path(source_dir) / Path(row["local_path"]).name
        dst = Path(out_dir) / row["split"] / src.name
        if not dst.exists():
            with Image.open(src) as img:
                img.convert("RGB").resize((size, size), Image.Resampling.LANCZOS).save(dst, quality=95)
        counts[row["split"]] += 1
    return counts


def folder_to_array(folder: str | Path, image_size: int) -> np.ndarray:
    """Images d'un dossier, passees par le pipeline sans augmentation, en uint8 (n, S, S, 3)."""
    dataset = PaintingDataset(folder, make_transform(image_size, hflip=False))
    images = torch.stack([dataset[i] for i in range(len(dataset))])
    return ((images + 1) * 127.5).round().clamp(0, 255).byte().permute(0, 2, 3, 1).numpy()
