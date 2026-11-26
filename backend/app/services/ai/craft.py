"""Task-specific prompt craft: one focused brief per AI task instead of one generic system prompt.

What lives here is judgement an experienced local-marketing consultant would apply, written down so the model gets it every time:
  * PLAYBOOKS: what customers of each kind of business actually care about, which post angles work, and what to stay away from;
  * LANGUAGE_STYLE: how a real person at an Indian business writes in English, Hindi and Hinglish (not translated brochure copy);
  * POST_TYPES: eight kinds of Google Post, each with its own structure, so a week of posts is a week of different ideas;
  * OCCASIONS: seasons and festivals around a date, as general windows (lunar dates move, so no exact dates are claimed);
  * per-sentiment reply guidance.

Nothing here adds facts about a business. Facts come only from the business context (services/ai/intelligence.py) and are still checked
by services/agent/safety.py after generation.
"""
from __future__ import annotations

import re
from datetime import date

# ------------------------------------------------------------------ playbooks by kind of business
PLAYBOOKS: dict[str, dict] = {
    "physio": {
        "match": ("physio", "physical therapy", "rehab", "chiropract", "orthop"),
        "care": "pain that limits daily life, desk-job posture and neck/back strain, sports and post-surgery recovery, whether the therapist explains the plan, punctuality, how many sessions to expect",
        "angles": ["a simple posture or movement habit for desk workers (general, not a prescription)", "what a first assessment visit involves, step by step", "when to see a physiotherapist instead of waiting it out",
                   "myth versus fact about back pain", "what to bring and wear to a first session", "how appointments and follow-ups work", "seasonal strain: cold-weather stiffness, monsoon slips, festival-season long drives"],
        "avoid": "promising recovery, cure or timelines; naming conditions as if diagnosing; before/after claims",
    },
    "dental": {
        "match": ("dental", "dentist", "orthodont", "implant"),
        "care": "fear of pain, clear explanation of treatment and cost before starting, hygiene and sterilisation, kids' comfort, emergency availability, how long a visit takes",
        "angles": ["how often to get a check-up and what it covers", "a brushing/flossing habit that is easy to keep", "what to do for a sudden toothache before the visit", "what happens in a routine cleaning",
                   "braces and aligners: questions to ask any dentist", "child's first dental visit: what to expect", "sweets-season care for teeth"],
        "avoid": "painless guarantees, 'best dentist' claims, prices not provided, outcome promises",
    },
    "salon": {
        "match": ("salon", "beauty", "parlour", "parlor", "spa", "barber", "hair", "makeup", "bridal", "nail"),
        "care": "skill with the specific service, hygiene and clean tools, listening to what the customer wants, waiting time, products used, bridal and festival bookings",
        "angles": ["a hair or skin care routine tip for the current season", "how to prepare for a bridal trial", "what to ask for so a haircut suits your face and routine", "how long a service usually takes so people can plan",
                   "wedding and festival season booking reminder (no invented slots)", "care after a colour or smoothing service (general)", "a behind-the-counter look at how tools are cleaned"],
        "avoid": "invented offers or packages, 'guaranteed results', staff names not provided",
    },
    "restaurant": {
        "match": ("restaurant", "cafe", "café", "dhaba", "bakery", "sweets", "food", "kitchen", "biryani", "pizza", "catering", "tiffin"),
        "care": "taste and freshness, portion and value, cleanliness, wait time, family seating, veg/non-veg clarity, delivery reliability",
        "angles": ["one dish and what makes it worth ordering (only dishes provided)", "a seasonal ingredient or festival-time menu (only if provided)", "when it is least crowded to visit",
                   "family or group seating and how to plan a visit", "how to place a bulk or party order (only if provided)", "the story of one signature item as told by the owner", "monsoon or winter comfort food theme"],
        "avoid": "invented dishes, prices or discounts, hygiene ratings, 'best in city'",
    },
    "gym": {
        "match": ("gym", "fitness", "yoga", "crossfit", "zumba", "pilates", "martial", "trainer"),
        "care": "trainer attention, equipment that works and is clean, crowd at peak hours, beginner friendliness, realistic expectations, timings",
        "angles": ["how a beginner should structure the first month (general, no medical claims)", "what a first visit or trial involves", "a form tip for a common exercise (general, safe)", "how to stay consistent when routine breaks (festivals, exams)",
                   "off-peak timings for a quieter workout", "what to ask a gym before joining", "monsoon or winter workout motivation"],
        "avoid": "weight-loss or body-transformation promises, before/after claims, invented membership prices",
    },
    "retail": {
        "match": ("store", "shop", "mart", "boutique", "showroom", "retail", "garment", "jewel", "electronics", "furniture", "stationery", "grocery", "kirana", "supermarket", "toys", "mobile"),
        "care": "availability, honest advice, fair price, return and exchange clarity, service after sale, easy parking and timings",
        "angles": ["one product category and how to choose well (only categories provided)", "new stock or a back-in-stock item (only if provided)", "festival gifting ideas using only listed products", "how exchange or return works (only if provided)",
                   "a buying guide for something customers often ask about", "store timings around a holiday", "care and maintenance tip for something sold here"],
        "avoid": "invented discounts, 'lowest price' claims, brands not provided",
    },
    "coaching": {
        "match": ("coaching", "tuition", "academy", "institute", "classes", "school", "education", "training", "learning", "tutor", "ielts", "neet", "jee", "upsc", "study"),
        "care": "teaching quality and doubt clearing, batch size, regular tests and feedback, honest guidance, discipline without pressure, fee transparency",
        "angles": ["a study-routine tip for the exam season", "how demo classes and batches work (only if provided)", "how parents can support without adding pressure", "how to use a mock test to find weak areas",
                   "what to ask a coaching centre before enrolling", "managing time in the last month before exams", "new batch timings (only if provided)"],
        "avoid": "result or rank claims, selection numbers, guaranteed success, invented fees",
    },
}
DEFAULT_PLAYBOOK = {
    "care": "reliable service, honest communication, fair value, cleanliness, being easy to reach",
    "angles": ["one service and who it helps", "how a first visit works", "a practical tip related to what the business does", "answer a question customers often ask", "timings and the easiest way to reach the business",
               "something customers should know this season"],
    "avoid": "claims the owner has not provided, invented offers, superlatives",
}


