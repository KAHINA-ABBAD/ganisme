"""GANisme a l'infini : une peinture a la fois, et le chemin qu'elle a suivi dans le GAN.

Lancement depuis la racine du projet :

    streamlit run app.py
"""

import io
import random
import sys
from pathlib import Path

import numpy as np
import streamlit as st
from matplotlib import colormaps
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ganisme.generate import load_discriminator, load_generator, realism, trace  # noqa: E402

MODELS = {  # libelle -> fichier exporte par ganisme.generate (seuls les fichiers presents sont proposes)
    "Portraits": ROOT / "models" / "generator_portraits_64.pt",
    "Tous les genres": ROOT / "models" / "generator.pt",
    "Portraits 128 px (essai)": ROOT / "models" / "generator_portraits_128.pt",
}
LAST = 999_999
PAINTING = 340   # taille d'affichage de la peinture (px)
STEP = 120       # taille d'affichage de chaque etape du schema (px)

st.set_page_config(page_title="GANisme", layout="wide")


@st.cache_resource(max_entries=3)
def get_models(path: str):
    G, info = load_generator(path)
    return G, info, load_discriminator(path)


def move(step: int):
    st.session_state.seed = (st.session_state.seed + step) % (LAST + 1)


def shuffle():
    st.session_state.seed = random.randint(0, LAST)


def upscale(array: np.ndarray, size: int) -> Image.Image:
    """Agrandit une petite image (uint8) sans flou, pour garder les pixels visibles."""
    return Image.fromarray(array).resize((size, size), Image.Resampling.NEAREST)


def heat(values: np.ndarray, cmap: str, vmin: float = 0.0, vmax: float = 1.0) -> np.ndarray:
    """Valeurs -> image couleur (uint8) selon une palette."""
    scaled = np.clip((values - vmin) / (vmax - vmin), 0, 1)
    return (colormaps[cmap](scaled)[..., :3] * 255).astype(np.uint8)


st.session_state.setdefault("seed", 42)

available = {name: path for name, path in MODELS.items() if path.exists()}
if not available:
    st.error("Aucun générateur trouvé. Exportez-le avec "
             "`python -m ganisme.generate --run_dir runs/dcgan_64` (avec `PYTHONPATH=src`).")
    st.stop()

top_left, top_right = st.columns([3, 2], vertical_alignment="bottom")
with top_left:
    st.title("GANisme", anchor=False)
    st.caption("Des peintures qui n'ont jamais existé, et le chemin qu'elles suivent dans le réseau.")
with top_right:
    collection = st.segmented_control("Collection", list(available), default=list(available)[0],
                                      key="collection", label_visibility="collapsed")

G, info, D = get_models(str(available[collection or list(available)[0]]))
seed = int(st.session_state.seed)
z, maps, image = trace(G, seed, info["z_dim"])
size = image.shape[-1]
painting = ((image[0].clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).numpy()

left, right = st.columns([5, 8], gap="large")

with left:
    st.image(upscale(painting, PAINTING), alt=f"Peinture générée n° {seed}", width=PAINTING)
    st.markdown(f"**Sans titre, n° {seed:06d}**")
    st.caption(f"Générée par un DCGAN · {size} × {size} pixels, agrandie sans flou")
    with st.container(horizontal=True):
        st.button("Précédente", key="prev", on_click=move, args=(-1,))
        st.button("Au hasard", key="random", on_click=shuffle, type="primary")
        st.button("Suivante", key="next", on_click=move, args=(1,))
        buffer = io.BytesIO()
        upscale(painting, 512).save(buffer, format="PNG")
        st.download_button("Télécharger", data=buffer.getvalue(), file_name=f"ganisme_{seed:06d}.png",
                           mime="image/png", key="download")

with right:
    st.subheader("Comment cette peinture est née", anchor=False)

    st.markdown("**1 · Un bruit aléatoire.** Le numéro de l'œuvre fixe 100 nombres tirés au hasard : "
                "c'est le seul point de départ du générateur.")
    st.markdown("**2 · Le générateur** transforme ce bruit en image, en doublant la résolution à chaque "
                "couche. Voici ce que contient réellement chaque étape pour cette peinture :")
    stages = [(upscale(heat(z.reshape(10, 10), "coolwarm", -2.5, 2.5), STEP), "bruit z · 100 nombres")]
    stages += [(upscale(heat(m, "magma"), STEP), f"{s} × {s}") for s, m in maps]
    stages.append((upscale(painting, STEP), f"image {size} × {size}"))
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        for k, (img, caption) in enumerate(stages):
            with st.container(width=STEP + 8, gap="small"):
                st.image(img, width=STEP, alt=f"Étape {k + 1} de la génération : {caption}")
                st.caption(caption)
            if k < len(stages) - 1:
                st.markdown("→")

    st.markdown("**3 · Le discriminateur** a appris, pendant l'entraînement, à reconnaître les vraies "
                "peintures. Le générateur, lui, a appris à le tromper.")
    if D is not None:
        p = realism(D, image)
        st.progress(p, text=f"Le discriminateur estime que cette image est une vraie peinture à {p:.0%}")
    else:
        st.caption("Score du discriminateur non disponible pour cette collection.")
