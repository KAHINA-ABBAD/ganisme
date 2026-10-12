import pandas as pd

from ganisme.selection import balanced_quotas, select_paintings, split_of


def test_balanced_quotas_fills_small_groups_then_shares_the_rest():
    available = pd.Series({"rare": 2, "medium": 10, "large": 100})

    quotas = balanced_quotas(available, 20)

    assert quotas.to_dict() == {"rare": 2, "medium": 9, "large": 9}


def test_balanced_quotas_distributes_remainder_and_respects_total():
    quotas = balanced_quotas(pd.Series({"a": 50, "b": 50, "c": 50}), 10)

    assert quotas.sum() == 10
    assert quotas.max() - quotas.min() <= 1


def test_balanced_quotas_takes_everything_when_short():
    available = pd.Series({"a": 3, "b": 4})

    assert balanced_quotas(available, 100).to_dict() == {"a": 3, "b": 4}


def test_split_is_deterministic():
    assert split_of("GIOTTO|madonna") == split_of("GIOTTO|madonna")
    splits = {split_of(f"artist|work {i}") for i in range(200)}
    assert splits == {"train", "eval"}


def _paintings():
    rows = []
    for i in range(40):
        rows.append({
            "URL": f"u{i:03d}", "AUTHOR": f"artist {i % 4}", "TYPE": "religious" if i < 30 else "landscape",
            "work_key": f"artist {i % 4}|work {i}", "is_detail": False,
            "technique_family": "oil", "aspect_ratio": 0.8,
        })
    rows.append({**rows[0], "URL": "detail", "is_detail": True})
    rows.append({**rows[0], "URL": "fresco", "technique_family": "fresco", "work_key": "x|fresco"})
    rows.append({**rows[0], "URL": "frieze", "aspect_ratio": 4.0, "work_key": "x|frieze"})
    rows.append({**rows[0], "URL": "same work", "work_key": rows[0]["work_key"]})
    return pd.DataFrame(rows)


def test_select_paintings_applies_filters_caps_and_quotas():
    selected = select_paintings(_paintings(), n=12, max_per_artist=5, seed=0)

    assert not {"detail", "fresco", "frieze"} & set(selected["URL"])
    assert selected["work_key"].is_unique
    assert selected["AUTHOR"].value_counts().max() <= 5
    assert selected["TYPE"].value_counts().to_dict() == {"religious": 6, "landscape": 6}
    assert list(selected["image_id"]) == list(range(len(selected)))


def test_select_paintings_is_reproducible():
    first = select_paintings(_paintings(), n=12, max_per_artist=5, seed=1)
    second = select_paintings(_paintings(), n=12, max_per_artist=5, seed=1)

    pd.testing.assert_frame_equal(first, second)


def test_select_paintings_can_restrict_to_one_genre():
    selected = select_paintings(_paintings(), n=100, max_per_artist=50, seed=0, types=["landscape"])

    assert set(selected["TYPE"]) == {"landscape"}
    assert len(selected) == 10
