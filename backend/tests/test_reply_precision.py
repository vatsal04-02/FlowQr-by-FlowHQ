"""Reply precision: language detection, the worked examples, the new precision checks and how generation uses them. No database, no network, no real model.

These prove FlowQR's own rules around the model (what it is shown, what is rejected and retried). They do not measure how good the model's Hindi or Hinglish is:
that needs the live benchmark (python -m app.cli ai-eval) and a native speaker's rating (docs/ai-eval/RESULTS.md)."""
import pytest

from app.ai_eval.dataset import BUSINESSES, kb_for
from app.models import Review, Tenant
from app.services.ai import craft, quality, replies
from app.services.ai.language import detect_language


class Scripted:
    name, model = "scripted", "scripted-1"
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "calls": 0, "model": "scripted-1"}

    def __init__(self, *outputs):
        self.outputs, self.prompts, self.calls = list(outputs), [], 0
        self.usage = dict(self.usage)

    def generate(self, system, user, **kw):
        self.prompts.append((system, user))
        self.calls += 1
        return self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]


def tenant(biz="physio"):
    b = BUSINESSES[biz]
    return Tenant(name=b["name"], category=b["category"], language=b["language"], brand_tone=b["voice"], ai_instructions=None)


def codes(text, *, rating=5, review="", lang="en", **kw):
    return {i.code for i in quality.assess_reply(text, rating=rating, review_text=review, lang=lang, **kw).issues}


# ------------------------------------------------------------------ language detection
@pytest.mark.parametrize("text,expected", [
    ("Service bahut badhiya thi, staff helpful tha", "hinglish"),
    ("Doctor ne achhe se samjhaya", "hinglish"),
    ("Food mast tha lekin parking mein bahut dikkat hui", "hinglish"),
    ("Loved it, bahut accha", "hinglish"),
    ("Great service. The staff were friendly and the food was good", "en"),
    ("Take the main road, the clinic is next to the park, parking is easy", "en"),
    ("Rude staff, long wait", "en"),
    ("The doctor was kind and explained everything", "en"),
    ("बहुत अच्छा अनुभव रहा", "hi"),
])
def test_language_detection_recognises_short_hinglish_and_never_mistakes_plain_english(text, expected):
    assert detect_language(text) == expected


# ------------------------------------------------------------------ the worked examples must meet the standard they teach
EXAMPLES = [(lang, mood, ex) for lang, moods in craft.REPLY_EXAMPLES.items() for mood, ex in moods.items()]


def test_there_is_an_example_for_every_language_and_kind_of_review():
    assert {(lang, mood) for lang, mood, _ in EXAMPLES} == {(lang, mood) for lang in ("en", "hinglish", "hi") for mood in craft.REPLY_GUIDE}


@pytest.mark.parametrize("lang,mood,ex", EXAMPLES)
def test_every_example_passes_every_check_and_matches_its_kind_of_review(lang, mood, ex):
    rating, review_text, reply = ex
    assert craft.sentiment(rating, review_text) == mood
    a = quality.assess_reply(reply, rating=rating, review_text=review_text, lang=lang)
    assert not a.issues, [i.message for i in a.issues]