def playbook(category: str | None) -> dict:
    c = (category or "").lower()
    for pb in PLAYBOOKS.values():
        if any(m in c for m in pb["match"]):
            return pb
    return DEFAULT_PLAYBOOK


# ------------------------------------------------------------------ language
LANGUAGE_STYLE = {
    "en": "Plain, warm Indian-business English: short sentences, everyday words, no corporate jargon, no exclamation-mark stacking.",
    "hi": ("Hindi in Devanagari, in simple spoken Hindi the way a shop owner would say it, not Sanskritised or translated-brochure Hindi. Short sentences. "
           "English words people really use (clinic, appointment, booking, doctor) may stay in Devanagari spelling."),
    "hinglish": ("Hinglish: Hindi in Roman letters mixed with English the way people text on WhatsApp ('Aapka feedback padhkar accha laga', 'appointment ke liye call kar sakte hain'). "
                 "Keep grammar natural, spelling consistent (aap, hai, hain, nahi, bahut), no Devanagari, never a stiff word-for-word translation."),
}

# ------------------------------------------------------------------ post types
POST_TYPES: dict[str, dict] = {
    "educational": {"label": "Educational tip", "brief": "Teach one small, useful, general thing about the business's field that a local customer can use today. Open with the problem or question the reader has.",
                    "needs": None},
    "service": {"label": "Service highlight", "brief": "Spotlight ONE listed service: who it helps, what a visit or session involves, and what to expect. Concrete, not promotional.", "needs": "services"},
    "update": {"label": "Business update", "brief": "Share a plain practical update that is true from the facts: opening hours, how to book, how to reach, what the visit is like. Useful, not exciting.", "needs": None},
    "seasonal": {"label": "Seasonal note", "brief": "Connect the business to the current season or occasion with one genuinely relevant, claim-free point. No invented festival offers, no invented dates.", "needs": None},
    "offer": {"label": "Verified offer", "brief": "Present ONE verified offer exactly as written (name, price and validity as given). State who it is for and how to take it up.", "needs": "offers"},
    "event": {"label": "Event or announcement", "brief": "Announce something with a date only if one is given in the facts; otherwise do not write an event.", "needs": "never_auto"},
    "faq": {"label": "Question answered", "brief": "Answer ONE frequently asked question from the facts in two or three sentences, using the answer given. Open with the question in the customer's words.", "needs": "faqs"},
    "engagement": {"label": "Customer question", "brief": "Ask readers one easy, relevant question about their preference or routine and say what the business can help with. No giveaways, no 'like and share'.", "needs": None},
}
POST_ORDER = ["educational", "service", "faq", "seasonal", "update", "engagement", "offer"]  # rotation; 'offer' only when a verified offer exists


