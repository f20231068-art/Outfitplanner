"""The reader: a model judges real, already-checked candidate products against what the shopper asked for.

What these tests pin down: it can only keep or drop real candidates (never add one), it is used only when the shopper
asked for something specific, pieces that ask for the same thing share one search and one reading, one extra search at most
when too few fit, and a failing model never breaks a search."""

import json

from api.agent.find import find_products_for_specs
from api.agent.judge import make_judge, safe_judge
from api.agent.schemas import (
    CandidateVerdict,
    FindProductsInput,
    ItemSpec,
    JudgeResult,
    OutfitSpec,
    Product,
)
from api.config import settings


def tee(n: int, colour: str | None = None, price: int = 800, title: str | None = None, **kw) -> Product:
    return Product(
        title=title or f"Oversized T-Shirt {n}", retailer="Snitch", price_inr=price, url=f"https://snitch.com/products/tee-{n}",
        image_url="https://i", color=colour, attributes={"gender": "men", **({"color": colour} if colour else {})},
        in_stock=True, **kw,
    )


def jeans(n: int, price: int = 1200) -> Product:
    return Product(
        title=f"Baggy Jeans {n}", retailer="Spykar", price_inr=price, url=f"https://spykar.com/products/jeans-{n}",
        image_url="https://i", attributes={"gender": "men"}, in_stock=True,
    )


def fixed_spec(i: int = 0) -> OutfitSpec:
    """The shopper fixed 'a white oversized t-shirt' and 'baggy jeans' for every outfit."""
    return OutfitSpec(
        top=ItemSpec(category="top", item="t-shirt", fit="oversized", color="white", color_source="user",
                     fixed=["item", "fit", "color"], max_price_inr=2000 + i),
        bottom=ItemSpec(category="bottom", item="jeans", fit="baggy", max_price_inr=2500 + i, fixed=["item", "fit"]),
        rationale="r",
    )


def verdicts(*top_rounds: dict, bottom: dict | None = None):
    """A judge with fixed answers: {candidate number: 'yes' | 'no' | 'unsure', 'retry': keywords}. Each call for a top takes the
    next answer in `top_rounds` (the last one repeats); bottoms always get `bottom`. Records what it was asked."""
    asked: list[dict] = []
    calls = {"top": 0, "bottom": 0}
    rounds = {"top": list(top_rounds) or [{}], "bottom": [bottom or {}]}

    def judge(spec, candidates, shopper_words, style, needed):
        n = calls[spec.category]
        calls[spec.category] += 1
        answer = rounds[spec.category][min(n, len(rounds[spec.category]) - 1)]
        asked.append({"spec": spec, "titles": [c.title for c in candidates], "words": shopper_words, "needed": needed})
        return JudgeResult(
            verdicts=[CandidateVerdict(number=i, fits=answer.get(i, "unsure"), reason=f"reason {i}")
                      for i in range(1, len(candidates) + 1)],
            retry_keywords=answer.get("retry"),
        )

    judge.asked = asked  # type: ignore[attr-defined]
    return judge


class Search:
    def __init__(self, tops, bottoms, retry_tops=None):
        self.tops, self.bottoms, self.retry_tops, self.calls = tops, bottoms, retry_tops or [], []

    def __call__(self, spec: ItemSpec):
        self.calls.append(spec)
        if spec.category == "bottom":
            return list(self.bottoms)
        return list(self.tops) + (list(self.retry_tops) if spec.keywords else [])


def run(search, judge, specs=None, words="a white oversized tshirt and baggy jeans"):
    inp = FindProductsInput(specs=specs or [fixed_spec()], budget_inr=4500, shopper_words=words, style="Streetwear")
    return find_products_for_specs(inp, search, judge)


# ---- it keeps or drops real products ---------------------------------------------------------------------------
def test_the_reader_drops_what_it_says_does_not_fit_and_prefers_what_it_says_fits():
    top_a, top_b, top_c = tee(1, price=1900), tee(2, price=900), tee(3, price=1500)
    judge = verdicts({1: "no", 2: "yes", 3: "unsure"})  # numbering follows the order the candidates were shown in
    out = run(Search([top_a, top_b, top_c], [jeans(1)]), judge)
    shown_order = judge.asked[0]["titles"]
    assert len(out.outfits) == 1
    chosen = out.outfits[0].top
    verdict_of = {t: v for t, v in zip(shown_order, ["no", "yes", "unsure"], strict=True)}
    assert verdict_of[chosen.title] == "yes"  # the reader's yes beats a higher price
    assert any(r.reasons[0].startswith("reader: reason") for r in out.rejected)


