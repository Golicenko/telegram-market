import pytest
from pydantic import ValidationError

from app.schemas import ListingCreate, ListingUpdate


def payload(**changes):
    return {"game_version": "car_parking_1", "brand": " BMW ", "power_hp": 300,
            "max_speed_kph": 250, "description": " Real photo ", "price_af_coins": "100.25",
            "image_urls": ["/uploads/legacy.jpg"], **changes}


@pytest.mark.parametrize("field,value", [("brand", "   "), ("description", "\n "), ("power_hp", 10**30), ("max_speed_kph", 1.1), ("price_af_coins", "10000000000000000"), ("price_af_coins", "1.111"), ("price_af_coins", "NaN")])
def test_invalid_listing_returns_validation_not_database_error(field, value):
    with pytest.raises(ValidationError):
        ListingCreate(**payload(**{field: value}))
    with pytest.raises(ValidationError):
        ListingUpdate(**{field: value})


@pytest.mark.parametrize("field", ["brand", "description", "power_hp", "max_speed_kph", "price_af_coins", "delivery_time_estimate", "image_urls"])
def test_patch_null_rejected_but_omission_keeps_existing_fields(field):
    with pytest.raises(ValidationError):
        ListingUpdate(**{field: None})
    assert ListingUpdate().model_dump(exclude_unset=True) == {}


def test_listing_whitespace_is_normalized_before_validation():
    listing = ListingCreate(**payload())
    assert listing.brand == "BMW" and listing.description == "Real photo"
    assert ListingUpdate(brand=" BMW ", description=" Car ").brand == "BMW"
