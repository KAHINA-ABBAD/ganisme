"""Evaluation du generateur : FID, KID, plus proches voisins et figures d'entrainement.

Les caracteristiques sont extraites par Inception v3 (torchvision, poids ImageNet). Les
valeurs ne sont donc pas directement comparables a celles des articles (qui utilisent
les poids TensorFlow), mais elles le sont entre nos propres experiences.

Usage : ``python -m ganisme.evaluate --run_dir runs/dcgan_64`` (avec ``PYTHONPATH=src``).
"""

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from PIL import Image
from scipy import linalg
from torch.nn import functional as F
from torchvision.models import Inception_V3_Weights, inception_v3

from ganisme.dcgan import Generator, load_split, to_tensor

MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def inception():
    model = inception_v3(weights=Inception_V3_Weights.IMAGENET1K_V1, aux_logits=True)
    model.fc = torch.nn.Identity()  # sortie : vecteur de 2048 caracteristiques
    return model.eval()


@torch.no_grad()
def features(model, images: torch.Tensor, batch: int = 64) -> np.ndarray:
    """Images dans [-1, 1], (n, 3, h, w) -> caracteristiques Inception (n, 2048)."""
    out = []
    for i in range(0, len(images), batch):
        x = (images[i:i + batch] + 1) / 2
        x = F.interpolate(x, size=(299, 299), mode="bilinear", align_corners=False)
        out.append(model((x - MEAN) / STD).numpy())
    return np.concatenate(out)


def fid(a: np.ndarray, b: np.ndarray) -> float:
    """Distance de Frechet entre deux nuages de caracteristiques (gaussiennes)."""
    mu_a, mu_b = a.mean(0), b.mean(0)
    cov_a, cov_b = np.cov(a, rowvar=False), np.cov(b, rowvar=False)
    covmean = np.real(linalg.sqrtm(cov_a @ cov_b))
    return float(((mu_a - mu_b) ** 2).sum() + np.trace(cov_a + cov_b - 2 * covmean))


