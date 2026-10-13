# GANisme

Generating original paintings with a Generative Adversarial Network (GAN), trained
on the painting catalogue of the [Web Gallery of Art](https://www.wga.hu/).

## Context

GANisme is a deep learning project from La Plateforme. The goal is to build an AI
that generates random painted artworks — "like DALL-E, but without the text
prompt". The project has three parts:

1. **GAN research** — a literature review answering 15 questions on how GANs work,
   how they are trained and evaluated, their variants (DCGAN, WGAN-GP, StyleGAN…)
   and the risks of generative models.
2. **GANisme** — explore the artwork catalogue, keep only paintings, scrape their
   images, preprocess them, then design, train and evaluate a GAN.
3. **GANisme à l'infini** — deploy the trained generator as a Streamlit app.
   Optionally, the training set can be extended with abstract-art paintings.

The full brief (in French) is in [data/GANisme.docx.pdf](data/GANisme.docx.pdf).

## Dataset

[data/raw/data.csv](data/raw/data.csv) is the Web Gallery of Art
catalogue: **52,867 artworks**, of which **32,438 are paintings** (`FORM ==
"painting"`). Each row has the following columns:

| Column | Description |
| --- | --- |
| `AUTHOR` | Artist name (`LASTNAME, Firstname`) |
| `BORN-DIED` | Artist's birth and death dates and places |
| `TITLE` | Title of the work |
| `DATE` | Date or date range of creation (free text) |
| `TECHNIQUE` | Medium and dimensions, e.g. `Oil on canvas, 68 x 95 cm` |
| `LOCATION` | Museum or collection holding the work |
| `URL` | Web Gallery of Art page for the work, used for scraping |
| `FORM` | `painting`, `sculpture`, `architecture`, `graphics`, … |
| `TYPE` | Genre: `portrait`, `landscape`, `mythological`, `religious`, … |
| `SCHOOL` | National school, e.g. `Italian`, `German` |
| `TIMEFRAME` | 50-year period, e.g. `1601-1650` |

The images are not in the CSV. They are fetched from the `URL` pages after the
exploratory analysis.

## Approach

The work follows two data phases so we don't download the whole image database
for nothing:

- **Phase 1: metadata EDA.** Analyse the full catalogue (missing values,
  duplicates, distributions by genre, school and period, biases) without
  downloading images.
- **Phase 2: targeted download.** Select a justified subset of roughly 5,000 to
  10,000 paintings, download only those images, and resize them for training
  (64×64 for a light baseline, or 128×128). A manifest records each image's
  status (`pending`, `downloaded`, `processed`, `failed`, `skipped`) so the
  pipeline can resume after an interruption.

Modelling starts with a **DCGAN baseline**. Alternatives such as WGAN-GP or
StyleGAN are tried only if the baseline's results justify them. Generated images
are evaluated quantitatively (e.g. FID) and by visual inspection, looking in
particular for mode collapse.

## Repository layout

```text
Ganisme/
├── data/
│   ├── GANisme.docx.pdf   Project brief (French)
│   ├── raw/               Source data, kept unmodified (not tracked by Git)
│   │   └── data.csv       Web Gallery of Art catalogue
│   └── processed/         Derived data (only the two items marked * are tracked by Git)
│       ├── paintings_metadata.csv   Paintings + parsed features (written by 01_eda)
│       ├── manifest.csv * One row per selected image, with its download status
│       ├── images_256/  * Downloaded images, centre-cropped to 256×256 (~270 MB)
│       └── dataset_64_v1.npz Final training/eval images at 64×64 (written by 02_dataset)
├── notebooks/
│   ├── 01_eda.ipynb       Phase 1: commented metadata EDA (French)
│   ├── 02_dataset.ipynb   Phase 2: selection, download report, image inspection, export
│   ├── 03_gan.ipynb       Phase 3: DCGAN architecture, training, evaluation (questions 6-8)
│   └── 04_portraits.ipynb Course pipeline, homogeneous portrait dataset, 64×64 then 128×128
├── reports/
│   ├── eda/, dataset/     Saved outputs (JSON, figures/*.png) of the notebooks
│   ├── training/          Metrics (metrics.json) and figures of the trained GAN
│   └── presentation/      Slide decks (.pptx), oral script and technical questions (PDF)
├── runs/                  Training checkpoints and samples (not tracked by Git)
├── models/generator.pt   Exported generator weights used by the app (~14 MB)
├── app.py                 Streamlit app: generate paintings with the trained GAN
├── .streamlit/           App theme (dark)
├── src/ganisme/           Reusable Python code
│   ├── data.py            CSV loading and basic cleaning
│   ├── eda.py             Feature extraction from the catalogue's free-text fields
│   ├── selection.py       Reproducible selection of the paintings to download
│   ├── download.py        Resumable image download and preprocessing (CLI)
│   ├── images.py          Image loading, colour statistics, near-duplicate detection
│   ├── dcgan.py           DCGAN 64×64 model and resumable training (CLI)
│   ├── evaluate.py        FID, KID, nearest neighbours and training figures (CLI)
│   ├── generate.py        Generator export, image generation and grids (used by the app)
│   ├── pipeline.py        Course image pipeline: transforms, Dataset, 128×128 folder export
│   └── compare.py         Compares generators on the same evaluation set
├── tests/                 Automated tests (pytest)
├── requirements.txt       Pinned dependencies
└── README.md
```

### `ganisme.data`

- `load_csv(path)` loads a CSV file and applies `clean_data`.
- `clean_data(df)` strips whitespace from column names and drops rows that are
  entirely empty.

```python
from ganisme.data import load_csv

df = load_csv("data/raw/data.csv")
paintings = df[df["FORM"] == "painting"]
```

### `ganisme.eda`

The catalogue fields are free text. `add_features(df)` adds parsed columns:
`year` (from `DATE`), `height_cm`, `width_cm` and `aspect_ratio` (from
`TECHNIQUE`), `technique_family` (oil, fresco, tempera…), `artist_born` and
`artist_died`, `is_detail` (detail views of another work), `work_key` (groups a
work with its detail views, used to split train/eval data without leakage) and
`image_url` (the image file behind each `URL` page).

### `notebooks/01_eda.ipynb`

Phase 1 analysis of the 32,438 paintings: data quality, genres, schools,
artists, periods, techniques, formats, near-duplicates and a proposed selection
for Phase 2. It writes `data/processed/paintings_metadata.csv` and
`reports/eda/`, so the results don't have to be recomputed.

### Phase 2: selection and download

`ganisme.selection.select_paintings` picks 8,000 paintings: no detail views or
frescoes, sensible aspect ratios, one row per work, at most 30 per artist, and
balanced quotas across genres. Works are split 90/10 into `train` and `eval` by
hashing `work_key`, so a work never appears on both sides.

`ganisme.download` scrapes the selected images. A manifest records each image's
status (`pending`, `processed`, `failed`, `skipped`), so the run can be stopped
and resumed; failed downloads are retried up to 3 times and exact duplicates are
skipped. Each image is centre-cropped to a square and stored at 256×256.

```powershell
$env:PYTHONPATH = "src"
python -m ganisme.download --workers 6
```

The Web Gallery of Art server is slow and irregular (about 0.7 images/s), so the full run
takes several hours. `notebooks/02_dataset.ipynb` then inspects the images,
removes greyscale reproductions and near-duplicates (an 8×8 perceptual hash
proposes candidate pairs, a pixel comparison confirms them), and exports
`data/processed/dataset_64_v1.npz`, a single file that can be copied to Google
Colab for training.

### Phase 3: training and evaluation

`ganisme.dcgan` trains a DCGAN 64×64 (Radford et al., 2015: Adam, learning rate
0.0002, β1 = 0.5, batch 128, z of size 100, binary cross-entropy). After each
epoch it saves a full checkpoint (`runs/<name>/last.pt`: weights, optimisers,
epoch, history and random states) and a grid generated from fixed noise
vectors, so an interrupted run resumes where it stopped. On a 16-thread CPU an
epoch over ~6,100 images takes about 90 seconds.

`ganisme.evaluate` computes the FID and KID between generated images and the
evaluation set (never seen in training), a reference FID between two sets of
real paintings of the same size, and the nearest training image of each
generated sample to check for memorisation. It writes `reports/training/`.

```powershell
$env:PYTHONPATH = "src"
python -m ganisme.dcgan --epochs 50
python -m ganisme.evaluate --run_dir runs/dcgan_64
```

### Streamlit app ("GANisme à l'infini")

`app.py` loads the exported generator (`models/generator.pt`, weights only, so
the training checkpoints are not needed) and generates paintings: choose how
many (1 to 36) and a seed (the same seed always gives the same paintings),
upscale without blur and download the grid as PNG.

```powershell
$env:PYTHONPATH = "src"
python -m ganisme.generate --run_dir runs/dcgan_64   # export after training
streamlit run app.py
```

### Phase 4: homogeneous dataset (portraits)

Following the course's image-processing how-to ("homogeneous dataset", "start
at 64×64, then 128×128"), `notebooks/04_portraits.ipynb` trains the same DCGAN
on portraits only (3,737 downloaded, 128×128 folder in
`data/processed/portraits_128/`), using the course pipeline
(`Resize → CenterCrop → RandomHorizontalFlip → ToTensor → Normalize`).

| Model | FID | Real-vs-real reference | Gap |
| --- | --- | --- | --- |
| All genres, 64×64 | 211 | 62 | ×3.4 |
| **Portraits, 64×64** (app default) | **204** | 73 | **×2.8** |
| Portraits, 128×128 (100 epochs only) | 286 | 76 | ×3.8 |

```bash
bash scripts/train_portraits.sh 64 180    # train, evaluate, export (auto-restart on crash)
```

### Presentations

`reports/presentation/` holds the slide decks (`GANisme_sombre.pptx` is the one
presented), the oral script (`commentaires_oral.pdf`) and the likely technical
questions with short answers (`questions_techniques.pdf`). The speaker notes
contain the oral script and the questions for each slide.
`reports/veille/veille_technologique.pdf` answers the 15 research questions.

### Planned deliverables

Still in progress:

- The final model, trained on the full dataset (the current results come from
  a baseline trained on a partial dataset).

## Getting started

Requires Python 3.10 or later (developed with 3.13). On Windows (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Re-run the EDA notebook end to end:

```powershell
python -m jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb
```

Run the tests from the project root:

```powershell
$env:PYTHONPATH = "src"
python -m pytest
```

The scraped images (`data/processed/images_256/`) and their manifest are tracked
by Git, so the dataset is available after cloning without scraping again. The
other files in `data/raw/` and `data/processed/` are ignored: place the catalogue
CSV at `data/raw/data.csv` after cloning and re-run the notebooks to rebuild them.

The images come from the Web Gallery of Art, which allows educational and
personal use only. Keep the repository private, or check the site's terms before
making it public.
