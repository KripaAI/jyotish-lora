"""Evaluation v2 plumbing: the chart-claim checker verifies against the engine, and the code quiz grader matches answers."""
from src.chart.births import chart_for_seed
from src.chart.constants import ordinal
from src.chart.render import houses_from
from src.eval.claims import check_claims
from src.eval.run_eval_v2 import quiz_code_correct


def test_claims_true_statements_verify_and_false_ones_fail():
    chart = chart_for_seed(1_000_003)
    by = {p["name"]: p for p in chart["planets"]}
    lords = {h["house"]: h["lord"] for h in chart["houses"]}
    moon = houses_from(chart, "Moon")
    venus, mars = by["Venus"], by["Mars"]
    wrong_house = venus["house"] % 12 + 1
    from_moon = next(r["house"] for r in moon if "Mars" in r["occupants"])
    text = (f"Your Venus is in the {ordinal(venus['house'])} house in {venus['sign']}. The 7th lord is {lords[7]}. "
            f"Mars is in the {ordinal(from_moon)} house from the Moon. Jupiter aspects the {ordinal(by['Jupiter']['aspects_houses'][0])} house. "
            f"Saturn sits in the {ordinal(wrong_house)} house.")
    claims = check_claims(text, chart)
    kinds = {c["kind"]: c["ok"] for c in claims if c["kind"] != "planet_in_house"}
    assert kinds["lord"] and kinds["from_moon"] and kinds["aspect"]
    houses = [c for c in claims if c["kind"] == "planet_in_house"]
    assert len(houses) == 2 and houses[0]["ok"] is True
    assert houses[1]["ok"] == (by["Saturn"]["house"] == wrong_house)


def test_claims_ignore_general_rules_with_another_planet_between():
    chart = chart_for_seed(1_000_003)
    assert check_claims("Jupiter with Venus in the 3rd house is a classic combination.", chart) == []


def test_quiz_code_grader_matches_any_accepted_spelling():
    item = {"answers": ["Jupiter", "Guru", "Brihaspati"]}
    assert quiz_code_correct(item, "Hamsa yoga is given by Guru (Jupiter) in a kendra.")
    assert not quiz_code_correct(item, "It is formed by Saturn.")
    assert quiz_code_correct({"answers": ["3, 6, 10 and 11"]}, "The upachaya houses are 3, 6, 10 and 11.")
