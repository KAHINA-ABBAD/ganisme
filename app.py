"""GANisme a l'infini : une galerie de peintures qui n'existent pas, une oeuvre a la fois.

Lancement depuis la racine du projet :

    streamlit run app.py
"""

import io
import random
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ganisme.generate import generate, load_generator, to_grid  # noqa: E402

MODELS = {  # libelle -> fichier exporte par ganisme.generate (seuls les fichiers presents sont proposes)
    "Portraits": ROOT / "models" / "generator_portraits_64.pt",
    "Tous les genres": ROOT / "models" / "generator.pt",
    "Portraits 128 px (essai)": ROOT / "models" / "generator_portraits_128.pt",
}
LAST = 999_999
DISPLAY = 512  # image agrandie sans flou (x8 en 64 px, x4 en 128 px)

st.set_page_config(page_title="GANisme", layout="centered")


@st.cache_resource(max_entries=3)
def get_generator(path: str):
    return load_generator(path)


def move(step: int):
    st.session_state.seed = (st.session_state.seed + step) % (LAST + 1)


def shuffle():
    st.session_state.seed = random.randint(0, LAST)


st.session_state.setdefault("seed", 42)

st.title("GANisme", anchor=False)
st.caption("Une galerie de peintures qui n'ont jamais existé.")

available = {name: path for name, path in MODELS.items() if path.exists()}
if not available:
    st.error("Aucun générateur trouvé. Exportez-le avec "
             "`python -m ganisme.generate --run_dir runs/dcgan_64` (avec `PYTHONPATH=src`).")
    st.stop()

with st.container(horizontal_alignment="center"):
    collection = st.segmented_control("Collection", list(available), default=list(available)[0],
                                      key="collection", label_visibility="collapsed")
G, info = get_generator(str(available[collection or list(available)[0]]))
seed = int(st.session_state.seed)
size = info.get("image_size", 64)
painting = to_grid(generate(G, 1, seed, info["z_dim"]), ncols=1, scale=DISPLAY // size, pad=0)

with st.container(horizontal_alignment="center"):
    st.image(painting, alt=f"Peinture générée n° {seed}", width=DISPLAY)

    # Cartel, comme a cote d'un tableau de musee.
    st.markdown(f"**Sans titre, n° {seed:06d}**")
    st.caption(f"Image générée par un DCGAN · {size} × {size} pixels, agrandie sans flou")

with st.container(horizontal=True, horizontal_alignment="center"):
    st.button("Précédente", key="prev", on_click=move, args=(-1,))
    st.button("Au hasard", key="random", on_click=shuffle, type="primary")
    st.button("Suivante", key="next", on_click=move, args=(1,))

buffer = io.BytesIO()
painting.save(buffer, format="PNG")
with st.container(horizontal=True, horizontal_alignment="center"):
    st.download_button("Télécharger", data=buffer.getvalue(), file_name=f"ganisme_{seed:06d}.png",
                       mime="image/png", key="download")

with st.expander("Aller à une œuvre précise"):
    st.number_input("Numéro de l'œuvre", min_value=0, max_value=LAST, step=1, key="seed",
                    help="Chaque numéro donne toujours la même peinture.")

with st.expander("À propos"):
    metrics = info.get("metrics", {})
    st.markdown(
        "Ces images sont produites par un réseau antagoniste génératif (DCGAN) entraîné sur "
        f"{metrics.get('n_train', 'quelques milliers de'):,} tableaux de la Web Gallery of Art, du XIIIe au "
        "XIXe siècle. Chaque numéro correspond à un point de départ aléatoire : le même numéro redonne "
        "toujours la même peinture.".replace(",", " "))
    if "fid" in metrics:
        st.caption(f"FID {metrics['fid']:.0f} (référence entre vraies peintures : {metrics['fid_real']:.0f}) · "
                   f"{info.get('epochs', '?')} époques")
