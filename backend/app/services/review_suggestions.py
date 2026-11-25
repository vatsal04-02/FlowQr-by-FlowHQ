"""Business context + experience-topic suggestions for Review Growth.

Everything here is DETERMINISTIC: the topic chips a customer sees come from the business's OWN list of services/products when it has one
(plus Staff and Value for money), otherwise from this catalog (matched to the business's category), never from a model call on page load. AI is only used later, when the customer asks for a draft.

Two ideas keep this honest:
  * A chip is a TOPIC ("Staff", "Cleanliness"), not a claim. Picking it tells us the customer wants to comment on that topic; the
    customer's own sentiment (Good / Okay / Not good) or words say what they think of it.
  * Business context (category, services, description) says what the business OFFERS. It is never evidence of what a particular
    customer received, so the generator is told so, and drafts that mention an offered service the customer didn't mention are rejected.
"""
import hashlib
import re
from dataclasses import dataclass

from app.services.ai.review_generate import clean_field

LANGUAGES = ("en", "hi")
MAX_SERVICES = 12
MAX_DESCRIPTION = 300
MAX_SERVICE_CHIPS = 6  # the first six services become chips; with Staff and Value for money that is eight, as many as a phone shows comfortably


@dataclass(frozen=True)
class Topic:
    id: str
    en: str
    hi: str
    alts: tuple[str, ...] = ()  # natural English words for the topic, to vary phrasing without adding claims


def _t(id: str, en: str, hi: str, *alts: str) -> Topic:
    return Topic(id, en, hi, alts)


STAFF = _t("staff", "Staff", "स्टाफ़", "the staff", "the team")
CLEAN = _t("cleanliness", "Cleanliness", "सफ़ाई", "the cleanliness")
WAIT = _t("waiting", "Waiting time", "इंतज़ार का समय", "the wait")
PRICE = _t("pricing", "Value for money", "पैसे का मूल्य", "the pricing", "the price")
COMM = _t("communication", "Communication", "बातचीत और जानकारी", "how things were communicated")
APPT = _t("appointment", "Appointments", "अपॉइंटमेंट", "booking and timing")
EXPL = _t("explanations", "Explanations", "समझाने का तरीका", "how things were explained")
HYG = _t("hygiene", "Hygiene", "स्वच्छता", "hygiene")

