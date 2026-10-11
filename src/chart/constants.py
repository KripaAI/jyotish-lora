"""Classical reference tables (Parashari) used by the chart engine, yogas and the eval quiz."""

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
SIGNS_SANSKRIT = ["Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
                  "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena"]

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
SEVEN = PLANETS[:7]
PLANETS_SANSKRIT = {"Sun": "Surya", "Moon": "Chandra", "Mars": "Mangala", "Mercury": "Budha",
                    "Jupiter": "Guru", "Venus": "Shukra", "Saturn": "Shani", "Rahu": "Rahu", "Ketu": "Ketu"}

SIGN_LORD = ["Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
             "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter"]

EXALTATION = {"Sun": 0, "Moon": 1, "Mars": 9, "Mercury": 5, "Jupiter": 3, "Venus": 11,
              "Saturn": 6, "Rahu": 1, "Ketu": 7}  # sign index; nodes per the common Parashari view
DEBILITATION = {p: (s + 6) % 12 for p, s in EXALTATION.items()}
OWN_SIGNS = {"Sun": [4], "Moon": [3], "Mars": [0, 7], "Mercury": [2, 5], "Jupiter": [8, 11],
             "Venus": [1, 6], "Saturn": [9, 10]}
# (sign index, start degree, end degree)
MOOLATRIKONA = {"Sun": (4, 0, 20), "Moon": (1, 3, 30), "Mars": (0, 0, 12), "Mercury": (5, 15, 20),
                "Jupiter": (8, 0, 10), "Venus": (6, 0, 15), "Saturn": (10, 0, 20)}

# Naisargika (natural) relationships
FRIENDS = {"Sun": ["Moon", "Mars", "Jupiter"], "Moon": ["Sun", "Mercury"],
           "Mars": ["Sun", "Moon", "Jupiter"], "Mercury": ["Sun", "Venus"],
           "Jupiter": ["Sun", "Moon", "Mars"], "Venus": ["Mercury", "Saturn"],
           "Saturn": ["Mercury", "Venus"]}
ENEMIES = {"Sun": ["Venus", "Saturn"], "Moon": [], "Mars": ["Mercury"], "Mercury": ["Moon"],
           "Jupiter": ["Mercury", "Venus"], "Venus": ["Sun", "Moon"], "Saturn": ["Sun", "Moon", "Mars"]}

NATURAL_BENEFICS = ["Jupiter", "Venus", "Mercury", "Moon"]
NATURAL_MALEFICS = ["Sun", "Mars", "Saturn", "Rahu", "Ketu"]

# Graha drishti: houses counted from the planet's own house (1 = itself)
SPECIAL_ASPECTS = {"Mars": [4, 7, 8], "Jupiter": [5, 7, 9], "Saturn": [3, 7, 10]}
DEFAULT_ASPECTS = [7]

# Combustion orbs in degrees from the Sun (retrograde orbs for Mercury/Venus)
COMBUST_ORB = {"Moon": 12, "Mars": 17, "Mercury": 14, "Jupiter": 11, "Venus": 10, "Saturn": 15}
COMBUST_ORB_RETRO = {"Mercury": 12, "Venus": 8}

NAKSHATRAS = ["Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
              "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra",
              "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha",
              "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"]
DASHA_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
NAKSHATRA_LORD = [DASHA_ORDER[i % 9] for i in range(27)]
DASHA_YEARS = {"Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7, "Rahu": 18,
               "Jupiter": 16, "Saturn": 19, "Mercury": 17}
NAK_SPAN = 360 / 27

KENDRAS = [1, 4, 7, 10]
TRIKONAS = [1, 5, 9]
DUSTHANAS = [6, 8, 12]

HOUSE_THEMES = {
    1: "self, body, personality, overall life direction", 2: "wealth, family, speech, food",
    3: "courage, siblings, communication, short travel", 4: "mother, home, property, vehicles, inner peace",
    5: "children, intelligence, creativity, past merit (purva punya)", 6: "enemies, disease, debts, service, competition",
    7: "marriage, spouse, partnerships", 8: "longevity, sudden events, inheritance, occult",
    9: "fortune, father, dharma, guru, long journeys", 10: "career, status, karma, authority",
    11: "gains, income, elder siblings, fulfilment of desires", 12: "losses, expenses, foreign lands, moksha, sleep",
}

FIXED_KARAKAS = {"Sun": "soul, father, authority", "Moon": "mind, mother", "Mars": "courage, siblings, land",
                 "Mercury": "intellect, speech, commerce", "Jupiter": "wisdom, children, guru, wealth",
                 "Venus": "spouse (for men), comforts, arts", "Saturn": "longevity, sorrow, service, discipline",
                 "Rahu": "obsession, foreign elements", "Ketu": "detachment, spirituality"}


def ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
