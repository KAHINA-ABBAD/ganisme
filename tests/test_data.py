import pandas as pd

from ganisme.data import clean_data


def test_clean_data_strips_columns_and_removes_empty_rows():
    data = pd.DataFrame({" nom ": ["Ada", None], " age ": [36, None]})

    cleaned = clean_data(data)

    assert list(cleaned.columns) == ["nom", "age"]
    assert cleaned.to_dict(orient="records") == [{"nom": "Ada", "age": 36.0}]