# key -> (label, keywords matched against the owner's free-text category, topics)
CATALOG: dict[str, dict] = {
    "physio": {"label": "Physiotherapy", "keywords": ("physio", "rehab", "chiropract"), "offered": ("physiotherapy", "physiotherapist", "rehabilitation"), "topics": (
        STAFF, EXPL, _t("exercises", "Exercise guidance", "एक्सरसाइज़ का मार्गदर्शन", "the exercise guidance"),
        _t("treatment", "Treatment", "इलाज", "the treatment"), APPT, _t("clinic_cleanliness", "Clinic cleanliness", "क्लिनिक की सफ़ाई", "cleanliness"), PRICE)},
    "dental": {"label": "Dental clinic", "keywords": ("dental", "dentist", "orthodont"), "offered": ("dental", "dentist", "orthodontic", "braces", "implants"), "topics": (
        STAFF, EXPL, _t("treatment", "Treatment", "इलाज", "the treatment"), _t("comfort", "Comfort during the visit", "विज़िट के दौरान सुविधा", "comfort"),
        APPT, _t("clinic_cleanliness", "Clinic cleanliness", "क्लिनिक की सफ़ाई", "cleanliness"), PRICE)},
    "healthcare": {"label": "Clinic / healthcare", "keywords": ("clinic", "hospital", "doctor", "medical", "healthcare", "diagnostic", "pathology", "health care"), "topics": (
        STAFF, _t("doctor", "Doctor", "डॉक्टर", "the doctor"), EXPL, _t("treatment", "Treatment", "इलाज", "the treatment"), APPT,
        _t("clinic_cleanliness", "Clinic cleanliness", "क्लिनिक की सफ़ाई", "cleanliness"), PRICE)},
    "restaurant": {"label": "Restaurant / cafe", "keywords": ("restaurant", "cafe", "café", "bakery", "dhaba", "eatery", "food", "caterer", "kitchen", "bar "), "topics": (
        _t("food", "Food quality", "खाने की गुणवत्ता", "the food"), _t("service", "Staff service", "स्टाफ़ की सेवा", "the service"),
        _t("ambience", "Ambience", "माहौल", "the atmosphere"), HYG, _t("menu", "Menu variety", "मेन्यू में विविधता", "the menu"), WAIT, PRICE)},
    "hotel": {"label": "Hotel / stay", "keywords": ("hotel", "resort", "hostel", "homestay", "lodge", "guest house", "guesthouse"), "topics": (
        _t("room", "Room comfort", "कमरे की सुविधा", "the room"), _t("hospitality", "Staff hospitality", "स्टाफ़ का आतिथ्य", "the hospitality"),
        _t("checkin", "Check-in experience", "चेक-इन का अनुभव", "check-in"), CLEAN, _t("facilities", "Facilities", "सुविधाएँ", "the facilities"),
        _t("food", "Food", "खाना", "the food"), PRICE)},
    "salon": {"label": "Salon / spa", "keywords": ("salon", "spa", "parlour", "parlor", "barber", "beauty", "makeup"), "offered": ("haircut", "facial", "manicure", "pedicure", "massage"), "topics": (
        _t("service_result", "Service result", "सेवा का नतीजा", "how it turned out"), STAFF, HYG, _t("ambience", "Ambience", "माहौल", "the atmosphere"), APPT, PRICE)},
    "auto": {"label": "Automobile service", "keywords": ("automobile", "auto ", "car service", "garage", "workshop", "mechanic", "car wash", "vehicle", "bike service"), "topics": (
        _t("service_quality", "Service quality", "सेवा की गुणवत्ता", "the work done"), STAFF, COMM, _t("turnaround", "Time taken", "लगा हुआ समय", "how long it took"),
        _t("billing", "Pricing and billing", "कीमत और बिलिंग", "the pricing", "the billing"), _t("work_cleanliness", "Cleanliness of the work", "काम की सफ़ाई", "cleanliness"))},
    "retail": {"label": "Retail store", "keywords": ("retail", "store", "shop", "showroom", "supermarket", "boutique", "mart"), "topics": (
        _t("products", "Product range", "प्रोडक्ट की रेंज", "the range"), STAFF, PRICE, _t("checkout", "Billing and checkout", "बिलिंग और चेकआउट", "checkout"),
        _t("store", "Store experience", "स्टोर का अनुभव", "the store"), CLEAN)},
    "gym": {"label": "Gym / fitness", "keywords": ("gym", "fitness", "yoga", "crossfit", "pilates", "health club"), "topics": (
        _t("trainers", "Trainers", "ट्रेनर", "the trainers"), _t("equipment", "Equipment", "उपकरण", "the equipment"), CLEAN, _t("facilities", "Facilities", "सुविधाएँ", "the facilities"),
        _t("atmosphere", "Atmosphere", "माहौल", "the atmosphere"), _t("membership", "Membership value", "सदस्यता का मूल्य", "the membership"))},
    "coaching": {"label": "Coaching / education", "keywords": ("coaching", "institute", "tuition", "academy", "school", "classes", "education", "training", "tutor"), "topics": (
        _t("teaching", "Teaching", "पढ़ाई", "the teaching"), _t("doubts", "Doubt clearing", "संदेह दूर करना", "how doubts were handled"), _t("material", "Study material", "स्टडी मटेरियल", "the material"),
        _t("environment", "Classroom environment", "क्लासरूम का माहौल", "the environment"), COMM, _t("fees", "Fees", "फ़ीस", "the fees"))},
    "generic": {"label": "Other business", "keywords": (), "topics": (STAFF, _t("service", "Service", "सेवा", "the service"), CLEAN, WAIT, PRICE, COMM, _t("atmosphere", "Atmosphere", "माहौल", "the atmosphere"))},
}
DEFAULT_CATEGORY = "generic"


