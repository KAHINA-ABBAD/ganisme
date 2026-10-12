"""Extraction de variables a partir des metadonnees du catalogue Web Gallery of Art.

Les champs du catalogue sont du texte libre (``DATE``, ``TECHNIQUE``, ``BORN-DIED``).
Ces fonctions en tirent des valeurs numeriques ou categorielles exploitables pour
l'EDA et pour la selection du sous-ensemble d'entrainement.
"""

import re

import numpy as np
import pandas as pd

_YEAR = re.compile(r"(?<!\d)(\d{3,4})(?!\d)")
_CENTURY = re.compile(r"(\d{1,2})(?:st|nd|rd|th) century", re.IGNORECASE)
_DIMENSIONS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*cm", re.IGNORECASE
)
_BORN = re.compile(r"b\.\s*(?:ca?\.\s*)?(\d{3,4})")
_DIED = re.compile(r"d\.\s*(?:ca?\.\s*)?(\d{3,4})")
_DETAIL = re.compile(r"\s*\(detail[^)]*\)", re.IGNORECASE)


def parse_year(date: str) -> float:
    """Retourne la premiere annee citee dans ``DATE``, ou NaN si inconnue.

    ``"1648-50"`` et ``"c. 1648"`` donnent 1648. Un siecle seul
    (``"15th century"``) donne son milieu, 1450. ``"-"`` donne NaN.
    """
    match = _YEAR.search(date)
    if match:
        return float(match.group(1))
    match = _CENTURY.search(date)
    if match:
        return (int(match.group(1)) - 1) * 100 + 50.0
    return np.nan


def parse_dimensions(technique: str) -> tuple[float, float]:
    """Retourne ``(hauteur_cm, largeur_cm)`` lues dans ``TECHNIQUE``.

    Le catalogue suit la convention hauteur x largeur. Sans dimensions en cm
    (fresques, tondi indiques par un diametre, etc.), retourne ``(NaN, NaN)``.
    """
    match = _DIMENSIONS.search(technique)
    if not match:
        return np.nan, np.nan
    height, width = (float(value.replace(",", ".")) for value in match.groups())
    return height, width


def technique_family(technique: str) -> str:
    """Regroupe ``TECHNIQUE`` en grandes familles de medium."""
    text = technique.lower()
    for family, keywords in (
        ("fresco", ("fresco", "mural")),
        ("tempera", ("tempera",)),
        ("oil", ("oil",)),
        ("watercolour", ("watercolour", "watercolor", "gouache")),
        ("pastel", ("pastel",)),
    ):
        if any(keyword in text for keyword in keywords):
            return family
    return "other"


def parse_life(born_died: str) -> tuple[float, float]:
    """Retourne ``(naissance, deces)`` lus dans ``BORN-DIED``, NaN si absents."""
    born = _BORN.search(born_died)
    died = _DIED.search(born_died)
    return (
        float(born.group(1)) if born else np.nan,
        float(died.group(1)) if died else np.nan,
    )


def work_key(author: str, title: str) -> str:
    """Identifiant d'oeuvre commun a une oeuvre et a ses vues de detail."""
    return f"{author.strip()}|{_DETAIL.sub('', title).strip().lower()}"


def image_url(page_url: str) -> str:
    """Deduit l'URL de l'image a partir de la page HTML de l'oeuvre.

    Hypothese a confirmer en phase 2 : ``/html/a/x.html`` -> ``/art/a/x.jpg``.
    """
    return page_url.replace("/html/", "/art/", 1).removesuffix(".html") + ".jpg"


def add_features(data: pd.DataFrame) -> pd.DataFrame:
    """Ajoute au catalogue les variables derivees utilisees par l'EDA."""
    features = data.copy()
    features["year"] = features["DATE"].map(parse_year)
    dims = features["TECHNIQUE"].map(parse_dimensions)
    features["height_cm"] = dims.str[0]
    features["width_cm"] = dims.str[1]
    features["aspect_ratio"] = features["width_cm"] / features["height_cm"]
    features["technique_family"] = features["TECHNIQUE"].map(technique_family)
    life = features["BORN-DIED"].map(parse_life)
    features["artist_born"] = life.str[0]
    features["artist_died"] = life.str[1]
    features["is_detail"] = features["TITLE"].str.contains(
        "(detail", case=False, regex=False
    )
    features["work_key"] = [
        work_key(author, title)
        for author, title in zip(features["AUTHOR"], features["TITLE"])
    ]
    features["image_url"] = features["URL"].map(image_url)
    return features