def kid(a: np.ndarray, b: np.ndarray, subsets: int = 50, size: int = 500, seed: int = 0) -> tuple[float, float]:
    """KID (Binkowski et al., 2018) : MMD non biaise, noyau polynomial cubique. (moyenne, ecart-type)."""
    rng = np.random.default_rng(seed)
    # Sous-ensembles plus petits que les jeux, sinon chaque tirage est identique (ecart-type nul).
    size = min(size, len(a) // 2, len(b) // 2)
    d = a.shape[1]
    values = []
    for _ in range(subsets):
        x, y = a[rng.choice(len(a), size, replace=False)], b[rng.choice(len(b), size, replace=False)]
        kxx, kyy, kxy = ((x @ x.T) / d + 1) ** 3, ((y @ y.T) / d + 1) ** 3, ((x @ y.T) / d + 1) ** 3
        n = size
        values.append((kxx.sum() - np.trace(kxx)) / (n * (n - 1)) + (kyy.sum() - np.trace(kyy)) / (n * (n - 1))
                      - 2 * kxy.mean())
    return float(np.mean(values)), float(np.std(values))


def load_generator(run_dir: Path) -> tuple[Generator, dict]:
    ckpt = torch.load(run_dir / "last.pt", map_location="cpu", weights_only=False)
    cfg = ckpt["config"]
    G = Generator(cfg["z_dim"], cfg["ngf"], cfg.get("image_size", 64))
    G.load_state_dict(ckpt["G"])
    return G.eval(), ckpt


@torch.no_grad()
def generate(G: Generator, n: int, z_dim: int, seed: int = 123) -> torch.Tensor:
    z = torch.randn(n, z_dim, 1, 1, generator=torch.Generator().manual_seed(seed))
    return torch.cat([G(z[i:i + 256]) for i in range(0, n, 256)])


def to_uint8(images: torch.Tensor) -> np.ndarray:
    return ((images.clamp(-1, 1) + 1) * 127.5).round().byte().permute(0, 2, 3, 1).numpy()


def grid(images: np.ndarray, ncols: int, pad: int = 2) -> Image.Image:
    n, h, w, _ = images.shape
    rows = int(np.ceil(n / ncols))
    canvas = np.full((rows * (h + pad) + pad, ncols * (w + pad) + pad, 3), 20, dtype=np.uint8)
    for k, img in enumerate(images):
        r, c = divmod(k, ncols)
        canvas[pad + r * (h + pad):pad + r * (h + pad) + h, pad + c * (w + pad):pad + c * (w + pad) + w] = img
    return Image.fromarray(canvas)


def plot_losses(history: list[dict], path: Path):
    it = np.array([h["iteration"] for h in history])
    window = max(1, len(history) // 100)

    def smooth(key):
        values = np.array([h[key] for h in history])
        return np.convolve(values, np.ones(window) / window, mode="valid")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    x = it[window - 1:]
    axes[0].plot(x, smooth("loss_d"), label="discriminateur", color="#c0505c")
    axes[0].plot(x, smooth("loss_g"), label="générateur", color="#d4a84b")
    axes[0].set_title("Pertes (moyenne glissante)")
    axes[0].set_xlabel("Itération")
    axes[0].set_ylabel("Entropie croisée binaire")
    axes[0].legend()
    axes[1].plot(x, smooth("d_real"), label="D(x) : vraies", color="#2a6fdb")
    axes[1].plot(x, smooth("d_fake"), label="D(G(z)) : générées", color="#e07b39")
    axes[1].axhline(0.5, color="grey", ls="--", lw=1, label="équilibre (0,5)")
    axes[1].set_ylim(0, 1)
    axes[1].set_title("Réponse moyenne du discriminateur")
    axes[1].set_xlabel("Itération")
    axes[1].set_ylabel("Probabilité « vraie »")
    axes[1].legend()
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def progression(samples_dir: Path, path: Path, per_row: int = 8, size: int = 64):
    """Une ligne par epoque choisie : les memes z, de la 1re a la derniere epoque."""
    files = sorted(samples_dir.glob("epoch_*.png"))
    picks = sorted({0, len(files) // 4, len(files) // 2, 3 * len(files) // 4, len(files) - 1})
    rows = []
    for k in picks:
        img = np.asarray(Image.open(files[k]).convert("RGB"))
        rows.append(img[:size + 2, :per_row * (size + 2)])  # premiere ligne de la grille (image + bordure 2 px)
    fig, axes = plt.subplots(len(rows), 1, figsize=(8, 1.25 * len(rows)))
    for ax, k, row in zip(np.atleast_1d(axes), picks, rows):
        ax.imshow(row)
        ax.set_ylabel(f"ép. {k + 1}", rotation=0, labelpad=28, va="center")
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("Mêmes vecteurs z, au fil des époques")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def evaluate(run_dir: Path, data: Path, out_dir: Path, n_neighbors: int = 6) -> dict:
    start = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    G, ckpt = load_generator(run_dir)
    cfg = ckpt["config"]
    train_real = load_split(data, "train")
    eval_real = load_split(data, "eval")
    n = len(eval_real)
    if n < 100:
        raise ValueError(f"jeu d'evaluation trop petit ({n} images) pour un FID interpretable")
    gen = generate(G, n, cfg["z_dim"])

    model = inception()
    f_eval = features(model, to_tensor(eval_real))
    f_gen = features(model, gen)
    rng = np.random.default_rng(0)
    ref_idx = rng.choice(len(train_real), n, replace=False)
    f_ref = features(model, to_tensor(train_real[ref_idx]))
    kid_mean, kid_std = kid(f_gen, f_eval)
    kid_ref, _ = kid(f_ref, f_eval)

    # Plus proches voisins (cosinus sur les caracteristiques Inception) parmi les images d'entrainement.
    f_train = features(model, to_tensor(train_real))
    a = f_gen[:n_neighbors] / np.linalg.norm(f_gen[:n_neighbors], axis=1, keepdims=True)
    b = f_train / np.linalg.norm(f_train, axis=1, keepdims=True)
    sims = a @ b.T
    nearest = sims.argmax(1)
    s = train_real.shape[1]
    k = 3 if s == 64 else 2  # agrandissement pour la lisibilite des figures
    pairs = np.stack([to_uint8(gen[:n_neighbors]), train_real[nearest]], axis=1).reshape(-1, s, s, 3)
    g = grid(pairs, ncols=2)
    g.resize((g.width * k, g.height * k), Image.NEAREST).save(out_dir / "nearest_neighbors.png")
    g = grid(to_uint8(gen[:64]), ncols=8)
    g.resize((g.width * k, g.height * k), Image.NEAREST).save(out_dir / "samples.png")
    plot_losses(ckpt["history"], out_dir / "losses.png")
    progression(run_dir / "samples", out_dir / "progression.png", size=train_real.shape[1])

    metrics = {
        "fid": fid(f_gen, f_eval),
        "fid_real": fid(f_ref, f_eval),
        "kid": kid_mean, "kid_std": kid_std, "kid_real": kid_ref,
        "nearest_cosine_mean": float(sims.max(1).mean()),
        "dataset": Path(data).name, "n_eval": int(n), "n_train": int(len(train_real)),
        "epochs": int(ckpt["epoch"] + 1), "iterations": int(ckpt["iteration"]),
        "hyperparams": {k: cfg[k] for k in ("epochs", "batch_size", "z_dim", "lr", "beta1", "ngf", "ndf", "hflip")},
        "protocol": f"Inception v3 torchvision (ImageNet), images {train_real.shape[1]}x{train_real.shape[1]} redimensionnees en 299x299 ; "
                    "genere vs jeu d'evaluation ; reference = sous-ensemble d'entrainement de meme taille vs evaluation",
        "duration_s": round(time.time() - start, 1),
    }
    if not all(np.isfinite([metrics["fid"], metrics["fid_real"], metrics["kid"]])):
        raise FloatingPointError(f"metrique non finie : {metrics}")
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run_dir", type=Path, default=Path("runs/dcgan_64"))
    parser.add_argument("--data", type=Path, default=Path("data/processed/dataset_64_v1.npz"))
    parser.add_argument("--out", type=Path, default=Path("reports/training"))
    args = parser.parse_args()
    metrics = evaluate(args.run_dir, args.data, args.out / "figures")
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k != "protocol"}, indent=2))


if __name__ == "__main__":
    main()
