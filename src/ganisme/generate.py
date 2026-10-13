"""Generation de peintures a partir d'un generateur entraine (utilise par l'application Streamlit).

Le generateur est exporte dans un fichier leger (poids + configuration), sans les etats
d'optimiseurs ni l'historique du checkpoint d'entrainement :

    python -m ganisme.generate --run_dir runs/dcgan_64 --out models/generator.pt
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from ganisme.dcgan import Discriminator, Generator


def export_generator(run_dir: str | Path, out: str | Path, metrics: dict | None = None,
                     with_discriminator: bool = True) -> Path:
    """Extrait les poids de G (et de D, pour le schema de l'application) vers un fichier autonome."""
    ckpt = torch.load(Path(run_dir) / "last.pt", map_location="cpu", weights_only=False)
    cfg = ckpt["config"]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": ckpt["G"],
        "z_dim": cfg["z_dim"],
        "ngf": cfg["ngf"],
        "image_size": cfg.get("image_size", 64),
        "epochs": ckpt["epoch"] + 1,
        "run": Path(run_dir).name,
        "metrics": metrics or {},
        "ndf": cfg["ndf"],
        "discriminator": ckpt["D"] if with_discriminator else None,
    }, out)
    return out


def load_generator(path: str | Path) -> tuple[Generator, dict]:
    """Charge le generateur exporte ; retourne (modele en mode evaluation, informations)."""
    payload = torch.load(path, map_location="cpu", weights_only=False)
    G = Generator(payload["z_dim"], payload["ngf"], payload.get("image_size", 64))
    G.load_state_dict(payload["state_dict"])
    info = {k: v for k, v in payload.items() if k not in ("state_dict", "discriminator")}
    return G.eval(), info


def load_discriminator(path: str | Path) -> Discriminator | None:
    """Discriminateur exporte avec le generateur, ou None s'il n'a pas ete inclus."""
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("discriminator") is None:
        return None
    D = Discriminator(payload["ndf"], payload.get("image_size", 64))
    D.load_state_dict(payload["discriminator"])
    return D.eval()


@torch.no_grad()
def trace(G: Generator, seed: int, z_dim: int) -> tuple[np.ndarray, list[tuple[int, np.ndarray]], torch.Tensor]:
    """Suit une generation couche par couche, pour l'expliquer.

    Retourne le bruit z (z_dim valeurs), les cartes intermediaires apres chaque bloc
    (taille, moyenne des canaux normalisee dans [0, 1]) et l'image finale dans [-1, 1].
    """
    z = torch.randn(1, z_dim, 1, 1, generator=torch.Generator().manual_seed(seed))
    x, maps = z, []
    for layer in G.net:
        x = layer(x)
        if isinstance(layer, torch.nn.ReLU):
            m = x[0].mean(0)
            m = (m - m.min()) / (m.max() - m.min() + 1e-8)
            maps.append((m.shape[-1], m.numpy()))
    return z.view(-1).numpy(), maps, x


@torch.no_grad()
def realism(D: Discriminator, image: torch.Tensor) -> float:
    """Probabilite « vraie » donnee par le discriminateur a une image (1, 3, S, S) dans [-1, 1]."""
    return float(torch.sigmoid(D(image))[0])


@torch.no_grad()
def generate(G: Generator, n: int, seed: int, z_dim: int) -> np.ndarray:
    """``n`` images uint8 (n, S, S, 3), reproductibles pour une graine donnee."""
    z = torch.randn(n, z_dim, 1, 1, generator=torch.Generator().manual_seed(seed))
    images = G(z).clamp(-1, 1).add(1).mul(127.5).round().byte()
    return images.permute(0, 2, 3, 1).numpy()


def to_grid(images: np.ndarray, ncols: int, scale: int = 1, pad: int = 4) -> Image.Image:
    """Assemble les images en grille, agrandies d'un facteur ``scale`` (sans flou)."""
    n, h, w, _ = images.shape
    rows = int(np.ceil(n / ncols))
    canvas = np.full((rows * (h + pad) + pad, ncols * (w + pad) + pad, 3), 20, dtype=np.uint8)
    for k, img in enumerate(images):
        r, c = divmod(k, ncols)
        y, x = pad + r * (h + pad), pad + c * (w + pad)
        canvas[y:y + h, x:x + w] = img
    grid = Image.fromarray(canvas)
    return grid.resize((grid.width * scale, grid.height * scale), Image.Resampling.NEAREST) if scale > 1 else grid


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run_dir", type=Path, default=Path("runs/dcgan_64"))
    parser.add_argument("--metrics", type=Path, default=Path("reports/training/metrics.json"))
    parser.add_argument("--out", type=Path, default=Path("models/generator.pt"))
    parser.add_argument("--without_discriminator", action="store_true",
                        help="n'exporte que G (fichier plus leger, sans score du discriminateur dans l'application)")
    args = parser.parse_args()
    metrics = json.loads(args.metrics.read_text(encoding="utf-8")) if args.metrics.exists() else {}
    keep = {k: metrics[k] for k in ("fid", "fid_real", "kid", "n_train", "dataset") if k in metrics}
    path = export_generator(args.run_dir, args.out, keep, with_discriminator=not args.without_discriminator)
    print(f"Generateur exporte : {path} ({path.stat().st_size / 1e6:.1f} Mo)")


if __name__ == "__main__":
    main()
