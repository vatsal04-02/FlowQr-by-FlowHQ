"""Benchmark cases for the AI evaluation: 7 kinds of business x (4 review replies, 2 posts, 1 description, 1 customer review draft), in English, Hindi and
Hinglish (the customer review assistant supports English and Hindi only, so its cases are those two). All businesses, names and reviews are INVENTED for testing (no real customer data), but written to look like what small Indian businesses really
receive: short, specific, sometimes mixed-language, sometimes rude.

Each case carries what a good output must be consistent with (`facts`) so factual accuracy can be checked mechanically. The `must_reference` words in
reply cases are concrete details from the review that a personal reply should pick up in its own words."""
from __future__ import annotations

from dataclasses import dataclass, field

# ------------------------------------------------------------------ businesses
BUSINESSES: dict[str, dict] = {
    "physio": dict(name="Gomti Physio & Rehab", category="Physiotherapy clinic", city="Lucknow", area="Gomti Nagar", language="en", health=True, voice="warm and professional, no emoji",
                   emoji=False, services=["back and neck pain assessment", "sports injury rehabilitation", "post-surgery physiotherapy", "posture correction for desk workers"],
                   description="A physiotherapy clinic in Gomti Nagar helping office workers, sportspeople and people recovering from surgery.",
                   hours="Monday to Saturday, 9 am to 7 pm", audience="office workers and people recovering from surgery nearby", offers=[],
                   faqs=[{"q": "Do I need a doctor's referral?", "a": "No referral is needed for a first assessment."}, {"q": "How long is a session?", "a": "A session is about 45 minutes."}],
                   praise=[("expertise and explanation", 9), ("staff behaviour", 6)], concerns=[("waiting time", 3)]),
    "dental": dict(name="Smile Craft Dental", category="Dental clinic", city="Pune", area="Kothrud", language="hinglish", health=True, voice="friendly, simple, no emoji", emoji=False,
                   services=["routine check-up and cleaning", "root canal treatment", "braces and aligners", "children's dentistry"],
                   description="Family dental clinic in Kothrud for check-ups, root canals, braces and children's dentistry.", hours="Monday to Saturday, 10 am to 8 pm",
                   audience="families and college students in Kothrud", offers=[{"name": "Free dental check-up camp", "price_inr": 0, "details": "first Sunday of the month, 10 am to 1 pm", "valid_until": "2027-03-31"}],
                   faqs=[{"q": "Is a root canal painful?", "a": "We use local anaesthesia, and the dentist explains each step before starting."}],
                   praise=[("expertise and explanation", 12), ("cleanliness", 7)], concerns=[("price and value", 2)]),
    "salon": dict(name="Glow Studio Salon", category="Beauty salon", city="Jaipur", area="Vaishali Nagar", language="en", health=False, voice="friendly and stylish, one emoji is fine", emoji=True,
                  services=["haircut and styling", "hair colour and smoothing", "bridal makeup", "facials and skin care"],
                  description="Unisex salon in Vaishali Nagar offering haircuts, colour, facials and bridal makeup.", hours="Every day, 10 am to 9 pm", audience="young professionals and brides-to-be", offers=[],
                  faqs=[{"q": "Do you take walk-ins?", "a": "Walk-ins are welcome, but appointments get priority."}],
                  praise=[("results and quality", 10), ("staff behaviour", 8)], concerns=[("waiting time", 4)]),
    "restaurant": dict(name="Tandoor Junction", category="Restaurant", city="Indore", area="Vijay Nagar", language="hinglish", health=False, voice="casual and hearty", emoji=True,
                       services=["North Indian thali", "tandoori starters", "family dining", "party orders"],
                       description="Family restaurant in Vijay Nagar serving North Indian thali, tandoori starters and party orders.", hours="Every day, 11 am to 11 pm", audience="families and office groups",
                       offers=[{"name": "Sunday family thali", "price_inr": 349, "details": "unlimited thali for one", "valid_until": "2027-06-30"}],
                       faqs=[{"q": "Do you take bulk orders?", "a": "Yes, party orders of 20 or more need a day's notice."}],
                       praise=[("results and quality", 15), ("ambience and comfort", 6)], concerns=[("waiting time", 5)]),
    "gym": dict(name="IronCore Fitness", category="Gym and fitness centre", city="Hyderabad", area="Madhapur", language="en", health=False, voice="motivating but honest, no hype", emoji=False,
                services=["strength training", "group cardio classes", "personal training", "beginner onboarding"], description="Gym in Madhapur with strength floor, group classes and personal trainers.",
                hours="Monday to Saturday, 5 am to 10 pm; Sunday 7 am to 1 pm", audience="IT professionals and first-time gym-goers", offers=[], faqs=[{"q": "Is there a trial?", "a": "A one-day trial pass is available at the front desk."}],
                praise=[("staff behaviour", 11), ("expertise and explanation", 7)], concerns=[("ambience and comfort", 4)]),
    "retail": dict(name="Sharma Mobile & Accessories", category="Mobile phone shop", city="Delhi", area="Laxmi Nagar", language="hinglish", health=False, voice="straightforward and helpful", emoji=False,
                   services=["new smartphones", "phone repair and screen replacement", "chargers and accessories", "exchange of old phones"],
                   description="Mobile shop in Laxmi Nagar selling smartphones and accessories, with in-house repair.", hours="Every day, 10:30 am to 9 pm", audience="students and families nearby", offers=[],
                   faqs=[{"q": "Do you give a bill and warranty?", "a": "Yes, every phone comes with a GST bill and the brand warranty."}],
                   praise=[("price and value", 9), ("expertise and explanation", 5)], concerns=[("booking and timings", 3)]),
    "coaching": dict(name="Vidya Path Classes", category="Coaching institute", city="Patna", area="Boring Road", language="hi", health=False, voice="encouraging and respectful, simple Hindi", emoji=False,
                     services=["class 9 to 12 maths and science", "JEE foundation batch", "weekly tests and doubt classes", "parent-teacher meetings"],
                     description="Coaching classes on Boring Road for class 9 to 12 maths and science and a JEE foundation batch.", hours="Monday to Saturday, 3 pm to 8 pm", audience="school students and their parents",
                     offers=[], faqs=[{"q": "Is a demo class available?", "a": "Yes, the first class is a free demo."}],
                     praise=[("expertise and explanation", 10), ("results and quality", 6)], concerns=[("booking and timings", 2)]),
}


