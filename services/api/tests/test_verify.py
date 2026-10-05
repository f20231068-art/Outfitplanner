import pytest

from api.agent.find import find_products_for_specs
from api.agent.products import mock_search
from api.agent.schemas import FindProductsInput, ItemSpec, OutfitSpec, Product
from api.agent.verify import verify_product


def _spec(**kw) -> ItemSpec:
    # these tests are about a colour the SHOPPER asked for (the only kind that is checked)
    base = {"category": "bottom", "item": "baggy pants", "color": "peach", "color_source": "user", "max_price_inr": 2000}
    return ItemSpec(**{**base, **kw})


def _product(**kw) -> Product:
    base = {
        "title": "Peach Baggy Pants",
        "retailer": "Myntra",
        "price_inr": 1500,
        "url": "https://x",
        "image_url": "https://i",
    }
    return Product(**{**base, **kw})


def _status(report, attr):
    return next(c.status for c in report.checks if c.attribute == attr)


def test_genuine_match_passes_with_evidence():
    report = verify_product(_product(attributes={"color": "Peach", "gender": "men"}), _spec())
    assert report.is_match
    assert report.score == 1.0
    assert all(c.evidence for c in report.checks)


def test_wrong_color_is_rejected_from_page_field():
    report = verify_product(_product(title="Black Baggy Pants", attributes={"color": "Black"}), _spec())
    assert not report.is_match and "color" in report.blocking


def test_wrong_color_is_rejected_from_title_alone():
    report = verify_product(_product(title="Olive Baggy Pants"), _spec())
    assert _status(report, "color") == "mismatch" and not report.is_match


def test_unstated_color_is_trusted_from_the_search_but_flagged_low_confidence():
    report = verify_product(_product(title="Baggy Pants"), _spec())
    color = next(c for c in report.checks if c.attribute == "color")
    assert color.status == "unknown" and color.assumed  # never reported as a confirmed match
    assert report.is_match and report.confidence == "low"
    assert "color" not in report.blocking


def test_confirmed_color_gives_high_confidence():
    report = verify_product(_product(attributes={"color": "peach", "gender": "men"}), _spec())
    assert report.confidence == "high"


def test_contradicting_color_is_still_rejected_even_with_the_fallback():
    report = verify_product(_product(title="Olive Baggy Pants"), _spec())
    assert not report.is_match and "color" in report.blocking


def test_confirmed_product_outranks_a_low_confidence_one_even_if_cheaper():
    cheap_confirmed = _product(title="Peach Baggy Pants", price_inr=900, url="https://a",
                               attributes={"color": "peach", "gender": "men"})
    pricey_assumed = _product(title="Baggy Pants", price_inr=1900, url="https://b")  # no colour stated

    out = find_products_for_specs(
        FindProductsInput(
            specs=[OutfitSpec(top=_spec(category="top", item="t-shirt"), bottom=_spec(), rationale="r")],
            budget_inr=9000,
        ),
        lambda spec: [cheap_confirmed, pricey_assumed] if spec.category == "bottom"
        else [_product(title="Peach T-Shirt", attributes={"color": "peach"})],
    )
    assert out.outfits[0].bottom.url == "https://a"  # the confirmed one wins


def test_outfit_with_an_assumed_colour_is_marked_low_confidence():
    out = find_products_for_specs(
        FindProductsInput(
            specs=[OutfitSpec(top=_spec(category="top", item="t-shirt"), bottom=_spec(), rationale="r")],
            budget_inr=9000,
        ),
        lambda spec: [_product(title="Peach T-Shirt" if spec.category == "top" else "Baggy Pants",
                               attributes={"color": "peach"} if spec.category == "top" else {})],
    )
    assert out.outfits[0].confidence == "low"


def test_wrong_item_is_rejected():
    report = verify_product(_product(title="Peach Skinny Jeans", attributes={"color": "peach"}), _spec())
    assert "item" in report.blocking


def test_price_over_cap_is_rejected():
    report = verify_product(_product(price_inr=2500, attributes={"color": "peach"}), _spec())
    assert "price" in report.blocking


def test_category_contradiction_blocks_top_vs_bottom():
    spec = _spec(category="top", item="blue", color="blue")  # asked for a top
    report = verify_product(_product(title="Blue Cargo Pants", attributes={"color": "blue"}), spec)
    assert _status(report, "category") == "mismatch"
    assert "category" in report.blocking


def test_conflicting_fit_blocks_but_missing_fit_does_not():
    spec = _spec(fit="oversized", item="pants")
    conflict = verify_product(
        _product(title="Peach Slim Pants", attributes={"color": "peach"}), spec
    )
    unknown = verify_product(_product(title="Peach Pants", attributes={"color": "peach"}), spec)
    assert "fit" in conflict.blocking
    assert _status(unknown, "fit") == "unknown" and unknown.is_match


