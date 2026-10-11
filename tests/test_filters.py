from datetime import datetime

from src.chart.engine import compute_chart
from src.dataset import filters
from src.dataset.split import bucket

# Seed-7-like chart: Pisces lagna; Venus 1st, Mercury 2nd, Sun 3rd, Jupiter 4th, Ketu 5th,
# Saturn+Rahu 11th, Moon+Mars 12th. 7th lord = Mercury, 10th lord = Jupiter.
CHART = compute_chart(datetime(1990, 5, 18, 2, 36), 5.5, 19.998, 73.79)


def test_citation_detection():
    assert filters.citation_issue("As BPHS says in Chapter 24, the lord of the seventh...")
    assert filters.citation_issue("Phaladeepika (verse 12) states...")
    assert filters.citation_issue("According to the passage, Saturn delays marriage.")
    assert filters.citation_issue("इति श्री")  # Devanagari verse
    assert not filters.citation_issue("Phaladeepika holds that Saturn in the 7th delays marriage.")


def test_chart_consistency_correct_claims_pass():
    text = ("Your Venus in the 1st house is exalted. Jupiter is in the 4th house. Your 7th lord Mercury "
            "sits in the 2nd house, and Saturn aspects the 5th house.")
    hard, soft = filters.chart_contradictions(text, CHART)
    assert hard == [] and soft == []


def test_chart_consistency_wrong_claims_flagged():
    hard, _ = filters.chart_contradictions("Your Saturn in the 7th house delays marriage.", CHART)
    assert hard
    hard, _ = filters.chart_contradictions("Your 7th lord Venus is exalted.", CHART)
    assert hard


def test_general_rule_is_soft_and_relative_houses_ignored():
    hard, soft = filters.chart_contradictions("Classically, Mars in the 7th house is said to cause friction.", CHART)
    assert hard == [] and len(soft) == 1
    hard, soft = filters.chart_contradictions("Jupiter in the 4th house from the Moon forms Gajakesari.", CHART)
    assert hard == [] and soft == []
    # the house belongs to the planet named last ("Venus in the 1st house")
    hard, soft = filters.chart_contradictions("Saturn aspects Venus in the 1st house.", CHART)
    assert hard == [] and soft == []


def test_length_and_language():
    assert filters.is_english("The seventh house governs marriage and partnerships in the Parashari system.")
    assert not filters.is_english("सप्तम भाव विवाह का कारक है और यह साझेदारी को दर्शाता है।")
    assert filters.word_count("one two three") == 3


def test_check_drops_failed_factcheck():
    answer = ("In the Parashari system the seventh house governs marriage, partnerships and the spouse. "
              "Its lord, the planets placed there and the aspects it receives together describe the "
              "quality and timing of marriage. ") * 6
    row = {"task": "concept", "messages": [{}, {"content": "q"}, {"content": answer}],
           "factcheck": {"verdict": "fail"}}
    assert filters.check(row, None)[0] == "fact check failed"
    row["factcheck"] = {"verdict": "pass"}
    assert filters.check(row, None)[0] is None


def test_minhash_detects_near_duplicates():
    a = ("Saturn in the seventh house is said to delay marriage but often gives a loyal and mature spouse. "
         "Phaladeepika adds that the result depends on the dignity of Saturn and on aspects from benefics. "
         "When Jupiter aspects the seventh house the delay is softened and the marriage becomes stable. "
         "A debilitated Saturn without such support can bring coldness, so the whole chart must be judged, "
         "including the seventh lord, Venus as karaka and the navamsa, before any conclusion is drawn about "
         "the timing or quality of married life in the dasha periods that follow.")
    b = a.replace("loyal", "faithful")
    assert filters.minhash(a).jaccard(filters.minhash(b)) > 0.8


def test_split_bucket_deterministic():
    assert bucket("chunk:bphs-0001") == bucket("chunk:bphs-0001")
    counts = {"train": 0, "val": 0, "test": 0}
    for i in range(2000):
        counts[bucket(f"chunk:x-{i}")] += 1
    assert 0.86 < counts["train"] / 2000 < 0.94