@dataclass
class Case:
    id: str
    task: str  # reply | post | description | review_draft
    biz: str
    lang: str
    data: dict = field(default_factory=dict)

    @property
    def business(self) -> dict:
        return BUSINESSES[self.biz]


def _r(biz, n, rating, lang, text, ref, name="", tags=()):
    return Case(f"reply-{biz}-{n}", "reply", biz, lang, {"rating": rating, "text": text, "must_reference": ref, "reviewer": name, "tags": list(tags)})


REPLIES = [
    # physio (en, en, hinglish, hi)
    _r("physio", 1, 5, "en", "Had severe lower back pain from sitting all day. Dr Mehta explained exactly what was causing it and gave me exercises I can do at my desk. Much better in three weeks.", ["back", "exercises", "desk"], "Rohit"),
    _r("physio", 2, 2, "en", "Waited 40 minutes past my appointment time and nobody told me why. The session itself was rushed.", ["waited", "appointment", "rushed"], "Neha", ("negative",)),
    _r("physio", 3, 4, "hinglish", "Therapist bahut acche hain, sab kuch achhe se samjhaya. Bas parking ki problem hai.", ["therapist", "samjhaya", "parking"], "Amit", ("concern",)),
    _r("physio", 4, 5, "hi", "मेरे घुटने की सर्जरी के बाद यहाँ फिजियोथेरेपी करवाई। स्टाफ बहुत सहयोगी है और हर सेशन में ध्यान से देखते हैं।", ["घुटने", "स्टाफ"], "सुनीता"),
    # dental (hinglish x2, en, en)
    _r("dental", 1, 5, "hinglish", "Mere bete ka pehla dental visit tha, doctor ne bahut pyaar se baat ki aur wo bilkul nahi dara. Clinic bhi bahut saaf hai.", ["bete", "doctor", "saaf"], "Pooja"),
    _r("dental", 2, 1, "hinglish", "Root canal ke liye 3 baar bulaya aur har baar naya kharcha bataya. Pehle clear nahi bataya tha. Bahut disappointed.", ["root canal", "kharcha", "clear"], "Vikas", ("negative",)),
    _r("dental", 3, 3, "en", "Treatment was fine but the waiting area was crowded and the reception staff seemed overwhelmed.", ["waiting", "reception"], "Karan", ("mixed",)),
    _r("dental", 4, 5, "en", "Excellent cleaning and the dentist walked me through what he was doing. Very hygienic.", ["cleaning", "dentist", "hygienic"], "Shreya"),
    # salon
    _r("salon", 1, 5, "en", "Got my bridal makeup done here and it lasted the whole wedding day. Priya listened to exactly what I wanted and the trial made me so relaxed.", ["bridal", "trial", "wedding"], "Ananya"),
    _r("salon", 2, 2, "en", "Haircut was okay but they made me wait an hour even with a booked slot, and the colour was a shade off from what I asked.", ["wait", "colour", "shade"], "Meera", ("negative",)),
    _r("salon", 3, 4, "hinglish", "Facial bahut accha tha, skin glow kar rahi hai. Thoda mehenga laga bas.", ["facial", "mehenga"], "Ritu", ("concern",)),
    _r("salon", 4, 5, "en", "", [], "Sana", ("rating_only",)),
    # restaurant
    _r("restaurant", 1, 5, "hinglish", "Sunday ko family ke saath gaye the, thali ekdum zabardast thi aur dal makhani ka swad ghar jaisa tha. Staff ne bachon ka bhi dhyan rakha.", ["thali", "dal makhani", "bachon"], "Sandeep"),
    _r("restaurant", 2, 2, "en", "Ordered tandoori starters and they arrived cold after 45 minutes. When I asked the waiter just shrugged.", ["tandoori", "cold", "waiter"], "Isha", ("negative",)),
    _r("restaurant", 3, 4, "hinglish", "Food mast tha lekin parking mein bahut dikkat hui aur weekend pe bahut bheed hoti hai.", ["parking", "bheed"], "Gaurav", ("concern",)),
    _r("restaurant", 4, 3, "en", "Average food for the price. Nothing special but service was polite.", ["price", "service"], "Tara", ("mixed",)),
    # gym
    _r("gym", 1, 5, "en", "As a total beginner I was nervous, but the trainer Arjun built a simple plan and corrected my form without making me feel silly. Down 4 kg in two months.", ["beginner", "trainer", "plan"], "Divya"),
    _r("gym", 2, 1, "en", "Equipment is always out of order, the treadmills have been broken for weeks. Tried to raise it with the manager and was ignored.", ["equipment", "treadmills", "manager"], "Rahul", ("negative",)),
    _r("gym", 3, 4, "hinglish", "Trainers helpful hain par evening mein bahut crowded ho jata hai, machine ke liye wait karna padta hai.", ["trainers", "evening", "wait"], "Faizan", ("concern",)),
    _r("gym", 4, 5, "hi", "जिम का माहौल बहुत अच्छा है और ट्रेनर हमेशा मदद के लिए तैयार रहते हैं।", ["माहौल", "ट्रेनर"], "नेहा"),
    # retail
    _r("retail", 1, 5, "hinglish", "Phone ki screen toot gayi thi, same din mein replace kar diya aur price bhi sahi liya. Bill bhi diya.", ["screen", "same din", "bill"], "Mohit"),
    _r("retail", 2, 2, "hinglish", "Naya phone liya tha, 2 din mein charging problem aayi. Dukaan wale ne bola brand ke paas jao, koi madad nahi ki.", ["charging", "brand", "madad"], "Suresh", ("negative",)),
    _r("retail", 3, 4, "en", "Good range of accessories and honest advice on which phone suits my budget. Shop is small and gets crowded though.", ["accessories", "budget", "crowded"], "Kunal", ("concern",)),
    _r("retail", 4, 5, "en", "Exchanged my old phone and got a fair value. Quick process.", ["exchanged", "fair"], "Zoya"),
    # coaching (hi x2, hinglish, en)
    _r("coaching", 1, 5, "hi", "मेरी बेटी कक्षा 10 में पढ़ती है। यहाँ के शिक्षक गणित में हर संदेह दूर करते हैं और हर हफ्ते टेस्ट होता है। पिछले टेस्ट में उसके नंबर काफी बढ़े।", ["बेटी", "गणित", "टेस्ट"], "राजेश"),
    _r("coaching", 2, 2, "hi", "बैच में बहुत ज्यादा बच्चे हैं, पीछे बैठकर कुछ समझ नहीं आता। डाउट पूछने का समय भी नहीं मिलता।", ["बैच", "डाउट"], "अनीता", ("negative",)),
    _r("coaching", 3, 4, "hinglish", "Teachers achhe hain aur test series useful hai. Bas class timing thodi late hai school ke baad.", ["teachers", "test", "timing"], "Prakash", ("concern",)),
    _r("coaching", 4, 5, "en", "My son joined the JEE foundation batch. The weekly tests and honest feedback to parents have helped him stay on track.", ["jee", "weekly", "feedback"], "Meenal"),
]