def test_synonyms_tee_and_trousers_count_as_matches():
    tee = verify_product(
        _product(title="Light Blue Tee", attributes={"color": "light blue"}),
        _spec(category="top", item="t-shirt", color="light blue"),
    )
    trousers = verify_product(
        _product(title="Peach Baggy Trousers", attributes={"color": "peach"}), _spec()
    )
    assert tee.is_match and trousers.is_match


def test_find_products_never_returns_the_wrong_colour_decoy():
    spec = OutfitSpec(
        top=ItemSpec(category="top", item="t-shirt", color="light blue", max_price_inr=1500),
        bottom=_spec(),
        rationale="r",
    )
    out = find_products_for_specs(FindProductsInput(specs=[spec], budget_inr=3500), mock_search)
    assert len(out.outfits) == 1
    chosen = [out.outfits[0].top, out.outfits[0].bottom]
    assert all(p.retailer != "Bewakoof" for p in chosen)  # decoy was the priciest, yet rejected
    assert all(p.verification and p.verification.is_match for p in chosen)
    assert {r.retailer for r in out.rejected} == {"Bewakoof"}
    assert any("color" in reason for r in out.rejected for reason in r.reasons)


def test_hallucinated_search_result_is_rejected_not_shown():
    def liar(spec: ItemSpec) -> list[Product]:
        # looks plausible but contradicts the request on colour and item
        return [_product(title="Premium Silk Saree", price_inr=100, attributes={"color": "gold"})]

    spec = OutfitSpec(top=_spec(category="top", item="t-shirt"), bottom=_spec(), rationale="r")
    out = find_products_for_specs(FindProductsInput(specs=[spec], budget_inr=4000), liar)
    assert out.outfits == []
    assert out.unfilled and "no verified match" in out.unfilled[0].reason
    assert out.rejected


@pytest.mark.parametrize("budget", [1000, 2300])
def test_verified_items_that_break_total_budget_are_unfilled(budget):
    spec = OutfitSpec(top=_spec(category="top", item="t-shirt"), bottom=_spec(), rationale="r")
    out = find_products_for_specs(FindProductsInput(specs=[spec], budget_inr=budget), mock_search)
    assert out.outfits == []
    assert "budget" in out.unfilled[0].reason


def test_a_cheaper_pair_is_used_when_the_two_best_pieces_break_the_budget():
    spec = OutfitSpec(top=_spec(category="top", item="t-shirt"), bottom=_spec(), rationale="r")
    out = find_products_for_specs(FindProductsInput(specs=[spec], budget_inr=2500), mock_search)
    assert len(out.outfits) == 1 and out.outfits[0].total_inr <= 2500  # 1200 + 1200, not the dearest 1900 + 1900


def test_womens_and_kids_items_are_rejected_for_a_male_shopper():
    womens = verify_product(
        _product(title="Women's Peach Baggy Pants", attributes={"color": "peach"}), _spec()
    )
    kids = verify_product(
        _product(title="Boys Peach Baggy Pants", attributes={"color": "peach"}), _spec()
    )
    assert "gender" in womens.blocking and "gender" in kids.blocking


def test_mens_unisex_and_unstated_gender_are_accepted():
    for title in ("Men's Peach Baggy Pants", "Unisex Peach Baggy Pants", "Peach Baggy Pants"):
        assert verify_product(_product(title=title, attributes={"color": "peach"}), _spec()).is_match


def test_same_product_is_not_reused_across_outfits():
    spec = OutfitSpec(top=_spec(category="top", item="t-shirt", color="white"), bottom=_spec(), rationale="r")
    out = find_products_for_specs(FindProductsInput(specs=[spec, spec], budget_inr=4000), mock_search)
    urls = [p.url for o in out.outfits for p in (o.top, o.bottom)]
    assert len(out.outfits) == 2
    assert len(urls) == len(set(urls))
    assert any("duplicate" in r for c in out.rejected for r in c.reasons)


def test_exclude_urls_from_earlier_outfits_are_respected():
    spec = OutfitSpec(top=_spec(category="top", item="t-shirt", color="white"), bottom=_spec(), rationale="r")
    first = find_products_for_specs(FindProductsInput(specs=[spec], budget_inr=4000), mock_search)
    used = [first.outfits[0].top.url, first.outfits[0].bottom.url]
    again = find_products_for_specs(
        FindProductsInput(specs=[spec], budget_inr=4000, exclude_urls=used), mock_search
    )
    assert not set(used) & {again.outfits[0].top.url, again.outfits[0].bottom.url}