def pick_post_type(kb: dict, *, day: int, recent_types: list[str] | None = None) -> str:
    """A different kind of post each time: rotate by day, skip types the business has no facts for, and skip what it just posted."""
    avail = []
    for t in POST_ORDER:
        need = POST_TYPES[t]["needs"]
        if need == "offers" and not kb.get("offers"):
            continue
        if need == "faqs" and not kb.get("faqs"):
            continue
        if need == "services" and not kb.get("services"):
            continue
        avail.append(t)
    recent = set((recent_types or [])[:2])
    fresh = [t for t in avail if t not in recent] or avail
    return fresh[day % len(fresh)]


def classify_post(text: str) -> str:
    """Rough type of an existing post, so the next one can differ. Heuristic; 'update' is the fallback."""
    t = (text or "").lower()
    if re.search(r"₹|\boffer\b|discount|% off", t):
        return "offer"
    if "?" in t[:160]:
        return "faq" if re.search(r"\b(what|how|when|can|do|is|does)\b", t[:60]) else "engagement"
    if re.search(r"\b(tip|habit|avoid|myth|remember|should|try)\b", t):
        return "educational"
    if re.search(r"\b(open|timing|hours|monday|sunday|call|book)\b", t):
        return "update"
    if re.search(r"\b(diwali|holi|monsoon|winter|summer|festival|season|new year|navratri|eid|christmas)\b", t):
        return "seasonal"
    return "service"


# ------------------------------------------------------------------ occasions
# General windows only. Lunar and regional festivals move every year, so they are named as "around" a month, never given an exact date.
_OCCASIONS = {
    1: ["New Year resolutions", "Lohri / Makar Sankranti / Pongal (mid-January)", "Republic Day (26 Jan)", "winter cold and dry air", "school board-exam preparation begins"],
    2: ["wedding season", "board exams", "Valentine's Day (14 Feb)", "late winter turning to spring", "Maha Shivratri (around Feb-Mar)"],
    3: ["Holi (around March)", "board exams and results anxiety", "start of summer heat", "financial year-end rush", "Navratri/Ugadi/Gudi Padwa (around Mar-Apr)"],
    4: ["summer heat", "new academic year", "Baisakhi / Ram Navami / Eid (dates move; around April)", "wedding season in some regions"],
    5: ["peak summer heat", "summer holidays for children", "pre-monsoon", "exam results season"],
    6: ["monsoon arrives", "school reopening", "International Yoga Day (21 Jun)", "humidity and monsoon health"],
    7: ["monsoon", "Guru Purnima (around July)", "college admissions", "rain and slippery roads"],
    8: ["Independence Day (15 Aug)", "Raksha Bandhan (around August)", "Janmashtami (around Aug-Sep)", "monsoon", "Ganesh Chaturthi (around Aug-Sep)"],
    9: ["Ganesh Chaturthi (around Sep)", "Onam (around Aug-Sep)", "end of monsoon", "Teachers' Day (5 Sep)", "festival season begins"],
    10: ["Navratri and Dussehra (around October)", "Karwa Chauth (around Oct-Nov)", "Diwali preparations", "festive shopping and gifting", "pleasant weather, wedding season approaches"],
    11: ["Diwali and Bhai Dooj (around Oct-Nov)", "start of winter", "wedding season", "Children's Day (14 Nov)", "Chhath (around Nov)"],
    12: ["Christmas", "New Year plans", "winter", "wedding season", "year-end"],
}