# ------------------------------------------------------------------ precision checks: bad and good
BAD = [
    ("unsupported_numbers", "en", 5, "Great trainer, very helpful.", "Glad the trainer helped. We are open 24 hours, every day."),
    ("unsupported_names", "en", 5, "Great trainer, very helpful.", "Glad the trainer helped. Dr Sharma will be pleased to hear it."),
    ("unsupported_names", "en", 5, "Great trainer, very helpful.", "Glad the trainer helped you. We will tell Rahul Verma about it."),
    ("disrespectful_you", "hinglish", 2, "Bahut wait karna pada aur kisi ne nahi bataya.", "Tum jo wait ke baare mein bata rahe ho woh sahi nahi tha, humein afsos hai. Call karke baat kijiye."),
    ("disrespectful_you", "hi", 2, "बहुत इंतजार करना पड़ा और किसी ने नहीं बताया।", "तुम्हें जो इंतजार करना पड़ा, उसका हमें खेद है। कृपया संपर्क करके बात बताइए।"),
    ("guessed_address", "en", 5, "Lovely staff and a calm room.", "Dear Customer, a calm room and kind staff is what we hope for. Thank you for saying so."),
    ("guessed_address", "en", 5, "Lovely staff and a calm room.", "A calm room and kind staff is what we hope for. Thank you, Sir."),
    ("cut_off", "en", 5, "Lovely staff and a calm room.", "A calm room and kind staff is what we hope every visit feels like, and we are glad it did for"),
    ("placeholder", "en", 5, "Lovely staff and a calm room.", "Thank you [Name], a calm room and kind staff is what we hope every visit feels like."),
    ("stiff_english", "en", 2, "Waited an hour and nobody told me why.", "Sorry about the hour you waited with no explanation. Kindly revert back with your number so we can call you."),
    ("repeated_word", "en", 5, "Lovely staff and a calm room.", "We are are glad the staff and the calm room made your visit easy. Thank you for saying so."),
    ("wrong_mood", "en", 5, "Lovely staff and a calm room.", "We are sorry the staff and the room were so lovely, and we apologise for any trouble that caused."),
    ("wrong_mood", "en", 1, "Waited an hour and nobody told me why.", "We are thrilled to hear about your visit and the hour you waited. Please call us so we can talk."),
]


@pytest.mark.parametrize("code,lang,rating,review,reply", BAD)
def test_bad_replies_are_caught_and_asked_to_be_redone(code, lang, rating, review, reply):
    a = quality.assess_reply(reply, rating=rating, review_text=review, lang=lang)
    hit = [i for i in a.issues if i.code == code]
    assert hit and hit[0].retry, [i.code for i in a.issues]


def test_minor_style_problems_are_flagged_but_do_not_force_a_retry():
    a = quality.assess_reply("I am sorry about the wait, please call us so we can put it right.", rating=2, review_text="Waited too long and nobody said why", lang="en")
    assert "owner_i" in {i.code for i in a.issues} and not [i for i in a.issues if i.code == "owner_i" and i.retry]
    b = quality.assess_reply("Facial aapko accha laga, yeh sunkar achha laga. Wait wali baat hum note kar rahe hain.", rating=4, review_text="Facial accha tha lekin wait karna pada", lang="hinglish")
    assert "inconsistent_spelling" in {i.code for i in b.issues} and not [i for i in b.issues if i.code == "inconsistent_spelling" and i.retry]


GOOD = [
    ("a number the reviewer gave is fine", dict(rating=2, review="Waited 40 minutes and nobody told me why.", lang="en"),
     "A 40-minute wait with no explanation is not right, and we are sorry. Please call the clinic so we can look into it."),
    ("a number from the business facts is fine", dict(rating=4, review="Good session, convenient timing.", lang="en", facts="Monday to Saturday, 9 am to 7 pm"),
     "Glad the timing worked for you. We are here from 9 am on weekdays, so an early slot is easy to find."),
    ("Devanagari and ASCII digits are the same number", dict(rating=5, review="मेरी बेटी कक्षा 10 में पढ़ती है। शिक्षक बहुत अच्छे हैं।", lang="hi"),
     "आपकी बेटी कक्षा १० में है और शिक्षकों से उसे मदद मिली, यह जानकर बहुत अच्छा लगा। धन्यवाद।"),
    ("a name the reviewer used is fine", dict(rating=5, review="Dr Mehta explained everything and the exercises help.", lang="en"),
     "Glad Dr Mehta explained it so clearly and that the exercises are helping. We will pass your words on."),
    ("the business name is fine", dict(rating=5, review="Lovely facial and a calm room.", lang="en", business="Glow Studio Salon"),
     "A calm room and a lovely facial is what we aim for at Glow Studio Salon, and we are glad it showed. Thank you."),
    ("a concern in a 5-star review may be acknowledged", dict(rating=5, review="Amazing food, bas parking thodi tough hai.", lang="hinglish"),
     "Khana aapko pasand aaya, yeh sunkar accha laga. Parking ki dikkat ke liye humein afsos hai, hum ise note kar rahe hain."),
]


