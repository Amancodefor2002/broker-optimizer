from app.models import Load
from app.validation import validate_loads


def test_detects_true_duplicate():
    loads = [
        Load(row_index=1, origin="A, IL", destination="B, IL", miles=100, rate=500),
        Load(row_index=2, origin="A, IL", destination="B, IL", miles=100, rate=500),
    ]
    report = validate_loads(loads)
    assert report.duplicate_count == 1
    assert report.flags[0].flag_type == "duplicate"
    assert report.flags[0].row_index == 2


def test_does_not_flag_placeholder_loads_as_duplicates():
    # Same origin, no destination/rate yet -- these are separate
    # available loads waiting to be assigned, not copy-paste dupes
    loads = [
        Load(row_index=1, origin="A, IL", destination=None, miles=None, rate=None),
        Load(row_index=2, origin="A, IL", destination=None, miles=None, rate=None),
        Load(row_index=3, origin="A, IL", destination=None, miles=None, rate=None),
    ]
    report = validate_loads(loads)
    assert report.duplicate_count == 0
    # still flagged as missing_destination/rate/miles though
    assert report.missing_field_count == 9  # 3 loads x 3 missing fields each


def test_different_rate_is_not_a_duplicate():
    loads = [
        Load(row_index=1, origin="A, IL", destination="B, IL", miles=100, rate=500),
        Load(row_index=2, origin="A, IL", destination="B, IL", miles=100, rate=650),
    ]
    report = validate_loads(loads)
    assert report.duplicate_count == 0


def test_flags_missing_fields_individually():
    loads = [Load(row_index=1, origin="A, IL", destination=None, miles=None, rate=200)]
    report = validate_loads(loads)
    flag_types = {f.flag_type for f in report.flags}
    assert "missing_destination" in flag_types
    assert "missing_miles" in flag_types
    assert "missing_rate" not in flag_types  # rate was provided