# ----------------------------------------------------------------------------------- what a topic MEANS (for richer, still honest drafts)
@dataclass(frozen=True)
class Meaning:
    """What a topic chip is about, so the writer can put it into fuller natural language, plus the plain describing words that merely restate
    "good <topic>" / "not good <topic>" (they add no event, no result and no reason). Facts about the visit still come only from the customer."""
    about: str
    words: tuple[str, ...] = ()
    ask_en: str = ""  # one optional follow-up for a customer who picked this single topic and said nothing else
    ask_hi: str = ""


def _m(about: str, words: tuple[str, ...], ask_en: str, ask_hi: str) -> Meaning:
    return Meaning(about, words, ask_en, ask_hi)


_PEOPLE = ("friendly", "polite", "courteous", "professional", "attentive")
MEANING: dict[str, Meaning] = {
    "staff": _m("how the staff dealt with the customer", _PEOPLE, "What did you appreciate most about the staff?", "स्टाफ़ की कौन-सी बात आपको सबसे अच्छी लगी?"),
    "doctor": _m("how the doctor dealt with the customer", ("attentive", "patient", "professional", "polite"), "What did you appreciate most about the doctor?", "डॉक्टर की कौन-सी बात आपको सबसे अच्छी लगी?"),
    "explanations": _m("how well things were explained to the customer", ("clear", "clearly", "simple", "easy to understand", "easy to follow"),
                       "Was there something that was explained especially well?", "क्या कोई बात खास तौर पर अच्छे से समझाई गई?"),
    "communication": _m("how well the business communicated with the customer", ("clear", "clearly", "polite"),
                        "What did you like about the communication?", "बातचीत में आपको क्या अच्छा लगा?"),
    "exercises": _m("the guidance the customer was given on the exercises", ("clear", "clearly", "simple", "easy to follow"),
                    "Was there anything about the exercise guidance you liked?", "एक्सरसाइज़ के मार्गदर्शन में आपको क्या अच्छा लगा?"),
    "treatment": _m("the treatment itself", ("professional", "careful", "thorough"), "What did you like about the treatment?", "इलाज में आपको क्या अच्छा लगा?"),
    "appointment": _m("the booking and appointment process", ("smooth", "easy", "convenient", "straightforward"), "What did you like about the appointment experience?", "अपॉइंटमेंट के अनुभव में आपको क्या अच्छा लगा?"),
    "cleanliness": _m("how clean the place was", ("clean", "tidy", "neat", "well-maintained"), "What stood out about the cleanliness?", "सफ़ाई में आपको क्या खास लगा?"),
    "clinic_cleanliness": _m("how clean the clinic was", ("clean", "tidy", "neat", "well-maintained"), "What stood out about the cleanliness?", "सफ़ाई में आपको क्या खास लगा?"),
    "work_cleanliness": _m("how clean the work was", ("clean", "tidy", "neat"), "What stood out about the cleanliness of the work?", "काम की सफ़ाई में आपको क्या खास लगा?"),
    "hygiene": _m("how hygienic the place was", ("clean", "hygienic", "neat"), "What stood out about the hygiene?", "स्वच्छता में आपको क्या खास लगा?"),
    "pricing": _m("whether the price felt fair for what was offered", ("reasonable", "fair"), "What made it feel worth the price?", "आपको यह कीमत के हिसाब से कैसा लगा?"),
    "fees": _m("whether the fees felt fair", ("reasonable", "fair"), "What did you think about the fees?", "फ़ीस के बारे में आपको क्या लगा?"),
    "membership": _m("whether the membership felt fair for what it offers", ("reasonable", "fair"), "What did you think about the membership?", "सदस्यता के बारे में आपको क्या लगा?"),
    "billing": _m("how clear and fair the pricing and bill were", ("clear", "transparent", "fair", "reasonable"), "What did you like about the billing?", "बिलिंग में आपको क्या अच्छा लगा?"),
    "checkout": _m("how the billing and checkout went", ("smooth", "easy", "quick", "straightforward"), "What did you like about the checkout?", "चेकआउट में आपको क्या अच्छा लगा?"),
    "waiting": _m("how long the customer had to wait", ("reasonable", "short"), "How did the waiting time feel to you?", "इंतज़ार का समय आपको कैसा लगा?"),
    "turnaround": _m("the time the work took", ("reasonable", "quick"), "How did the time it took feel to you?", "काम में लगा समय आपको कैसा लगा?"),
    "comfort": _m("how comfortable the visit was", ("comfortable", "relaxed"), "What made the visit comfortable?", "विज़िट में क्या आरामदायक लगा?"),
    "food": _m("the food", ("tasty", "flavourful"), "What did you enjoy most about the food?", "खाने में आपको सबसे ज़्यादा क्या पसंद आया?"),
    "service": _m("the service the customer received from the staff", ("polite", "courteous", "attentive", "friendly", "professional"),
                  "What did you like about the service?", "सेवा में आपको क्या अच्छा लगा?"),
    "ambience": _m("the atmosphere of the place", ("pleasant", "comfortable", "relaxing", "calm"), "What did you like about the ambience?", "माहौल में आपको क्या अच्छा लगा?"),
    "atmosphere": _m("the atmosphere of the place", ("pleasant", "comfortable", "relaxing", "calm"), "What did you like about the atmosphere?", "माहौल में आपको क्या अच्छा लगा?"),
    "environment": _m("the classroom atmosphere", ("pleasant", "comfortable", "calm"), "What did you like about the environment?", "माहौल में आपको क्या अच्छा लगा?"),
    "menu": _m("the menu and the choice it offered", (), "What did you like about the menu?", "मेन्यू में आपको क्या अच्छा लगा?"),
    "room": _m("how comfortable the room was", ("comfortable",), "What did you like about the room?", "कमरे में आपको क्या अच्छा लगा?"),
    "hospitality": _m("how the staff looked after the guest", ("warm", "friendly", "courteous", "welcoming"), "What did you appreciate about the hospitality?", "आतिथ्य में आपको क्या अच्छा लगा?"),
    "checkin": _m("how the check-in went", ("smooth", "easy", "quick", "straightforward"), "What did you like about the check-in?", "चेक-इन में आपको क्या अच्छा लगा?"),
    "facilities": _m("the facilities available", ("well-maintained", "comfortable", "clean"), "Which facilities did you like?", "कौन-सी सुविधाएँ आपको अच्छी लगीं?"),
    "service_result": _m("how the service turned out for the customer", (), "What did you like about how it turned out?", "नतीजे में आपको क्या अच्छा लगा?"),
    "service_quality": _m("the quality of the work done", ("professional", "careful", "thorough"), "What did you like about the work?", "काम में आपको क्या अच्छा लगा?"),
    "products": _m("the range of products available", (), "What did you like about the range?", "रेंज में आपको क्या अच्छा लगा?"),
    "store": _m("the store experience", ("pleasant", "comfortable", "clean", "organised"), "What did you like about the store?", "स्टोर में आपको क्या अच्छा लगा?"),
    "trainers": _m("how the trainers dealt with the customer", ("knowledgeable", "supportive", "professional", "attentive"), "What did you appreciate about the trainers?", "ट्रेनर्स की कौन-सी बात आपको अच्छी लगी?"),
    "equipment": _m("the equipment available", ("well-maintained", "clean", "modern"), "What did you think of the equipment?", "उपकरणों में आपको क्या अच्छा लगा?"),
    "teaching": _m("how things were taught", ("clear", "clearly", "knowledgeable", "patient"), "What did you like about the teaching?", "पढ़ाई में आपको क्या अच्छा लगा?"),
    "doubts": _m("how the customer's doubts were handled", ("patient", "clear", "clearly", "supportive"), "What did you like about how doubts were handled?", "संदेह दूर करने के तरीके में आपको क्या अच्छा लगा?"),
    "material": _m("the study material", ("clear", "detailed", "well-organised"), "What did you like about the study material?", "स्टडी मटेरियल में आपको क्या अच्छा लगा?"),
}
# How a customer of each kind of business naturally talks. Wording only: it says nothing about what happened on a visit.
VOICE = {
    "physio": "Plain patient language (the clinic, the staff, the exercises, the appointments). No clinical jargon.",
    "dental": "Plain patient language (the clinic, the staff, the treatment). No clinical jargon.",
    "healthcare": "Plain patient language (the clinic, the doctor, the staff). No clinical jargon.",
    "restaurant": "Casual diner language (the food, the place, the service). Relaxed and short.",
    "hotel": "Guest language (the stay, the room, the staff, check-in).",
    "salon": "Client language (the salon, the service, the staff).",
    "auto": "Vehicle-owner language (the service centre, the work on the vehicle, the staff). No mechanical jargon.",
    "retail": "Shopper language (the store, the range, the staff, the billing).",
    "gym": "Member language (the gym, the trainers, the equipment).",
    "coaching": "Student or parent language (the classes, the teaching, the study material).",
    "generic": "Everyday customer language.",
}


