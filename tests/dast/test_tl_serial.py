"""Тесты безопасного сериализатора raw TL-объектов."""

from datetime import datetime, timezone

from tg_flowmap.dast.tl_serial import clean, safe_dumps


class _TLStub:
    """Имитация TLObject: to_dict() с вложенными bytes/datetime/объектами."""

    def to_dict(self):
        return {
            "_": "fake TLObject",
            "data": b"\x01\x02\xff",
            "when": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            "inner": {"nested": (b"\x00", 7)},
        }


class _Boom:
    def to_dict(self):
        raise RuntimeError("boom")


def test_bytes_cleaned_to_b64_and_hex():
    v = clean(b"\x01\x02")
    assert v == {"$bytes": {"b64": "AQI=", "hex": "0102"}}


def test_datetime_iso8601():
    assert clean(datetime(2026, 8, 17, 10, 30, tzinfo=timezone.utc)) == \
        "2026-08-17T10:30:00+00:00"


def test_tlobject_to_dict_recursive():
    v = clean(_TLStub())
    assert v["_"] == "fake TLObject"
    assert v["data"] == {"$bytes": {"b64": "AQL/", "hex": "0102ff"}}
    assert v["when"] == "2026-01-01T12:00:00+00:00"
    assert v["inner"]["nested"][0] == {"$bytes": {"b64": "AA==", "hex": "00"}}
    assert v["inner"]["nested"][1] == 7


def test_unknown_object_type_and_repr():
    v = clean(object())
    assert v["$unknown"] == "object"
    assert "repr" in v


def test_to_dict_failure_does_not_raise():
    v = clean(_Boom())
    assert v["$unknown"] == "_Boom"
    s = safe_dumps({"x": _Boom()})
    assert "$unknown" in s  # json собран, обход не прерывается


def test_sets_tuples_to_lists():
    assert clean((1, 2)) == [1, 2]
    assert clean({1, 2}) in ([1, 2], [2, 1])


def test_safe_dumps_plain():
    assert safe_dumps({"a": 1}) == '{"a": 1}'
