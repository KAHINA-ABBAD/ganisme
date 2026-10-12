"""Telechargement et pretraitement des images selectionnees, avec reprise.

Le manifeste (un CSV, une ligne par image) est la source de verite. Chaque image
passe par l'un des statuts suivants :

- ``pending``   : a traiter ;
- ``processed`` : telechargee, validee, recadree et enregistree ;
- ``failed``    : erreur (HTTP, reseau, fichier illisible, image trop petite) ;
  retentee aux executions suivantes tant que ``attempts < max_attempts`` ;
- ``skipped``   : ecartee volontairement (doublon exact d'une autre image, ratio
  reel hors bornes).

Les originaux ne sont pas conserves : chaque image est recadree au centre en carre
puis redimensionnee en ``ARCHIVE_SIZE`` x ``ARCHIVE_SIZE``. Les resolutions
d'entrainement (64, 128) en sont derivees.

Usage : ``python -m ganisme.download --limit 50`` depuis la racine du projet,
avec ``PYTHONPATH=src``.
"""

import argparse
import hashlib
import io
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from PIL import Image

from ganisme.selection import MAX_RATIO, MIN_RATIO, select_paintings

ARCHIVE_SIZE = 256
MIN_SIDE = 256
USER_AGENT = "GANisme student project (La Plateforme) - educational use"

MANIFEST_COLUMNS = [
    "status", "attempts", "error", "http_status", "bytes", "sha1",
    "orig_width", "orig_height", "orig_mode", "local_path", "updated_at",
]