def test_out_of_stock_product_is_rejected():
    def sold_out(_spec: ItemSpec) -> list[Product]:
        return [_product(attributes={"color": "peach"}, in_stock=False)]

    spec = OutfitSpec(top=_spec(category="top", item="t-shirt"), bottom=_spec(), rationale="r")
    out = find_products_for_specs(FindProductsInput(specs=[spec], budget_inr=4000), sold_out)
    assert out.outfits == []
    assert any("out of stock" in r for c in out.rejected for r in c.reasons)


# ---- item matching: the garment type must match, descriptive words may be missing -----------------
def _item_spec(item, color="black"):
    return _spec(category="top" if item in ("t-shirt", "polo shirt", "henley", "crewneck t-shirt") else "bottom",
                 item=item, color=color)


def test_right_garment_with_a_missing_descriptive_word_is_accepted_but_low_confidence():
    spec = _item_spec("crewneck t-shirt")
    report = verify_product(_product(title="Men Solid T-Shirt", attributes={"color": "black"}), spec)
    item = next(c for c in report.checks if c.attribute == "item")
    assert item.status == "unknown" and item.assumed  # never reported as a confirmed match
    assert report.is_match and report.confidence == "low"
    assert "crewneck" in item.evidence


def test_a_title_with_every_item_word_is_a_confirmed_item_match():
    report = verify_product(_product(title="Men Crewneck T-Shirt", attributes={"color": "black"}), _item_spec("crewneck t-shirt"))
    assert next(c for c in report.checks if c.attribute == "item").status == "match"


@pytest.mark.parametrize(
    "item,title",
    [
        ("cargo pants", "Men Black Cargo Shorts"),  # shorts are not pants, even though 'cargo' matches
        ("jeans", "Men Black Chinos"),
        ("t-shirt", "Men Black Cotton Trousers"),
        ("polo shirt", "Men Black Cotton T-Shirt"),
        ("overshirt", "Men Black Casual Shirt"),
    ],
)
def test_the_wrong_garment_type_is_still_rejected(item, title):
    report = verify_product(_product(title=title, attributes={"color": "black"}), _item_spec(item))
    assert "item" in report.blocking, (item, title)


def test_a_title_that_just_says_cargos_counts_as_cargo_pants():
    report = verify_product(_product(title="Snitch Men Cargos", attributes={"color": "black"}), _item_spec("cargo pants"))
    assert report.is_match


def test_shirt_synonyms_still_match():
    assert verify_product(_product(title="Men Polo T-Shirt", attributes={"color": "black"}), _item_spec("polo shirt")).is_match


def test_a_different_neckline_than_requested_is_rejected():
    spec = _item_spec("crewneck t-shirt")
    vneck = verify_product(_product(title="Jockey Men Black Solid V-Neck Lounge T-Shirt", attributes={"color": "black"}), spec)
    assert "item" in vneck.blocking
    crew = verify_product(_product(title="Men Black Crew Neck T-Shirt", attributes={"color": "black"}), spec)
    assert crew.is_match and next(c for c in crew.checks if c.attribute == "item").status == "match"
    neutral = verify_product(_product(title="Men Black Solid T-Shirt", attributes={"color": "black"}), spec)
    assert neutral.is_match  # no neckline stated: allowed, flagged as low confidence


# ---- colour the PLANNER chose is a hidden hint: it steers the search but never rejects a product ----
def test_the_planners_own_colour_is_never_checked():
    hint = _spec(color_source="planner")
    for title, attrs in (("Black Baggy Pants", {"color": "Black"}), ("Olive Baggy Pants", {}), ("Baggy Pants", {})):
        report = verify_product(_product(title=title, attributes=attrs), hint)
        assert report.is_match and report.confidence == "high"
        assert all(c.attribute != "color" for c in report.checks)  # no colour verdict at all


def test_no_colour_at_all_is_fine():
    report = verify_product(_product(title="Baggy Pants"), _spec(color=None, color_source="planner"))
    assert report.is_match and all(c.attribute != "color" for c in report.checks)


def test_a_colour_the_shopper_asked_for_is_still_enforced():
    spec = _spec(color="purple")
    assert not verify_product(_product(title="Black Baggy Pants", attributes={"color": "black"}), spec).is_match
    assert verify_product(_product(title="Purple Baggy Pants", attributes={"color": "purple"}), spec).confidence == "high"


def test_the_mock_search_decoy_is_a_womens_item_when_no_colour_was_asked_for():
    spec = ItemSpec(category="top", item="t-shirt", color="olive", max_price_inr=1500)  # planner hint
    out = find_products_for_specs(
        FindProductsInput(specs=[OutfitSpec(top=spec, bottom=_spec(color_source="planner"), rationale="r")], budget_inr=3500),
        mock_search,
    )
    assert len(out.outfits) == 1 and {r.retailer for r in out.rejected} == {"Bewakoof"}
    assert any("gender" in reason for r in out.rejected for reason in r.reasons)