def _p(biz, n, lang, ptype, recent):
    return Case(f"post-{biz}-{n}", "post", biz, lang, {"type": ptype, "recent": recent})


POSTS = [
    _p("physio", 1, "en", "educational", ["Back pain from long hours at a desk is common. Our physiotherapists can assess your posture and show you simple exercises. Call the clinic to book."]),
    _p("physio", 2, "hinglish", "faq", []),
    _p("dental", 1, "hinglish", "service", ["Regular dental check-up zaroori hai. Humare clinic mein aap check-up ke liye aa sakte hain."]),
    _p("dental", 2, "en", "offer", []),
    _p("salon", 1, "en", "seasonal", []),
    _p("salon", 2, "en", "service", ["Our bridal makeup service is available. Book your trial today!"]),
    _p("restaurant", 1, "hinglish", "offer", []),
    _p("restaurant", 2, "en", "update", ["Visit us for the best North Indian food in Vijay Nagar!"]),
    _p("gym", 1, "en", "educational", []),
    _p("gym", 2, "en", "faq", ["New year, new you! Join IronCore Fitness today."]),
    _p("retail", 1, "hinglish", "service", []),
    _p("retail", 2, "hinglish", "faq", []),
    _p("coaching", 1, "hi", "educational", []),
    _p("coaching", 2, "en", "service", ["Admissions open for the new batch at Vidya Path Classes."]),
]

