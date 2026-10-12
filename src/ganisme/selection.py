"""Selection reproductible du sous-ensemble de peintures a telecharger (phase 2).

Les criteres viennent de l'EDA (notebooks/01_eda.ipynb) :
- pas de vues de detail ni de fresques ;
- ratio largeur/hauteur dans [0.5, 2] quand les dimensions sont connues ;
- une seule ligne par oeuvre (``work_key``) pour limiter les quasi-doublons ;
- un plafond de peintures par artiste ;
- des quotas par genre equilibres ("water-filling") : chaque genre recoit la meme
  part, les genres rares sont pris en entier et leur reliquat est redistribue.
"""

import hashlib

import numpy as np
import pandas as pd

MIN_RATIO, MAX_RATIO = 0.5, 2.0


def balanced_quotas(available: pd.Series, total: int) -> pd.Series:
    """Repartit ``total`` entre les groupes le plus equitablement possible.

    Un groupe ne peut pas recevoir plus que ``available``. Si la somme disponible
    est inferieure a ``total``, chaque groupe est pris en entier.
    """
    available = available.astype(int)
    if available.sum() <= total:
        return available.copy()
    quotas = pd.Series(0, index=available.index)
    remaining = total
    open_groups = list(available.sort_values().index)
    while open_groups:
        share = remaining // len(open_groups)
        smallest = open_groups[0]
        if available[smallest] <= share:
            quotas[smallest] = available[smallest]
            remaining -= available[smallest]
            open_groups.pop(0)
            continue
        quotas[open_groups] = share
        # Reste de la division entiere : une unite de plus aux plus grands groupes.
        for group in open_groups[::-1][: remaining - share * len(open_groups)]:
            quotas[group] += 1
        break
    return quotas


def split_of(work_key: str, eval_share: float = 0.1) -> str:
    """Affecte une oeuvre a ``train`` ou ``eval`` de facon deterministe.

    Le hachage de ``work_key`` ne depend ni de l'ordre des lignes ni de la graine :
    une oeuvre reste toujours du meme cote, ce qui evite les fuites.
    """
    digest = hashlib.sha1(work_key.encode("utf-8")).hexdigest()
    return "eval" if int(digest[:8], 16) / 0xFFFFFFFF < eval_share else "train"


def select_paintings(
    paintings: pd.DataFrame,
    n: int = 8000,
    max_per_artist: int = 30,
    seed: int = 42,
    eval_share: float = 0.1,
    types: list[str] | None = None,
) -> pd.DataFrame:
    """Retourne ``n`` peintures (ou moins si les candidats manquent).

    ``paintings`` est la sortie de ``ganisme.eda.add_features`` filtree sur les
    peintures. ``types`` restreint la selection a certains genres (jeu homogene).
    """
    if types is not None:
        paintings = paintings[paintings["TYPE"].isin(types)]
    ratio = paintings["aspect_ratio"]
    candidates = paintings[
        ~paintings["is_detail"].astype(bool)
        & (paintings["technique_family"] != "fresco")
        & (ratio.isna() | ratio.between(MIN_RATIO, MAX_RATIO))
    ]
    # Melange unique et seede : toutes les etapes suivantes gardent cet ordre.
    shuffled = candidates.sample(frac=1, random_state=seed)
    shuffled = shuffled.drop_duplicates("work_key")
    shuffled = shuffled.groupby("AUTHOR", sort=False).head(max_per_artist)

    quotas = balanced_quotas(shuffled["TYPE"].value_counts(), n)
    selected = pd.concat(
        shuffled[shuffled["TYPE"] == genre].head(quota)
        for genre, quota in quotas.items()
    )
    selected = selected.sort_values("URL").reset_index(drop=True)
    selected["split"] = selected["work_key"].map(
        lambda key: split_of(key, eval_share)
    )
    selected.insert(0, "image_id", np.arange(len(selected)))
    return selected
