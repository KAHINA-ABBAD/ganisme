import math

import pandas as pd

from ganisme.eda import (
    add_features,
    image_url,
    parse_dimensions,
    parse_life,
    parse_year,
    technique_family,
    work_key,
)


def test_parse_year_handles_catalogue_formats():
    assert parse_year("1648-50") == 1648
    assert parse_year("c. 1530") == 1530
    assert parse_year("c.1530") == 1530
    assert parse_year("1880s") == 1880
    assert parse_year("Summer 1888, Paris") == 1888
    assert parse_year("15th century") == 1450
    assert parse_year("3rd century") == 250
    assert math.isnan(parse_year("-"))


def test_parse_dimensions_reads_height_and_width():
    assert parse_dimensions("Oil on canvas, 68 x 95 cm") == (68.0, 95.0)
    assert parse_dimensions("Oil on canvas, 78,5 x 78,5 cm") == (78.5, 78.5)
    height, width = parse_dimensions("Fresco")
    assert math.isnan(height) and math.isnan(width)


def test_technique_family():
    assert technique_family("Oil on oak panel, 29 x 22 cm") == "oil"
    assert technique_family("Egg tempera on wood") == "tempera"
    assert technique_family("Fresco, 470 x 470 cm") == "fresco"
    assert technique_family("Wood") == "other"


def test_parse_life():
    assert parse_life("(b. 1552, Köln, d. 1615, Praha)") == (1552.0, 1615.0)
    assert parse_life("(b. ca. 1430, Venezia, d. ca. 1516)") == (1430.0, 1516.0)
    born, died = parse_life("(active 1500s in Florence)")
    assert math.isnan(born) and math.isnan(died)


def test_work_key_groups_details_with_their_work():
    assert work_key("GIOTTO", "Last Judgment (detail)") == work_key(
        "GIOTTO", "Last Judgment"
    )


def test_image_url():
    assert (
        image_url("https://www.wga.hu/html/a/aachen/adonis.html")
        == "https://www.wga.hu/art/a/aachen/adonis.jpg"
    )


def test_add_features_keeps_rows_and_adds_columns():
    data = pd.DataFrame(
        {
            "AUTHOR": ["AACHEN, Hans von"],
            "BORN-DIED": ["(b. 1552, Köln, d. 1615, Praha)"],
            "TITLE": ["Venus and Adonis (detail)"],
            "DATE": ["1574-88"],
            "TECHNIQUE": ["Oil on canvas, 68 x 95 cm"],
            "URL": ["https://www.wga.hu/html/a/aachen/adonis.html"],
        }
    )

    features = add_features(data)

    assert len(features) == 1
    row = features.iloc[0]
    assert row["year"] == 1574
    assert row["aspect_ratio"] == 95 / 68
    assert row["technique_family"] == "oil"
    assert bool(row["is_detail"])
