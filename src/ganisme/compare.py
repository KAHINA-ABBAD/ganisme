"""Compare plusieurs generateurs sur le MEME jeu d'evaluation, avec le meme protocole.

Le FID depend du nombre d'images et du jeu de reference : des valeurs obtenues sur des jeux
d'evaluation differents ne se comparent pas. Ce script evalue chaque generateur contre le
meme ensemble de vraies peintures, avec le meme nombre d'images generees.

Usage : ``python -m ganisme.compare --runs runs/dcgan_64_v0 runs/dcgan_64``
"""

import argparse
import json
from pathlib import Path

import numpy as np

from ganisme.dcgan import load_split, to_tensor
from ganisme.evaluate import features, fid, generate, inception, kid, load_generator


def compare(runs: list[Path], data: Path) -> dict:
    eval_real = load_split(data, "eval")
    train_real = load_split(data, "train")
    n = len(eval_real)
    model = inception()
    f_eval = features(model, to_tensor(eval_real))
    ref_idx = np.random.default_rng(0).choice(len(train_real), n, replace=False)
    f_ref = features(model, to_tensor(train_real[ref_idx]))
    results = {"reference (reel vs reel)": {"fid": fid(f_ref, f_eval), "kid": kid(f_ref, f_eval)[0]},
               "n_eval": n, "dataset": data.name}
    for run in runs:
        G, ckpt = load_generator(run)
        f_gen = features(model, generate(G, n, ckpt["config"]["z_dim"]))
        kid_mean, kid_std = kid(f_gen, f_eval)
        results[run.name] = {"fid": fid(f_gen, f_eval), "kid": kid_mean, "kid_std": kid_std,
                             "epochs": int(ckpt["epoch"] + 1), "iterations": int(ckpt["iteration"])}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--data", type=Path, default=Path("data/processed/dataset_64_v1.npz"))
    parser.add_argument("--out", type=Path, default=Path("reports/training/comparison.json"))
    args = parser.parse_args()
    results = compare(args.runs, args.data)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