def test_the_reader_only_sees_products_that_already_passed_the_rule_based_check():
    womens = Product(title="Women's Oversized T-Shirt", retailer="X", price_inr=800, url="https://x/w", image_url="https://i",
                     attributes={"gender": "women"}, in_stock=True)
    wrong_colour = tee(9, colour="Black")
    out = run(Search([tee(1), womens, wrong_colour], [jeans(1)]), judge := verdicts({1: "yes"}))
    assert judge.asked[0]["titles"] == ["Oversized T-Shirt 1"]  # the women's item and the black tee never reach it
    assert len(out.outfits) == 1


def test_a_yes_from_the_reader_cannot_rescue_a_product_the_rules_rejected():
    judge = verdicts({1: "yes", 2: "yes"})
    out = run(Search([tee(1, colour="Black"), tee(2, price=5000)], [jeans(1)]), judge)  # wrong colour; over the price cap
    assert out.outfits == [] and out.unfilled


def test_the_reader_is_not_called_when_the_shopper_asked_for_nothing_specific():
    spec = OutfitSpec(top=ItemSpec(category="top", item="t-shirt", color="blue", max_price_inr=2000),  # planner's own colour
                      bottom=ItemSpec(category="bottom", item="jeans", max_price_inr=2500), rationale="r")
    judge = verdicts()
    out = run(Search([tee(1)], [jeans(1)]), judge, specs=[spec], words="")
    assert judge.asked == [] and len(out.outfits) == 1


# ---- pieces that ask for the same thing share one search and one reading ---------------------------------------
def test_four_outfits_with_the_same_fixed_pieces_cost_one_search_and_one_reading_each():
    search = Search([tee(i, price=800 + i * 10) for i in range(1, 6)], [jeans(i, price=1200 + i) for i in range(1, 6)])
    all_yes = {i: "yes" for i in range(1, 6)}
    judge = verdicts(all_yes, bottom=all_yes)
    out = run(search, judge, specs=[fixed_spec(i) for i in range(4)])
    assert len(search.calls) == 2 and len(judge.asked) == 2  # one for the tops, one for the bottoms (not 8)
    assert len(out.outfits) == 4
    assert len({o.top.url for o in out.outfits}) == 4 and len({o.bottom.url for o in out.outfits}) == 4  # each takes its own


# ---- one extra search, with the reader's own words, when too few fit -----------------------------------------------
def test_when_too_few_fit_the_search_is_repeated_once_with_the_readers_keywords():
    search = Search([tee(1)], [jeans(1)], retry_tops=[tee(2)])
    judge = verdicts({1: "no", "retry": "boxy drop shoulder"}, {1: "yes"})
    out = run(search, judge)
    assert [c.keywords for c in search.calls if c.category == "top"] == [None, "boxy drop shoulder"]
    assert len(judge.asked) == 3  # tops, tops again, bottoms
    assert len(out.outfits) == 1


def test_the_search_is_repeated_at_most_once_however_poorly_it_goes(monkeypatch):
    monkeypatch.setattr(settings, "judge_search_retries", 1)
    search = Search([tee(1)], [jeans(1)], retry_tops=[tee(2)])
    run(search, verdicts({1: "no", "retry": "more words"}))
    assert sum(c.category == "top" for c in search.calls) == 2


def test_no_extra_search_when_the_reader_offers_no_keywords_or_retries_are_off(monkeypatch):
    search = Search([tee(1)], [jeans(1)])
    run(search, verdicts({1: "no"}))
    assert sum(c.category == "top" for c in search.calls) == 1
    monkeypatch.setattr(settings, "judge_search_retries", 0)
    search = Search([tee(1)], [jeans(1)])
    run(search, verdicts({1: "no", "retry": "boxy"}))
    assert sum(c.category == "top" for c in search.calls) == 1


# ---- a failing model never breaks a search --------------------------------------------------------------------
def test_a_failing_reader_leaves_the_rule_based_result_standing():
    def broken(*args):
        raise RuntimeError("model down")

    out = run(Search([tee(1)], [jeans(1)]), broken)
    assert len(out.outfits) == 1 and out.search_errors == []