def occasions(d: date | None = None) -> list[str]:
    d = d or date.today()
    return list(_OCCASIONS[d.month])


# ------------------------------------------------------------------ reply guidance
# Hints that a 4 or 5 star review still carries a concern, in English, Hinglish and Hindi (no \b around Devanagari: its vowel signs are not word characters).
CONCERN_CUES = re.compile(r"\b(but|however|although|though|except|only issue|could be better|wait\w*|late|slow|expensive|costly|crowd\w*|noisy|parking|problem|issue|dikkat|pareshani|"
                          r"lekin|magar|par|bas|thoda|thodi|bheed|mehenga|mehnga|intezaar|der|bura|kami)\b|लेकिन|मगर|बस|थोड़ा|थोड़ी|भीड़|परेशानी|दिक्कत|समस्या|इंतजार|इंतज़ार|देर|महंगा", re.I)


def sentiment(rating: int, text: str) -> str:
    if rating <= 2:
        return "negative"
    if rating == 3:
        return "mixed"
    if rating >= 4 and CONCERN_CUES.search(text or ""):
        return "positive_with_a_concern"
    return "positive"


# Stricter language rules for REPLIES (the text is public and signed by the business, so small grammar or register mistakes show).
LANGUAGE_PRECISION = {
    "en": ("Indian-English spelling (colour, apologise, organise, centre). Complete, grammatical sentences in one tense. No 'kindly', 'do the needful', 'revert back', no abbreviations or texting spellings. "
           "Say 'we' for the business."),
    "hinglish": ("HINGLISH RULES. (1) Address the reviewer only as aap / aapka / aapki / aapke / aapne, never tum, tu or tera. (2) The business speaks as 'hum' with plural verbs (note kar rahe hain, dekhenge), never 'main'. "
                 "(3) Make aapka / aapki / aapke agree with the noun that follows (aapka feedback, aapki baat, aapke bete). (4) Spell each word one way, always: hai, hain, nahi, bahut, accha, acche, shukriya, kharcha, dikkat. "
                 "(5) Keep everyday English words in English (appointment, booking, clinic, staff, parking, service, wait, feedback, treatment) and service names exactly as given. "
                 "(6) Match the reviewer's own mix of Hindi and English; do not make it more Hindi or more English than theirs. (7) Plain spoken words, not formal Hindi."),
    "hi": ("HINDI RULES. Simple spoken Devanagari. Always आप, never तुम or तू; the business says हम and the verbs agree with it (हम ... करेंगे). Correct spelling including nukta and anusvara "
           "(ज़्यादा, माफ़ी, नहीं, हैं, कृपया). Write numbers as digits, as the reviewer did. Everyday English words people really use (क्लिनिक, स्टाफ, पार्किंग, अपॉइंटमेंट) stay, in Devanagari. "
           "No English sentences mixed in."),
}

