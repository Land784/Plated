from menu.allergens import UnknownAllergenPolicy, filter_items, item_is_allergen_safe
from tests.conftest import make_item


def test_item_with_excluded_allergen_is_unsafe():
    item = make_item("Peanut Noodles", protein_g=20, calories=300, allergens=["Peanuts"])
    assert item_is_allergen_safe(item, {"peanuts"}) is False


def test_item_without_excluded_allergen_is_safe():
    item = make_item("Rice", protein_g=5, calories=200, allergens=["Gluten"])
    assert item_is_allergen_safe(item, {"peanuts"}) is True


def test_item_with_no_allergen_data_is_unknown():
    item = make_item("Mystery Casserole", protein_g=10, calories=300, allergens=[])
    assert item_is_allergen_safe(item, {"peanuts"}) is None


def test_filter_items_flags_unknown_by_default():
    known_safe = make_item("Rice", protein_g=5, calories=200, allergens=["Gluten"])
    unknown = make_item("Mystery Casserole", protein_g=10, calories=300, allergens=[])
    excluded = make_item("Peanut Noodles", protein_g=20, calories=300, allergens=["Peanuts"])

    keep, dropped = filter_items(
        [known_safe, unknown, excluded],
        {"peanuts"},
        unknown_policy=UnknownAllergenPolicy.FLAG,
    )

    assert known_safe in keep
    assert unknown in keep  # flagged, not dropped
    assert excluded in dropped
    assert excluded not in keep


def test_filter_items_can_exclude_unknown_instead():
    unknown = make_item("Mystery Casserole", protein_g=10, calories=300, allergens=[])

    keep, dropped = filter_items(
        [unknown], {"peanuts"}, unknown_policy=UnknownAllergenPolicy.EXCLUDE
    )

    assert unknown in dropped
    assert unknown not in keep