def test_a_candidate_the_reader_does_not_mention_is_neither_kept_nor_dropped():
    def partial(spec, candidates, *_):
        return JudgeResult(verdicts=[CandidateVerdict(number=1, fits="no", reason="wrong fit")])

    found, retry = safe_judge(partial, fixed_spec().top, [tee(1), tee(2)], "", "", 1)
    assert found == {tee(1).url: ("no", "wrong fit"), tee(2).url: ("unsure", "")} and retry is None


# ---- what the model is told ---------------------------------------------------------------------------------------
def test_the_prompt_separates_what_the_shopper_fixed_from_the_planners_hints():
    seen = {}

    def structured(schema, system, human):
        seen.update(schema=schema, system=system, context=json.loads(human))
        return JudgeResult(verdicts=[])

    spec = ItemSpec(category="top", item="t-shirt", fit="oversized", color="white", color_source="user",
                    fixed=["item", "fit", "color"], fabric="cotton", max_price_inr=2000, avoid_colors=["black"])
    make_judge(structured)(spec, [tee(1, details="Boxy fit, 100% cotton", colour="Off White")], "white tshirt", "Streetwear", 4)
    ctx = seen["context"]
    assert ctx["required"] == {"item": "t-shirt", "color": "white", "fit": "oversized"}
    assert ctx["planner_hints_not_required"] == {"fabric": "cotton"}
    assert ctx["avoid_colours"] == ["black"] and ctx["products_needed"] == 4 and ctx["shopper_words"] == "white tshirt"
    candidate = ctx["candidates"][0]
    assert candidate["page_description"] == "Boxy fit, 100% cotton" and candidate["colour_stated_by_page"] == "Off White"
    assert candidate["link_words"] == "tee 1" and set(candidate) >= {"number", "title", "store", "price_inr"}
    assert "never invent" in seen["system"].lower()


def test_a_planners_colour_is_a_hint_the_reader_must_not_reject_for():
    seen = {}

    def structured(schema, system, human):
        seen["context"] = json.loads(human)
        return JudgeResult(verdicts=[])

    spec = ItemSpec(category="top", item="t-shirt", color="blue", max_price_inr=2000)  # chosen by the planner
    make_judge(structured)(spec, [tee(1)], "", "", 1)
    assert seen["context"]["required"] == {"item": "t-shirt"} and seen["context"]["planner_hints_not_required"] == {"color": "blue"}


# ---- a second search aims at the stores that specialise in the garment ----------------------------------------------------
def test_the_second_search_for_jeans_covers_only_the_denim_stores():
    wide = ItemSpec(category="bottom", item="jeans", fit="baggy", max_price_inr=2500, fixed=["item", "fit"], store_groups=["streetwear", "denim"])
    spec = OutfitSpec(top=fixed_spec().top, bottom=wide, rationale="r")
    search = Search([tee(1)], [jeans(1)])
    run(search, verdicts({1: "yes"}, bottom={1: "no"}), specs=[spec])
    seen = [c.store_groups for c in search.calls if c.category == "bottom"]
    assert seen == [["streetwear", "denim"], ["denim"], ["smart_casual", "activewear"]]  # broad, the specialists, then the rest


def test_after_the_specialists_the_everyday_clothing_stores_are_tried():
    only_denim = ItemSpec(category="bottom", item="jeans", fit="baggy", max_price_inr=2500, fixed=["item", "fit"], store_groups=["denim"])
    search = Search([tee(1)], [jeans(1)])
    run(search, verdicts({1: "yes"}, bottom={1: "no"}), specs=[OutfitSpec(top=fixed_spec().top, bottom=only_denim, rationale="r")])
    seen = [c.store_groups for c in search.calls if c.category == "bottom"]
    assert seen[:2] == [["denim"], ["streetwear", "smart_casual", "activewear"]]  # (a third try finds nothing new to look at)
    assert len(seen) == 2


def test_a_second_search_for_a_top_covers_the_stores_the_first_did_not():
    top = ItemSpec(category="top", item="t-shirt", fit="oversized", max_price_inr=2500, fixed=["item", "fit"], store_groups=["streetwear"])
    search = Search([tee(1)], [jeans(1)])
    run(search, verdicts({1: "no"}), specs=[OutfitSpec(top=top, bottom=fixed_spec().bottom, rationale="r")])
    assert [c.store_groups for c in search.calls if c.category == "top"] == [["streetwear"], ["smart_casual", "activewear"]]