SERVICE_PREFIX = "svc_"


def service_topic(name: str) -> Topic:
    """A chip made from one of the business's own services or products. The id comes from the name, so renaming or reordering the list never changes another chip's id (stored picks and statistics stay valid).
    Customers see the owner's own words; there is no Hindi translation, so Hindi shows the same text."""
    return Topic(SERVICE_PREFIX + hashlib.sha1(name.strip().lower().encode("utf-8")).hexdigest()[:10], name, name, (f"the {name.lower()}",))


def all_topics(rc: dict | None, category_key: str) -> tuple[Topic, ...]:
    """EVERY chip this business has before the owner switches any off: its own services (first MAX_SERVICE_CHIPS) + Staff + Value for money, or the category's list when it has no services
    (or the owner turned `chips_from_services` off)."""
    rc = rc or {}
    services = [s for s in (rc.get("services") or []) if isinstance(s, str) and s.strip()]
    if services and rc.get("chips_from_services", True):
        own = tuple(dict.fromkeys(service_topic(s) for s in services[:MAX_SERVICE_CHIPS]))
        return own + (STAFF, PRICE)
    return topics_for(category_key)


def meaning_of(topic: Topic) -> Meaning | None:
    """What a chip is about: the catalog's wording, or for a service chip a plain line that names it. It says what the customer chose to comment on, never what happened."""
    m = MEANING.get(topic.id)
    if m is None and topic.id.startswith(SERVICE_PREFIX):
        return Meaning(f"the {topic.en.lower()} the customer chose to comment on", (), f"What did you like about the {topic.en.lower()}?", f"{topic.en} में आपको क्या अच्छा लगा?")
    return m


