"""Chargement des images pretraitees et indicateurs simples pour les controler."""

from pathlib import Path

import numpy as np
from PIL import Image


def load_images(paths: list[str | Path], size: int) -> np.ndarray:
    """Charge des images RGB redimensionnees en ``(n, size, size, 3)`` uint8."""
    array = np.empty((len(paths), size, size, 3), dtype=np.uint8)
    for i, path in enumerate(paths):
        with Image.open(path) as image:
            image = image.convert("RGB")
            if image.size != (size, size):
                image = image.resize((size, size), Image.Resampling.LANCZOS)
            array[i] = np.asarray(image)
    return array


def saturation(images: np.ndarray) -> np.ndarray:
    """Saturation moyenne (0-1, au sens HSV) de chaque image ``(n, h, w, 3)``."""
    rgb = images.astype(np.float32) / 255
    high, low = rgb.max(axis=-1), rgb.min(axis=-1)
    sat = np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0)
    return sat.mean(axis=(1, 2))


def brightness(images: np.ndarray) -> np.ndarray:
    """Luminance moyenne (0-1) de chaque image ``(n, h, w, 3)``."""
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return (images.astype(np.float32) / 255 @ weights).mean(axis=(1, 2))


def average_hash(images: np.ndarray, hash_size: int = 8) -> np.ndarray:
    """Empreinte perceptuelle (aHash) de chaque image, sous forme d'entier.

    Deux images quasi identiques (meme oeuvre, recadrage ou compression
    differents) ont des empreintes egales ou tres proches.
    """
    gray = images.astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    n, height, width = gray.shape
    blocks = gray.reshape(n, hash_size, height // hash_size, hash_size, width // hash_size)
    small = blocks.mean(axis=(2, 4)).reshape(n, -1)
    bits = small > small.mean(axis=1, keepdims=True)
    return bits @ (1 << np.arange(hash_size * hash_size, dtype=np.uint64))


def hamming(a: np.ndarray, b: int) -> np.ndarray:
    """Distance de Hamming entre les empreintes ``a`` et l'empreinte ``b``."""
    xor = np.bitwise_xor(a.astype(np.uint64), np.uint64(b))
    return np.array([bin(int(value)).count("1") for value in xor])


def near_duplicate_pairs(hashes: np.ndarray, max_distance: int = 2, chunk: int = 1024) -> np.ndarray:
    """Paires ``(i, j)``, ``i < j``, d'empreintes a distance de Hamming <= ``max_distance``."""
    bits = np.unpackbits(hashes.astype(">u8").view(np.uint8).reshape(len(hashes), 8), axis=1)
    bits = bits.astype(np.float32)
    pairs = []
    for start in range(0, len(bits), chunk):
        block = bits[start:start + chunk]
        # Hamming = bits differents = |a| + |b| - 2 a.b
        dist = block.sum(1, keepdims=True) + bits.sum(1) - 2 * block @ bits.T
        i, j = np.nonzero(dist <= max_distance)
        i = i + start
        keep = i < j
        pairs.append(np.stack([i[keep], j[keep]], axis=1))
    return np.concatenate(pairs) if pairs else np.empty((0, 2), dtype=int)


def confirm_pairs(images: np.ndarray, pairs: np.ndarray, max_mean_diff: float = 10.0) -> np.ndarray:
    """Garde les paires dont l'ecart moyen absolu des pixels (0-255) est <= ``max_mean_diff``.

    L'empreinte aHash 8x8 seule rapproche beaucoup d'images differentes ayant la
    meme repartition clair/sombre (ciel clair en haut, sol sombre en bas) : elle
    sert a proposer des candidats, la comparaison des pixels a confirmer.
    """
    if len(pairs) == 0:
        return pairs
    diff = np.array([np.abs(images[i].astype(np.int16) - images[j].astype(np.int16)).mean() for i, j in pairs])
    return pairs[diff <= max_mean_diff]