def test_where_the_second_try_looks():
    from api.agent.stores import second_try_groups

    assert second_try_groups("baggy jeans", [["streetwear", "denim"]]) == ["denim"]  # the specialists
    assert second_try_groups("baggy jeans", [["streetwear", "denim"], ["denim"]]) == ["smart_casual", "activewear"]  # then the rest
    assert second_try_groups("baggy jeans", [["streetwear", "denim"], ["denim"], ["smart_casual", "activewear"]]) == []
    assert second_try_groups("t-shirt", [["streetwear", "smart_casual"]]) == ["activewear"]  # what was not covered
    assert second_try_groups("t-shirt", [["streetwear", "smart_casual", "activewear"]]) == []  # nothing new to try
    assert second_try_groups("t-shirt", [[]]) == [] and second_try_groups("t-shirt", []) == []  # every store was searched


def test_one_design_listed_under_several_links_is_shown_once():
    twins = [jeans(i).model_copy(update={"title": "Wrangler Men Blue Jeans", "image_url": "https://img/same.jpg"}) for i in (1, 2, 3)]
    other = jeans(4).model_copy(update={"title": "Killer Light Blue Jeans", "image_url": "https://img/other.jpg"})
    out = run(Search([tee(i) for i in range(1, 5)], twins + [other]), None, specs=[fixed_spec(i) for i in range(3)])
    titles = [o.bottom.title for o in out.outfits]
    assert sorted(titles) == ["Killer Light Blue Jeans", "Wrangler Men Blue Jeans"]  # not the same Wrangler three times


# ---- putting a top and a bottom together within the budget -----------------------------------------------------------------
def test_when_the_two_best_pieces_are_over_budget_the_best_pair_that_fits_is_used():
    dear_top, cheaper_top = tee(1, price=2200), tee(2, price=1500)
    dear_jeans, fair_jeans = jeans(1, price=2900), jeans(2, price=2300)
    spec = OutfitSpec(top=fixed_spec().top.model_copy(update={"max_price_inr": 3000}),
                      bottom=fixed_spec().bottom.model_copy(update={"max_price_inr": 3000}), rationale="r")
    out = find_products_for_specs(
        FindProductsInput(specs=[spec], budget_inr=4500), Search([dear_top, cheaper_top], [dear_jeans, fair_jeans]), None
    )
    assert len(out.outfits) == 1
    outfit = out.outfits[0]
    assert outfit.total_inr <= 4500 and outfit.top.price_inr == 2200 and outfit.bottom.price_inr == 2300  # best top kept, bottom stepped down


def test_when_no_pair_fits_the_budget_the_outfit_is_reported_unfilled():
    out = find_products_for_specs(
        FindProductsInput(specs=[fixed_spec()], budget_inr=1500), Search([tee(1, price=800)], [jeans(1, price=900)]), None
    )
    assert out.outfits == [] and out.unfilled[0].reason == "verified items exceed the total budget together"


def test_a_product_the_reader_could_not_confirm_is_shown_but_flagged_low_confidence():
    unsure = run(Search([tee(1)], [jeans(1)]), verdicts({1: "unsure"}, bottom={1: "yes"}))
    assert len(unsure.outfits) == 1 and unsure.outfits[0].top.verification.confidence == "low" and unsure.outfits[0].confidence == "low"
    sure = run(Search([tee(1)], [jeans(1)]), verdicts({1: "yes"}, bottom={1: "yes"}))
    # (the colour is not stated on this fake page, so the rules also call it low confidence: compare the reader's effect alone)
    plain = ItemSpec(category="top", item="t-shirt", fit="oversized", max_price_inr=2000, fixed=["item", "fit"])
    spec = OutfitSpec(top=plain, bottom=fixed_spec().bottom, rationale="r")
    yes = run(Search([tee(1)], [jeans(1)]), verdicts({1: "yes"}, bottom={1: "yes"}), specs=[spec])
    no_reader = run(Search([tee(1)], [jeans(1)]), None, specs=[spec])
    assert yes.outfits[0].top.verification.confidence == no_reader.outfits[0].top.verification.confidence == "high"
    assert sure.outfits
