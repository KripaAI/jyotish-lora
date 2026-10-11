"""Ordinary personal astrology questions, written in the same style as the sensitive ones in safety_v2.

The learned safety screen (src/app/safety_clf.py) first learned "personal story with a first-person voice = sensitive"
because the normal examples came from the textbook-style training questions. These negatives remove that shortcut: the
same range of personas, lengths and tones, but nothing sensitive.

    python -m src.dataset.safety_normals     # -> data/dpo/normals/questions.jsonl (resumable)
"""
from __future__ import annotations

from src.common import DATA
from src.dataset import safety_v2 as sv

DIR = DATA / "dpo" / "normals"

TOPICS = {
    "marriage_timing": "asking when they might marry, what kind of partner suits them, or how a chart reads for relationships and compatibility in general",
    "career": "asking about career direction, which field suits them, a job change, a promotion period, or whether to study further",
    "education": "a student or parent asking about study streams, exams in general terms, concentration, or good periods for learning",
    "relocation_abroad": "asking about moving cities, settling or studying abroad, or travel in general terms",
    "business": "asking about starting a business in general terms, partnership style, or good phases for effort, with no investment or trading questions",
    "family_children": "asking about parenting, relationships with parents or siblings, or the general outlook on having children, with no medical or fertility worry",
    "personality": "asking about their temperament, strengths, talents, habits, communication style or what their ascendant and Moon say about them",
    "dasha_transit": "asking what the running dasha or a transit such as Saturn or Jupiter generally means for them, with curiosity and no fear",
    "muhurta_naming": "asking for an auspicious day for a housewarming or ceremony, or about name letters, in a casual way",
    "learning_astrology": "someone studying Jyotish asking how to read a placement, yoga, house or nakshatra, or how two traditions differ",
    "remedies_simple": "asking calmly about simple optional practices such as a mantra for peace, a fast or lamp lighting, or what a gemstone traditionally signifies, with no pressure from anyone",
    "wellbeing_general": "asking about work-life balance, stress at work, sleep routines or motivation in a general, non-medical way and how the chart describes their energy",
}
PER_TOPIC = 40   # about 40 messages per topic, written in batches of 10


def main() -> None:
    system = (
        "You write realistic user messages for a dataset that teaches an AI Vedic astrologer to tell ordinary questions "
        "from sensitive ones. Write the requested number of distinct, ORDINARY messages that a real person might send "
        "for the given topic. They must NOT contain anything sensitive: no questions about death, serious illness, "
        "pregnancy outcomes, court cases, stocks or gambling, self-harm, stigma, fear-selling of remedies, third-party "
        "snooping, harming anyone, or demands for a guarantee.\n"
        "Match the style of real chat messages: vary the persona (age, gender, region of India or the diaspora), length "
        "(from one short sentence to a few sentences), tone (curious, hopeful, casual, formal, a little worried about "
        "everyday things), and language (some plain English, some mixing Hindi words in Roman script). Many should be "
        "first-person and personal ('Will I...', 'When will I...', 'I am 27 and...'), because those are the messages "
        "that must NOT be blocked. Set needs_chart true when the message refers to 'my chart' or asks for a reading "
        "of their own placements, otherwise false.")

    jobs = [{"key": f"{t}-{i}", "topic": t, "desc": d} for t, d in TOPICS.items() for i in range(PER_TOPIC // 10)]

    def fn(j):
        res = sv._call(f"sn-{j['key']}", system, f"TOPIC: {j['topic']}\nTHE PERSON IS: {j['desc']}\n\nWrite 10 messages.",
                       sv.SONNET, "medium", sv.QUESTION_SCHEMA)
        if res["type"] != "succeeded":
            return None
        import json
        return {"key": j["key"], "topic": j["topic"], "messages": json.loads(res["text"])["messages"]}

    sv._run(jobs, DIR / "questions.jsonl", fn)


if __name__ == "__main__":
    main()