def follow_up_for(topic_ids: list[str], rating: int | None, language: str, typed: str) -> str | None:
    """ONE short, optional question, only when the customer gave us very little: a single topic and no words of their own. Never asked when
    the picks and words are already enough, and never required (the draft has already been written)."""
    if len(topic_ids) != 1 or typed.strip():
        return None
    m = MEANING.get(topic_ids[0])
    if not m:
        return None
    if rating is not None and rating <= 3:  # the question must fit the direction of the rating
        return {"en": "Is there anything specific you would like to add?", "hi": "क्या आप कुछ और खास जोड़ना चाहेंगे?"}[language if language in ("en", "hi") else "en"]
    return (m.ask_hi if language == "hi" else m.ask_en) or None
SENTIMENTS = {"good": "Good", "okay": "Okay", "not_good": "Not good"}
SENTIMENT_ASK = {
    "en": "How was it? Choose Good, Okay or Not good so we can reflect it honestly, or add a few words of your own.",
    "hi": "कैसा रहा? “अच्छा”, “ठीक-ठाक” या “अच्छा नहीं” चुनें ताकि हम इसे ईमानदारी से लिख सकें, या अपने कुछ शब्द जोड़ें।",
}


def category_options() -> list[dict]:
    return [{"key": k, "label": v["label"]} for k, v in CATALOG.items()]


def resolve_category(tenant_category: str | None, override: str | None = None) -> str:
    """Owner's explicit choice wins; otherwise match the free-text category by keyword (first catalog match); else the generic fallback."""
    if override in CATALOG:
        return override
    text = f" {(tenant_category or '').lower()} "
    for key, entry in CATALOG.items():
        if key != DEFAULT_CATEGORY and any(kw in text for kw in entry["keywords"]):
            return key
    return DEFAULT_CATEGORY