DESCRIPTIONS = [Case(f"desc-{b}", "description", b, BUSINESSES[b]["language"], {"current": c}) for b, c in [
    ("physio", "Physiotherapy clinic in Lucknow. Best treatment. Call now."), ("dental", ""), ("salon", "Best salon in Jaipur for hair, skin and makeup. Affordable prices. Visit us today."),
    ("restaurant", ""), ("gym", "Gym in Hyderabad."), ("retail", ""), ("coaching", "Coaching classes for all subjects. Best results.")]]

REVIEW_DRAFTS = [
    Case("review-physio-1", "review_draft", "physio", "en", {"note": "back pain better, therapist explained everything", "topics": ["Expertise", "Explanation"], "rating": 5}),
    Case("review-dental-1", "review_draft", "dental", "en", {"note": "my son first dental visit, doctor was very gentle with him", "topics": ["Doctor behaviour", "Cleanliness"], "rating": 5}),
    Case("review-salon-1", "review_draft", "salon", "en", {"note": "bridal trial was relaxed, makeup lasted all day", "topics": ["Bridal makeup"], "rating": 5}),
    Case("review-restaurant-1", "review_draft", "restaurant", "en", {"note": "thali was good, waited a bit long on sunday", "topics": ["Food", "Waiting time"], "rating": 4}),
    Case("review-gym-1", "review_draft", "gym", "en", {"note": "trainer helped beginner like me, machines sometimes busy", "topics": ["Trainers", "Crowd"], "rating": 4}),
    Case("review-retail-1", "review_draft", "retail", "hi", {"note": "सही दाम और अच्छी सलाह मिली", "topics": ["Price", "Advice"], "rating": 5}),
    Case("review-coaching-1", "review_draft", "coaching", "hi", {"note": "शिक्षक अच्छे हैं और हर हफ्ते टेस्ट होता है", "topics": ["Teaching", "Tests"], "rating": 5}),
]

ALL_CASES: list[Case] = REPLIES + POSTS + DESCRIPTIONS + REVIEW_DRAFTS


def by_task(task: str | None = None, biz: str | None = None) -> list[Case]:
    return [c for c in ALL_CASES if (not task or c.task == task) and (not biz or c.biz == biz)]


def kb_for(biz: str) -> dict:
    """The Business Knowledge Base dict the production prompts expect, built from the benchmark business."""
    b = BUSINESSES[biz]
    from app.services.agent.safety import HEALTH_PROHIBITED_DEFAULTS
    return {"business": b["name"], "category": b["category"], "language": b["language"], "description": b["description"], "services": list(b["services"]), "offers": list(b["offers"]),
            "hours": b["hours"], "faqs": list(b["faqs"]), "brand_voice": b["voice"], "approved_claims": [], "prohibited_claims": list(HEALTH_PROHIBITED_DEFAULTS) if b["health"] else [],
            "safety_profile": "health" if b["health"] else "general", "instructions": "", "audience": b["audience"]}


def intel_for(biz: str, recent_posts: list[str] | None = None) -> dict:
    """A synthetic observation block for the benchmark business (what intelligence.build would produce from its reviews and profile)."""
    from app.services.ai import craft
    b = BUSINESSES[biz]
    posts = list(recent_posts or [])
    return {"business": b["name"], "category": b["category"], "city": b["city"], "area": b["area"], "language": b["language"], "audience": b["audience"], "safety_profile": "health" if b["health"] else "general",
            "profile": {"description": "", "primary_category": b["category"], "additional_categories": [], "services_on_google": [], "has_hours": True, "known": True},
            "reviews": {"n": 40, "avg": 4.5, "mix": {1: 1, 2: 2, 3: 3, 4: 12, 5: 22}, "praise": b["praise"], "concerns": b["concerns"], "unanswered": 0},
            "recent_posts": posts, "recent_post_types": [craft.classify_post(p) for p in posts], "recent_replies": [], "photos": None, "performance": None,
            "search_terms": [s.split(" and ")[0] for s in b["services"][:3]], "occasions": craft.occasions(__import__("datetime").date(2026, 11, 15)), "today": "2026-11-15", "missing": []}