# Worked examples, one per language and kind of review. They teach register and care, on invented reviews that are NOT in the benchmark. The prompt tells the model never to reuse
# their wording or facts, and the generation check rejects a draft that copies one. Every example is itself required to pass quality.assess_reply (tests/test_ai_quality.py).
REPLY_EXAMPLES: dict[str, dict[str, tuple[int, str, str]]] = {
    "en": {
        "negative": (1, "The AC was not working and we waited 45 minutes for a simple trim. Nobody even offered us water.",
                     "A 45-minute wait in a room with no working AC, and nobody looking after you, is not the welcome we want for anyone. We are sorry. Please call us so the team can understand what happened and make it right."),
        "mixed": (3, "Food was fine for the price but the place was noisy and my order took very long.",
                  "We are glad the food felt fair for the price. A noisy room and a slow order should not have been part of your visit, and we have noted both."),
        "positive_with_a_concern": (4, "The trainer was very helpful and explained the machines well. Gets crowded in the evening though.",
                                    "Glad the trainer took the time to explain the machines. The evening crowd is a fair point and we have noted it."),
        "positive": (5, "The mechanic showed me the old part and went through the bill line by line. The garage was clean too.",
                     "Showing you the old part and going through the bill line by line is how it should be done, and we are glad the garage felt clean to you. Your kind words will reach the whole team."),
    },
    "hinglish": {
        "negative": (1, "Phone ka cover maanga to dusra pakda diya, aur exchange karne se bhi mana kar diya.",
                     "Aapne jo cover maanga woh nahi mila, aur exchange se bhi mana kiya gaya, yeh sahi nahi tha. Humein afsos hai. Aap dukaan par aakar ya call karke humse baat kijiye, hum ise theek karne ki koshish karenge."),
        "mixed": (3, "Facial achha tha lekin staff thoda busy tha aur wait karna pada.",
                  "Facial aapko pasand aaya, yeh sunkar accha laga. Wait wali baat hum note kar rahe hain, aur busy time mein aapko pehle se bataya jaye, yeh hum dekhenge."),
        "positive_with_a_concern": (4, "Trainers helpful hain par evening mein bahut crowded ho jata hai.",
                                    "Trainers ki madad aapko pasand aayi, yeh jaankar accha laga. Evening ki bheed wali baat sahi hai, hum ise note kar rahe hain."),
        "positive": (5, "Birthday dinner ke liye gaye the, staff ne cake ke liye table sajaya aur khana garam mila.",
                     "Birthday dinner mein table sajana aur khana garam milna, yeh sunkar bahut accha laga. Aapke din ko khaas banana hamare liye khushi ki baat thi."),
    },
    "hi": {
        "negative": (1, "दवाई के लिए लाइन में बहुत इंतजार करना पड़ा और काउंटर पर किसी ने सही से बात नहीं की।",
                     "दवाई के लिए लंबी लाइन में इंतजार और काउंटर पर सही से बात न होना, यह ठीक नहीं है और हमें इसका खेद है। कृपया हमसे संपर्क करके पूरी बात बताइए ताकि हम इसे सुधार सकें।"),
        "mixed": (3, "टीचर अच्छे हैं लेकिन क्लास का समय स्कूल के बाद थोड़ा देर से है।",
                  "टीचर आपको अच्छे लगे, यह जानकर खुशी हुई। क्लास का समय देर से होने की बात हमने नोट कर ली है।"),
        "positive_with_a_concern": (4, "ट्रेनर अच्छे हैं लेकिन शाम को बहुत भीड़ हो जाती है।",
                                    "ट्रेनर की मदद आपको पसंद आई, यह जानकर अच्छा लगा। शाम की भीड़ वाली बात सही है और हमने इसे नोट कर लिया है।"),
        "positive": (5, "यहाँ की सफाई बहुत अच्छी है और स्टाफ ने हर चीज़ आराम से समझाई।",
                     "सफाई और स्टाफ का आराम से हर चीज़ समझाना, यह सुनकर बहुत अच्छा लगा। आपके भरोसे के लिए धन्यवाद।"),
    },
}


def reply_example(lang: str, mood: str) -> tuple[int, str, str] | None:
    return REPLY_EXAMPLES.get(lang, {}).get(mood)


REPLY_GUIDE = {
    "negative": ("The reviewer is unhappy. Open by acknowledging what went wrong in their words, without defending or explaining it away. Apologise for the experience, not for facts you do not know. "
                 "Do not argue, blame or ask for details publicly. Close by inviting them to contact the business directly so it can be put right. No selling."),
    "mixed": ("The review is mixed. Thank them for the honest feedback, acknowledge the part that fell short specifically, and acknowledge the part they liked. Do not force positivity or push them to return."),
    "positive_with_a_concern": ("Mostly positive with one concern. Thank them for the specific praise, then acknowledge the concern honestly in one sentence and say it has been noted. Do not ignore the concern."),
    "positive": ("The review is positive. Thank them for the specific thing they mentioned, in your own words, and add one human touch (what it means to the team, or what they can expect next time) without promising anything. "
                 "Keep it short; do not turn it into an advertisement."),
}