def topics_for(category_key: str) -> tuple[Topic, ...]:
    return CATALOG.get(category_key, CATALOG[DEFAULT_CATEGORY])["topics"]


# ---------------------------------------------------------------------------------------------------- owner-configured context
# Claims an owner must not be able to push into customers' reviews (via the description or service list).
_CLAIMS = re.compile(
    r"\b(best|no\.? ?1|number (?:one|1)|top[- ]rated|leading|world[- ]class|unmatched|unbeatable|guarantee\w*|100 ?%|cure[ds]?|miracle|painless|risk[- ]free|"
    r"award[- ]winning|certified best|discount\w*|offers?|free|cheapest|lowest price)\b|#\s?1\b|(?:₹|rs\.?|inr)\s?\d", re.I)
CLAIM_HELP = "Describe what you offer in plain, factual terms. Remove claims such as “best”, “guaranteed”, “cure”, “free” or prices."


def check_plain(value: str, what: str) -> str:
    if _CLAIMS.search(value):
        raise ValueError(f"{what}: {CLAIM_HELP}")
    if re.search(r"https?://|www\.|@\w+\.", value, re.I):
        raise ValueError(f"{what}: please remove links and email addresses.")
    return value


def clean_services(items: list[str]) -> list[str]:
    out, seen = [], set()
    for raw in items:
        s = clean_field(raw, 60)
        if len(s) < 2 or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(check_plain(s, f"Service “{s}”"))
    if len(out) > MAX_SERVICES:
        raise ValueError(f"Add at most {MAX_SERVICES} services or products.")
    return out


@dataclass(frozen=True)
class BusinessContext:
    business_name: str
    category_key: str
    category_label: str
    location: str | None
    description: str
    services: tuple[str, ...]
    languages: tuple[str, ...]
    topics: tuple[Topic, ...]  # the ENABLED topics
    every_topic: tuple[Topic, ...] = ()  # all of this business's topics, enabled or not (an earlier pick must still be understood after the owner switches a chip off)

    def prompt_block(self) -> str:
        """Context for the writer. Labelled as what the business OFFERS, explicitly not what this customer received."""
        lines = [f"Business type: {self.category_label}."]
        if self.description:
            lines.append(f"Owner's description: {self.description}")
        if self.services:
            lines.append("Services/products the business offers: " + "; ".join(self.services) + ".")
        lines.append("This is background ONLY. It says what the business offers, NOT what this customer received or experienced. "
                     "Never say or imply the customer used, ate, bought or was treated with anything unless THEY said so.")
        lines.append(f"Wording to prefer (vocabulary only, not events): {VOICE.get(self.category_key, VOICE['generic'])}")
        return "\n".join(lines)

    def offered_terms(self) -> tuple[str, ...]:
        """Words that name what the business offers. A draft may not use them unless the customer did (see validate_draft)."""
        words: set[str] = set(CATALOG[self.category_key].get("offered", ()))
        for s in self.services:
            words |= {w for w in re.findall(r"[a-z]{5,}", s.lower())}
        return tuple(sorted(words))


def merged_context(tenant, location=None) -> BusinessContext:
    """Build the context from the tenant row (+ its review_context JSON) and the campaign's location. Missing fields simply stay empty."""
    rc = tenant.review_context or {}
    key = resolve_category(tenant.category, rc.get("category_key"))
    disabled = set(rc.get("disabled_suggestions") or [])
    languages = tuple(l for l in (rc.get("languages") or LANGUAGES) if l in LANGUAGES) or LANGUAGES
    every = all_topics(rc, key)
    place = None
    if location is not None:
        place = ", ".join(p for p in (location.name, location.city) if p) or None
    return BusinessContext(
        business_name=tenant.name, category_key=key, category_label=CATALOG[key]["label"], location=place,
        description=clean_field(rc.get("description"), MAX_DESCRIPTION), services=tuple(clean_field(s, 60) for s in (rc.get("services") or [])),
        languages=languages, topics=tuple(t for t in every if t.id not in disabled), every_topic=every,
    )
