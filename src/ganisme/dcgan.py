"""DCGAN 64x64 ou 128x128 (Radford et al., 2015) : modele, entrainement reprenable, echantillons.

Usage, depuis la racine du projet avec ``PYTHONPATH=src`` :

    python -m ganisme.dcgan --epochs 25

L'entrainement reprend automatiquement depuis ``runs/<nom>/last.pt`` s'il existe.
"""

import argparse
import json
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from torchvision.utils import save_image


@dataclass
class Config:
    data: str = "data/processed/dataset_64_v1.npz"
    run_dir: str = "runs/dcgan_64"
    epochs: int = 25
    batch_size: int = 128
    z_dim: int = 100
    ngf: int = 64
    ndf: int = 64
    lr: float = 2e-4
    beta1: float = 0.5
    seed: int = 42
    n_fixed: int = 64
    hflip: bool = True
    image_size: int = 64
    images: str = ""      # dossier d'images (pipeline du cours) ; vide = fichier .npz
    num_workers: int = 0


class Generator(nn.Module):
    """z (z_dim x 1 x 1) -> image 3 x S x S dans [-1, 1], S = 64 ou 128."""

    def __init__(self, z_dim: int = 100, ngf: int = 64, image_size: int = 64):
        super().__init__()
        if image_size not in (64, 128):
            raise ValueError("image_size doit valoir 64 ou 128")

        def up(cin, cout):
            return [nn.ConvTranspose2d(cin, cout, 4, 2, 1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(True)]

        mult = image_size // 8  # 8 en 64x64, 16 en 128x128
        layers = [nn.ConvTranspose2d(z_dim, ngf * mult, 4, 1, 0, bias=False), nn.BatchNorm2d(ngf * mult), nn.ReLU(True)]  # 4x4
        while mult > 1:  # 8x8, 16x16, 32x32 (puis 64x64 en 128)
            layers += up(ngf * mult, ngf * mult // 2)
            mult //= 2
        layers += [nn.ConvTranspose2d(ngf, 3, 4, 2, 1, bias=False), nn.Tanh()]  # taille finale
        self.net = nn.Sequential(*layers)

    def forward(self, z):
        return self.net(z)


class Discriminator(nn.Module):
    """Image 3 x S x S -> logit (probabilite d'etre vraie apres sigmoide)."""

    def __init__(self, ndf: int = 64, image_size: int = 64):
        super().__init__()

        def down(cin, cout, bn=True):
            layers = [nn.Conv2d(cin, cout, 4, 2, 1, bias=False)]
            if bn:
                layers.append(nn.BatchNorm2d(cout))
            return layers + [nn.LeakyReLU(0.2, inplace=True)]

        layers, mult, size = down(3, ndf, bn=False), 1, image_size // 2
        while size > 4:  # divise par deux jusqu'a 4x4
            layers += down(ndf * mult, ndf * mult * 2)
            mult, size = mult * 2, size // 2
        layers.append(nn.Conv2d(ndf * mult, 1, 4, 1, 0, bias=False))  # 1x1 : un logit par image
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x).view(-1)


def init_weights(module):
    """Initialisation du papier DCGAN : N(0, 0.02), BatchNorm N(1, 0.02)."""
    if isinstance(module, (nn.Conv2d, nn.ConvTranspose2d)):
        nn.init.normal_(module.weight, 0.0, 0.02)
    elif isinstance(module, nn.BatchNorm2d):
        nn.init.normal_(module.weight, 1.0, 0.02)
        nn.init.zeros_(module.bias)


def to_tensor(images: np.ndarray) -> torch.Tensor:
    """uint8 (n, h, w, 3) -> float (n, 3, h, w) dans [-1, 1]."""
    return torch.from_numpy(images).permute(0, 3, 1, 2).float().div(127.5).sub(1.0)


def load_split(path: str | Path, split: str) -> np.ndarray:
    with np.load(path) as data:
        mask = data["split"] == split
        return data["images"][mask]


def seed_everything(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def save_checkpoint(state: dict, path: Path):
    """Ecriture sure : fichier temporaire, verifie en le relisant, puis remplacement."""
    tmp = path.with_suffix(".tmp")
    torch.save(state, tmp)
    torch.load(tmp, map_location="cpu", weights_only=False)  # leve une erreur si le fichier est corrompu
    os.replace(tmp, path)


def grad_norm(model: nn.Module) -> float:
    norms = [p.grad.detach().norm() for p in model.parameters() if p.grad is not None]
    return float(torch.norm(torch.stack(norms))) if norms else 0.0


def train(cfg: Config, max_iters: int | None = None) -> dict:
    """Entraine (ou reprend) le DCGAN. ``max_iters`` limite le nombre d'iterations (tests)."""
    run = Path(cfg.run_dir)
    (run / "samples").mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    seed_everything(cfg.seed)

    if cfg.images:  # pipeline du cours : dossier d'images + transforms (le miroir est dans les transforms)
        from ganisme.pipeline import PaintingDataset, make_transform
        dataset = PaintingDataset(Path(cfg.images) / "train", make_transform(cfg.image_size, hflip=cfg.hflip))
        apply_flip = False
    else:
        dataset = TensorDataset(to_tensor(load_split(cfg.data, "train")))
        apply_flip = cfg.hflip
    if len(dataset) == 0:
        raise ValueError(f"aucune image d'entrainement dans {cfg.images or cfg.data}")
    loader = DataLoader(dataset, batch_size=cfg.batch_size, shuffle=True, drop_last=True,
                        num_workers=cfg.num_workers, persistent_workers=cfg.num_workers > 0)
    if len(loader) == 0:
        raise ValueError(f"{len(dataset)} images : moins qu'un lot de {cfg.batch_size}")

    G = Generator(cfg.z_dim, cfg.ngf, cfg.image_size).to(device)
    D = Discriminator(cfg.ndf, cfg.image_size).to(device)
    G.apply(init_weights)
    D.apply(init_weights)
    opt_g = torch.optim.Adam(G.parameters(), lr=cfg.lr, betas=(cfg.beta1, 0.999))
    opt_d = torch.optim.Adam(D.parameters(), lr=cfg.lr, betas=(cfg.beta1, 0.999))
    bce = nn.BCEWithLogitsLoss()
    fixed_z = torch.randn(cfg.n_fixed, cfg.z_dim, 1, 1, generator=torch.Generator().manual_seed(cfg.seed)).to(device)

    history, start_epoch, it = [], 0, 0
    last = run / "last.pt"
    if last.exists():
        ckpt = torch.load(last, map_location=device, weights_only=False)
        G.load_state_dict(ckpt["G"])
        D.load_state_dict(ckpt["D"])
        opt_g.load_state_dict(ckpt["opt_g"])
        opt_d.load_state_dict(ckpt["opt_d"])
        history, start_epoch, it = ckpt["history"], ckpt["epoch"] + 1, ckpt["iteration"]
        torch.set_rng_state(ckpt["rng_torch"])
        np.random.set_state(ckpt["rng_numpy"])
        random.setstate(ckpt["rng_python"])
        print(f"Reprise a l'epoque {start_epoch} (iteration {it})", flush=True)
    (run / "config.json").write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")

    epochs_done = start_epoch  # reste valable si l'entrainement etait deja termine
    for epoch in range(start_epoch, cfg.epochs):
        t0 = time.time()
        G.train()
        D.train()
        for batch in loader:
            x = (batch[0] if isinstance(batch, (list, tuple)) else batch).to(device)
            if apply_flip:
                flip = torch.rand(x.size(0), device=device) < 0.5
                x = torch.where(flip[:, None, None, None], x.flip(3), x)
            b = x.size(0)
            ones, zeros = torch.ones(b, device=device), torch.zeros(b, device=device)

            # Pas 1 : D apprend (G fige grace a detach)
            z = torch.randn(b, cfg.z_dim, 1, 1, device=device)
            fake = G(z)
            opt_d.zero_grad()
            out_real, out_fake = D(x), D(fake.detach())
            loss_d = bce(out_real, ones) + bce(out_fake, zeros)
            loss_d.backward()
            gn_d = grad_norm(D)
            opt_d.step()

            # Pas 2 : G apprend a tromper D (perte non saturante -log D(G(z)))
            opt_g.zero_grad()
            out_gen = D(fake)
            loss_g = bce(out_gen, ones)
            loss_g.backward()
            gn_g = grad_norm(G)
            opt_g.step()

            values = [loss_d.item(), loss_g.item(), gn_d, gn_g]
            if not all(np.isfinite(values)):
                raise FloatingPointError(f"valeur non finie a l'iteration {it} : {values}")
            history.append({
                "iteration": it, "epoch": epoch, "loss_d": values[0], "loss_g": values[1],
                "d_real": torch.sigmoid(out_real).mean().item(), "d_fake": torch.sigmoid(out_fake).mean().item(),
                "grad_d": gn_d, "grad_g": gn_g,
            })
            it += 1
            if max_iters is not None and it >= max_iters:
                break

        G.eval()
        with torch.no_grad():
            save_image(G(fixed_z), run / "samples" / f"epoch_{epoch:03d}.png", nrow=8, normalize=True, value_range=(-1, 1))
        save_checkpoint({
            "G": G.state_dict(), "D": D.state_dict(), "opt_g": opt_g.state_dict(), "opt_d": opt_d.state_dict(),
            "epoch": epoch, "iteration": it, "history": history, "config": asdict(cfg),
            "rng_torch": torch.get_rng_state(), "rng_numpy": np.random.get_state(), "rng_python": random.getstate(),
        }, last)
        recent = history[-len(loader):]
        print(f"epoque {epoch + 1}/{cfg.epochs} - {time.time() - t0:.0f}s - "
              f"loss_d {np.mean([h['loss_d'] for h in recent]):.3f} loss_g {np.mean([h['loss_g'] for h in recent]):.3f} "
              f"D(x) {np.mean([h['d_real'] for h in recent]):.2f} D(G(z)) {np.mean([h['d_fake'] for h in recent]):.2f}",
              flush=True)
        epochs_done = epoch + 1
        if max_iters is not None and it >= max_iters:
            break
    (run / "history.json").write_text(json.dumps(history), encoding="utf-8")
    return {"iterations": it, "epochs_done": epochs_done, "n_train": len(dataset), "history": history}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for field, value in asdict(Config()).items():
        kind = type(value)
        if kind is bool:
            parser.add_argument(f"--{field}", type=lambda s: s.lower() in ("1", "true", "oui"), default=value)
        else:
            parser.add_argument(f"--{field}", type=kind, default=value)
    train(Config(**vars(parser.parse_args())))


if __name__ == "__main__":
    main()
