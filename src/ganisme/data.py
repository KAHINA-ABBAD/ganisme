"""Fonctions simples de chargement et de preparation des donnees."""

from pathlib import Path

import pandas as pd


def clean_data(data: pd.DataFrame) -> pd.DataFrame:
    """Nettoie les noms de colonnes et retire les lignes entierement vides."""
    cleaned = data.copy()
    cleaned.columns = cleaned.columns.astype(str).str.strip()
    return cleaned.dropna(how="all").reset_index(drop=True)


def load_csv(path: str | Path) -> pd.DataFrame:
    """Charge un CSV et applique le nettoyage de base."""
    return clean_data(pd.read_csv(path))