class DownloadError(Exception):
    """Erreur definitive ou temporaire lors de la recuperation d'une image."""

    def __init__(self, message: str, http_status: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.http_status = http_status
        self.retryable = retryable


def _read_with_deadline(response, deadline: float, chunk: int = 64 * 1024) -> bytes:
    """Lit la reponse par blocs et abandonne si le delai total est depasse.

    ``timeout`` d'``urlopen`` ne borne que chaque lecture : un serveur qui envoie
    les donnees au compte-gouttes bloquerait sinon le thread indefiniment.
    """
    parts = []
    while block := response.read(chunk):
        parts.append(block)
        if time.monotonic() > deadline:
            raise DownloadError("delai total depasse")
    return b"".join(parts)


def fetch(
    url: str, timeout: float = 15, total_timeout: float = 45, retries: int = 3, backoff: float = 2.0
) -> bytes:
    """Telecharge ``url`` et retourne son contenu, avec tentatives limitees.

    Chaque tentative est bornee par ``total_timeout`` secondes (plus au plus
    ``timeout`` pour la derniere lecture). Les erreurs 404/403 ne sont pas
    retentees ; les erreurs reseau, les delais depasses et les 5xx le sont avec
    une temporisation croissante.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            deadline = time.monotonic() + total_timeout
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                data = _read_with_deadline(response, deadline)
            if not content_type.startswith("image/"):
                raise DownloadError(f"content-type {content_type!r}", 200, retryable=False)
            if not data:
                raise DownloadError("reponse vide", 200)
            return data
        except urllib.error.HTTPError as error:
            failure = DownloadError(f"HTTP {error.code}", error.code, retryable=error.code >= 500)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            failure = DownloadError(f"reseau : {error}")
        except DownloadError as error:
            failure = error
        if not failure.retryable or attempt == retries - 1:
            raise failure
        time.sleep(backoff * 2**attempt)
    raise AssertionError("unreachable")


def center_square(image: Image.Image, size: int = ARCHIVE_SIZE) -> Image.Image:
    """Recadre au centre en carre puis redimensionne en ``size`` x ``size``."""
    width, height = image.size
    side = min(width, height)
    left, top = (width - side) // 2, (height - side) // 2
    square = image.crop((left, top, left + side, top + side))
    return square.resize((size, size), Image.Resampling.LANCZOS)


def process_bytes(data: bytes, size: int = ARCHIVE_SIZE) -> tuple[bytes, dict]:
    """Valide une image et retourne ``(jpeg_recadre, informations)``.

    Leve ``ValueError`` si l'image est illisible, trop petite ou a un ratio
    reel hors bornes (la cle ``skip`` de l'exception l'indique).
    """
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as error:  # Pillow leve des types d'erreurs varies
        raise ValueError(f"image illisible : {error}") from error
    info = {"orig_width": image.width, "orig_height": image.height, "orig_mode": image.mode}
    if min(image.size) < MIN_SIDE:
        raise ValueError(f"trop petite : {image.width}x{image.height}")
    ratio = image.width / image.height
    if not MIN_RATIO <= ratio <= MAX_RATIO:
        error = ValueError(f"ratio reel {ratio:.2f} hors [{MIN_RATIO}, {MAX_RATIO}]")
        error.skip = True
        raise error
    out = io.BytesIO()
    center_square(image.convert("RGB"), size).save(out, format="JPEG", quality=95)
    return out.getvalue(), info


def init_manifest(selection: pd.DataFrame) -> pd.DataFrame:
    """Cree un manifeste ``pending`` a partir de la selection."""
    manifest = selection.copy()
    for column in MANIFEST_COLUMNS:
        manifest[column] = pd.NA
    manifest["status"] = "pending"
    manifest["attempts"] = 0
    return manifest


def save_manifest(manifest: pd.DataFrame, path: Path) -> None:
    """Ecriture atomique : un fichier temporaire remplace l'ancien d'un coup."""
    tmp = path.with_suffix(".tmp")
    manifest.to_csv(tmp, index=False)
    os.replace(tmp, path)


def load_manifest(path: Path, image_dir: Path) -> pd.DataFrame:
    """Recharge le manifeste et remet en ``pending`` les images dont le fichier manque."""
    manifest = pd.read_csv(path)
    for column in ("error", "sha1", "local_path", "orig_mode", "updated_at"):
        manifest[column] = manifest[column].astype("object")
    lost = (manifest["status"] == "processed") & ~manifest["local_path"].map(
        lambda p: isinstance(p, str) and (image_dir / Path(p).name).exists()
    )
    manifest.loc[lost, "status"] = "pending"
    return manifest


def _work(row: dict, delay: float) -> dict:
    """Traite une image (execute dans un thread) ; ne modifie pas le manifeste."""
    result = {"image_id": row["image_id"], "attempts": row["attempts"] + 1}
    try:
        data = fetch(row["image_url"])
        result.update(bytes=len(data), http_status=200, sha1=hashlib.sha1(data).hexdigest())
        jpeg, info = process_bytes(data)
        result.update(info, status="processed", error=pd.NA, jpeg=jpeg)
    except DownloadError as error:
        result.update(status="failed", error=str(error), http_status=error.http_status)
    except ValueError as error:
        result.update(status="skipped" if getattr(error, "skip", False) else "failed", error=str(error))
    time.sleep(delay)  # politesse envers le serveur
    return result


def run(
    manifest_path: Path,
    image_dir: Path,
    limit: int | None = None,
    workers: int = 4,
    delay: float = 0.25,
    max_attempts: int = 3,
    save_every: int = 25,
) -> pd.DataFrame:
    """Traite les images ``pending`` (et ``failed`` retentables) du manifeste."""
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path, image_dir)
    todo = manifest[
        (manifest["status"] == "pending")
        | ((manifest["status"] == "failed") & (manifest["attempts"] < max_attempts))
    ]
    if limit is not None:
        todo = todo.head(limit)
    seen = set(manifest.loc[manifest["status"] == "processed", "sha1"].dropna())
    index_of = {image_id: i for i, image_id in zip(manifest.index, manifest["image_id"])}
    print(f"{len(todo)} images a traiter ({len(seen)} deja traitees)", flush=True)

    start, done = time.time(), 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_work, row, delay) for row in todo.to_dict("records")]
        for future in as_completed(futures):
            result = future.result()
            i = index_of[result.pop("image_id")]
            jpeg = result.pop("jpeg", None)
            if result["status"] == "processed":
                if result["sha1"] in seen:
                    result.update(status="skipped", error="doublon exact")
                else:
                    seen.add(result["sha1"])
                    path = image_dir / f"{manifest.at[i, 'image_id']:05d}.jpg"
                    path.write_bytes(jpeg)
                    result["local_path"] = path.as_posix()
            result["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for key, value in result.items():
                manifest.at[i, key] = value
            done += 1
            if done % save_every == 0:
                save_manifest(manifest, manifest_path)
                rate = done / (time.time() - start)
                print(f"{done}/{len(todo)} ({rate:.1f} img/s) "
                      f"{manifest['status'].value_counts().to_dict()}", flush=True)
    save_manifest(manifest, manifest_path)
    print("Termine :", manifest["status"].value_counts().to_dict(), flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=Path("data/processed/manifest.csv"))
    parser.add_argument("--images", type=Path, default=Path(f"data/processed/images_{ARCHIVE_SIZE}"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--features", type=Path, default=Path("data/processed/paintings_metadata.csv"),
                        help="sortie de 01_eda, utilisee si le manifeste n'existe pas encore")
    args = parser.parse_args()
    if not args.manifest.exists():
        selection = select_paintings(pd.read_csv(args.features))
        save_manifest(init_manifest(selection), args.manifest)
        print(f"Manifeste cree : {len(selection)} images -> {args.manifest}")
    run(args.manifest, args.images, limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    main()