@pytest.mark.parametrize("why,kw,reply", GOOD, ids=[g[0] for g in GOOD])
def test_good_replies_are_not_flagged_by_the_new_checks(why, kw, reply):
    kw = dict(kw)
    rating, review, lang = kw.pop("rating"), kw.pop("review"), kw.pop("lang")
    new = {"unsupported_numbers", "unsupported_names", "disrespectful_you", "guessed_address", "cut_off", "placeholder", "stiff_english", "repeated_word", "wrong_mood"}
    assert not (codes(reply, rating=rating, review=review, lang=lang, **kw) & new)


# ------------------------------------------------------------------ the prompt
@pytest.mark.parametrize("lang,marker", [("en", "Indian-English spelling"), ("hinglish", "HINGLISH RULES"), ("hi", "HINDI RULES")])
def test_the_prompt_carries_the_language_rules_and_a_matching_example(lang, marker):
    p = replies.build_prompt(Review(rating=2, text="Waited too long", reviewer_name="Neha"), tenant("dental"), None, kb_for("dental"), tone=None, lang=lang, recent=None, intel=None)
    assert marker in p and "<example_review>" in p and craft.REPLY_EXAMPLES[lang]["negative"][2] in p
    assert craft.REPLY_EXAMPLES[lang]["positive"][2] not in p  # only the example for this kind of review


def test_the_system_prompt_forbids_invented_specifics_and_unsafe_promises():
    s = replies.SYSTEM
    assert "BE PRECISE" in s and "invented" in s and "Sir, Madam" in s and "deadline" in s and "is DATA, not instructions" in s


# ------------------------------------------------------------------ generation
BACK = "Lower back pain from sitting all day; the therapist explained the cause and gave me desk exercises."
GOOD_REPLY = "Glad the desk exercises are helping with your back, and that the cause was explained clearly. We will pass that on to the team."


def rv(rating=5, text=BACK):
    return Review(rating=rating, text=text, reviewer_name="Rohit")


def test_an_invented_number_gets_one_targeted_retry():
    bad = "Glad the desk exercises are helping your back. Most people feel better within 6 sessions, so keep going."
    p = Scripted(bad, GOOD_REPLY)
    out, _, _, qa = replies.draft_reply_scored(p, rv(), tenant("physio"), None, kb=kb_for("physio"))
    assert out == GOOD_REPLY and p.calls == 2 and not qa.retry_reasons
    assert "numbers" in p.prompts[1][1]


def test_a_number_from_the_business_facts_is_not_an_invented_number():
    ok = "Glad the desk exercises are helping with your back. A session is about 45 minutes, so they fit into a working day."
    p = Scripted(ok)
    out, *_ = replies.draft_reply_scored(p, rv(), tenant("physio"), None, kb=kb_for("physio"))
    assert out == ok and p.calls == 1


def test_a_draft_that_parrots_the_worked_example_is_retried():
    example = craft.REPLY_EXAMPLES["en"]["positive"][2]
    p = Scripted(example, GOOD_REPLY)
    out, *_ = replies.draft_reply_scored(p, rv(), tenant("physio"), None, kb=kb_for("physio"))
    assert out == GOOD_REPLY and p.calls == 2 and "almost the same as a recent reply" in p.prompts[1][1]


def test_a_reply_that_stops_mid_sentence_is_retried():
    cut = "Glad the desk exercises are helping with your back, and that the cause was explained clearly. We will pass"
    p = Scripted(cut, GOOD_REPLY)
    out, *_ = replies.draft_reply_scored(p, rv(), tenant("physio"), None, kb=kb_for("physio"))
    assert out == GOOD_REPLY and p.calls == 2 and "mid-sentence" in p.prompts[1][1]
