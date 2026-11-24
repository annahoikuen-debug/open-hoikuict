"""home_care_details.validate_meals のスケール統一テスト（フェーズA W2）."""

from home_care_details import APPETITES_V2, validate_meals


def _meal_payload(dinner_appetite="", dinner_contents="", breakfast_appetite="", breakfast_contents=""):
    return {
        "dinner_appetite": dinner_appetite,
        "dinner_contents": dinner_contents,
        "breakfast_appetite": breakfast_appetite,
        "breakfast_contents": breakfast_contents,
    }


def test_new_appetite_scale_is_accepted():
    """新スケール（完食/ほぼ完食/半分/少なめ）が受理される."""
    for appetite in APPETITES_V2:
        result = validate_meals(_meal_payload(dinner_appetite=appetite, breakfast_appetite=appetite))
        assert result["dinner_appetite"] == appetite
        assert result["breakfast_appetite"] == appetite


def test_old_appetite_scale_is_accepted():
    """旧スケール（旺盛/普通/あまりない/ない）も引き続き受理される（旧クライアント互換）."""
    for appetite in ("旺盛", "普通", "あまりない", "ない"):
        result = validate_meals(_meal_payload(dinner_appetite=appetite, breakfast_appetite=appetite))
        assert result["dinner_appetite"] == appetite
        assert result["breakfast_appetite"] == appetite


def test_invalid_appetite_raises_valueerror():
    """両スケール外の値は ValueError（誘導文言）."""
    try:
        validate_meals(_meal_payload(dinner_appetite="旺盛!", breakfast_appetite="完食"))
    except ValueError as exc:
        assert "食欲は表示された四つから選んでください" in str(exc)
        assert "完食" in str(exc)
        assert "旺盛" in str(exc)
        return
    raise AssertionError("ValueError が送出されませんでした")


def test_empty_appetite_is_accepted():
    """空欄（未記入）は受理される."""
    result = validate_meals(_meal_payload())
    assert result["dinner_appetite"] == ""
    assert result["breakfast_appetite"] == ""


def test_contents_length_boundary():
    """献立 1000 文字境界（1000 OK / 1001 NG）."""
    ok_1000 = "あ" * 1000
    ng_1001 = "あ" * 1001

    result = validate_meals(_meal_payload(dinner_contents=ok_1000, breakfast_contents=ok_1000))
    assert result["dinner_contents"] == ok_1000
    assert result["breakfast_contents"] == ok_1000

    try:
        validate_meals(_meal_payload(dinner_contents=ng_1001))
    except ValueError as exc:
        assert "1000文字以内" in str(exc)
        return
    raise AssertionError("ValueError が送出されませんでした")


def test_mixed_new_and_old_appetite_is_accepted():
    """新旧混在（夕食=旧値、朝食=新値）でも受理される."""
    result = validate_meals(_meal_payload(dinner_appetite="旺盛", breakfast_appetite="完食"))
    assert result["dinner_appetite"] == "旺盛"
    assert result["breakfast_appetite"] == "完食"
