"""The assistant's fixed words and its deterministic rules (no database, no model).

Anything a customer must be able to rely on is FIXED TEXT here, never model output: the line that says it is an automated assistant, the "someone will reply" line, the refusal for questions that
are not about the business, greetings and thanks. The model only ever writes the body of an "answer", and only from the business's own facts (see agent.py). Pre-checks run BEFORE any model call, so
a hand-off request, an emergency, an OTP, an injection attempt or a general-assistant request never reach the provider.

Languages: English, Hindi (Devanagari) and Hinglish (Hindi in Latin letters). Other languages fall back to English fixed text; the model's own answer follows the customer's language."""
from __future__ import annotations

import re

LANGS = ("en", "hi", "hinglish")

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HINGLISH = re.compile(r"\b(aap|aapka|aapki|apka|apki|kya|kaise|kab|kahan|kitna|kitne|kitni|hai|hain|ho|hoga|hogi|chahiye|karna|karni|karo|kijiye|bataiye|batao|bata|mujhe|mera|meri|mere|hum|humein|nahi|nahin|"
                       r"haan|ji|dikhao|milega|milegi|khula|khule|band|samay|time kya|ghar|dukaan|kal|aaj|abhi|bhai|sir ji|madam ji|dhanyavad|shukriya|namaste)\b", re.I)


def detect_lang(text: str | None) -> str:
    t = text or ""
    letters = sum(c.isalpha() for c in t) or 1
    if len(_DEVANAGARI.findall(t)) / letters > 0.3:
        return "hi"
    if len(_HINGLISH.findall(t)) >= 2 or (len(_HINGLISH.findall(t)) >= 1 and len(t.split()) <= 4):
        return "hinglish"
    return "en"


def _l(lang: str) -> str:
    return lang if lang in LANGS else "en"


DISCLOSURE = {
    "en": "Hi! I'm the automated assistant for {business}. ",
    "hi": "नमस्ते! मैं {business} का स्वचालित (ऑटोमैटिक) असिस्टेंट हूँ। ",
    "hinglish": "Namaste! Main {business} ka automated assistant hoon. ",
}
HOLDING = {
    "en": "Thanks for your message. I have asked someone from {business} to reply to you here. Please wait a little.",
    "hi": "आपके संदेश के लिए धन्यवाद। मैंने {business} की टीम से किसी को यहीं जवाब देने के लिए कहा है। कृपया थोड़ा इंतज़ार करें।",
    "hinglish": "Aapke message ke liye shukriya. Maine {business} ki team se kisi ko yahin reply karne ke liye kaha hai. Please thoda wait kijiye.",
}
REFUSAL = {
    "en": "I can only help with questions about {business}, such as what we do, our timings and where to find us. For anything else, please contact the team directly.",
    "hi": "मैं केवल {business} से जुड़े सवालों में मदद कर सकता हूँ, जैसे हम क्या करते हैं, हमारा समय और पता। बाकी बातों के लिए कृपया टीम से सीधे संपर्क करें।",
    "hinglish": "Main sirf {business} se jude sawaalon mein madad kar sakta hoon, jaise hum kya karte hain, hamara time aur pata. Baaki baaton ke liye please team se seedha baat kijiye.",
}
SENSITIVE_DATA = {
    "en": "For your safety, please do not share OTPs, card, bank or ID details here. Someone from {business} will contact you.",
    "hi": "आपकी सुरक्षा के लिए कृपया यहाँ OTP, कार्ड, बैंक या पहचान की जानकारी साझा न करें। {business} की टीम से कोई आपसे संपर्क करेगा।",
    "hinglish": "Aapki suraksha ke liye please yahan OTP, card, bank ya ID ki details share mat kijiye. {business} ki team se koi aapse contact karega.",
}
GREET = {"en": "How can I help you today?", "hi": "मैं आपकी क्या मदद कर सकता हूँ?", "hinglish": "Main aapki kya madad kar sakta hoon?"}
THANKS = {"en": "You're welcome! Let us know if you need anything else.", "hi": "आपका स्वागत है! और कुछ चाहिए तो बताइए।", "hinglish": "Aapka swagat hai! Aur kuch chahiye to bataiye."}


BOOKED = {
    "en": "Your appointment is booked: {service}, {when}.",
    "hi": "आपकी अपॉइंटमेंट बुक हो गई है: {service}, {when}।",
    "hinglish": "Aapki appointment book ho gayi hai: {service}, {when}.",
}
ASK_UPDATES = {
    "en": "Would you like a reminder and updates about this visit on WhatsApp from {business}? Reply YES if you would.",
    "hi": "क्या आप इस विज़िट के बारे में {business} से व्हाट्सऐप पर रिमाइंडर और अपडेट चाहते हैं? चाहें तो YES लिखें।",
    "hinglish": "Kya aap is visit ke baare mein {business} se WhatsApp par reminder aur updates chahte hain? Chahein to YES likhein.",
}
UPDATES_YES = {"en": "Thank you. We will send you a reminder about this visit.", "hi": "धन्यवाद। हम आपको इस विज़िट की याद दिलाएंगे।", "hinglish": "Shukriya. Hum aapko is visit ka reminder bhejenge."}
UPDATES_NO = {"en": "No problem, we will not send reminders. Your appointment is still booked.", "hi": "कोई बात नहीं, हम रिमाइंडर नहीं भेजेंगे। आपकी अपॉइंटमेंट बुक है।", "hinglish": "Koi baat nahi, hum reminder nahi bhejenge. Aapki appointment book hai."}
RESCHEDULED = {"en": "Done. Your appointment is moved: {service}, {when}.", "hi": "हो गया। आपकी अपॉइंटमेंट बदल दी गई है: {service}, {when}।", "hinglish": "Ho gaya. Aapki appointment badal di gayi hai: {service}, {when}."}
CANCELLED = {"en": "Your appointment ({service}, {when}) is cancelled.", "hi": "आपकी अपॉइंटमेंट ({service}, {when}) रद्द कर दी गई है।", "hinglish": "Aapki appointment ({service}, {when}) cancel kar di gayi hai."}


def say(table: dict, lang: str, business: str = "", **kw) -> str:
    return table[_l(lang)].format(business=business or "the business", **kw)


# ---- pre-checks (customer text, before any model call)
def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.I)


HUMAN_REQUEST = _rx(r"\b(talk|speak|chat|connect)\s+(to|with)\s+(a\s+|the\s+|some\s*)?(human|person|real person|someone|agent|manager|owner|staff|executive)\b", r"\b(human|real person|live agent|customer care|customer support|call me|call back)\b",
                    r"\bnot a bot\b", r"\b(insaan|insan|aadmi|manager|owner|malik)\s+(se\s+)?(baat|bat|bol)", r"\b(kisi\s+se\s+baat|baat\s+karni\s+hai|call\s+karo|phone\s+karo)\b", r"इंसान|व्यक्ति से बात|मैनेजर|मालिक से|किसी से बात|कॉल करो")
SENSITIVE_TOPIC = _rx(r"\b(emergency|ambulance|chest pain|heart attack|can'?t breathe|bleeding|overdose|poison|suicide|kill myself|self[- ]harm|want to die|harass|abuse[ds]?|assault|molest)\b",
                      r"\b(lawyer|legal notice|legal action|sue you|court|consumer forum|consumer court|police|fir\b|fraud|cheated|scam|refund|chargeback|compensation)\b",
                      r"\b(complaint|complain|very bad service|worst|disgusting|negligence)\b", r"\b(emergency|accident|bachao|madad chahiye turant)\b", r"आपातकाल|एम्बुलेंस|आत्महत्या|पुलिस|वकील|धोखा|शिकायत|रिफंड")
SENSITIVE_DATA_RX = [re.compile(p, re.I) for p in (r"\b(otp|cvv|cvc|pin|password|passcode)\b.{0,20}\d{3,8}", r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b(?=.*(aadhaar|aadhar|uid))", r"\b[A-Z]{5}\d{4}[A-Z]\b",
                                                                             r"\b(aadhaar|aadhar|pan card|pan number|account number|ifsc|upi pin)\b.{0,25}\d")]
INJECTION = _rx(r"ignore (all |any |the )?(previous|prior|above|earlier|your)\b", r"disregard (all |any |the )?(previous|prior|above|your)", r"forget (all |your |the )?(instructions|rules|previous)", r"(system|hidden|initial) (prompt|instructions?|message)",
                r"\b(you are|you're) (now|no longer)\b", r"\bact as\b", r"\bpretend (to be|you)\b", r"\bjailbreak\b", r"developer mode", r"\b(?-i:DAN)\b", r"reveal (your|the) (prompt|instructions|rules|knowledge)", r"print (your|the) (prompt|instructions)",
                r"override (your|the|all) ", r"new instructions?:", r"</?(system|assistant|instructions?)>", r"\[(system|inst)\]", r"repeat (everything|all) (above|before)", r"what (are|were) your (instructions|rules)",
                r"pichle (saare )?(instructions|nirdesh) (bhool|ignore)|apne (instructions|rules) (batao|bhool)", r"पिछले निर्देश|निर्देशों को अनदेखा|अपना प्रॉम्प्ट")
OFF_TOPIC = _rx(r"\b(poem|poetry|song lyrics|joke|riddle|homework|python|javascript|sql|regex|bitcoin|crypto|stock tips|share market|nifty|sensex|lottery|horoscope|astrology)\b",
                r"\bwrite (me |us )?(a |an |some )?(story|essay|code|program|script|letter|article|blog)\b",
                r"\b(weather|cricket score|ipl|movie review|recipe|translate|translation|capital of|prime minister|president of|who invented|how to (cook|hack|make a bomb)|math problem|solve this)\b",
                r"\b(chatgpt|gpt|openai|gemini|llm|language model|which model|who made you|who built you|what model)\b", r"कविता|चुटकुला|कहानी|निबंध|कोड|मौसम|राशिफल")


def human_requested(text: str) -> bool:
    return bool(HUMAN_REQUEST.search(text or ""))


def sensitive_topic(text: str) -> bool:
    return bool(SENSITIVE_TOPIC.search(text or ""))


def sensitive_data(text: str) -> bool:
    t = text or ""
    return any(r.search(t) for r in SENSITIVE_DATA_RX)


def injection(text: str) -> bool:
    return bool(INJECTION.search(text or ""))


def off_topic(text: str) -> bool:
    return bool(OFF_TOPIC.search(text or ""))


def precheck(text: str) -> str | None:
    """The first pre-check the customer's text trips, as a stable code, in priority order (safety first). None means the model may be asked."""
    if sensitive_data(text):
        return "sensitive_data"
    if sensitive_topic(text):
        return "sensitive_topic"
    if injection(text):  # before "a person": an injected "say you are human" is an attack, not a request
        return "injection"
    if human_requested(text):
        return "human"
    if off_topic(text):
        return "off_topic"
    return None


# ---- output validators (model text, before anything is sent)
_HUMAN_CLAIM = _rx(r"\b(i am|i'm|im|main|mai)\s+(a\s+)?(real\s+)?(human|person|insaan|insan|aadmi|staff member|employee|owner|doctor|dentist|physio)\b", r"\bas a (human|person)\b", r"\bnot (a )?(bot|robot|ai|machine)\b", r"मैं (एक )?(इंसान|व्यक्ति|मालिक) हूँ")
_PAYMENT = _rx(r"\b(send|share|give|tell|enter|type)\b.{0,30}\b(otp|cvv|card number|card details|password|upi pin|pin|aadhaar|aadhar|pan|bank details|account number)\b", r"\b(pay|transfer|send)\b.{0,25}\b(now|here|to this)\b.{0,25}\b(upi|account|number)\b",
               r"\b(otp|cvv|pin)\b.{0,15}\b(bhejiye|batao|share karo|dijiye)\b")
_ADVICE = _rx(r"\byou (should|must|need to|ought to) (take|stop|start|increase|decrease|avoid|continue)\b.{0,40}\b(medicine|medication|tablet|dose|dosage|drug|antibiotic|painkiller|insulin|supplement)\b", r"\b(diagnos(e|is|ed)|prescri(be|ption)|dosage|cure[sd]?|guarantee[sd]? (results|recovery|cure))\b",
              r"\b(your|the) (condition|symptoms?|pain|injury|infection) (is|are|means|sounds like|could be)\b", r"\b(legal advice|investment advice|you will (definitely|surely) (recover|be cured|get better))\b")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|in|co|net|org|me|site|app|io)\b(?:/\S*)?", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CLOCK = re.compile(r"(\d{1,2}):([0-5]\d)")


def claims_human(text: str) -> bool:
    return bool(_HUMAN_CLAIM.search(text or ""))


def asks_for_payment_or_secrets(text: str) -> bool:
    return bool(_PAYMENT.search(text or ""))


def gives_advice(text: str) -> bool:
    return bool(_ADVICE.search(text or ""))


def _digits(s: str) -> str:
    return re.sub(r"[^\d.]", "", s)


def ungrounded_facts(text: str, facts: str) -> list[str]:
    """Numbers, links and e-mail addresses in the reply that do not appear in the facts it cites. A reply that states a price, a time, a phone number or a link the owner never wrote is not sent.
    Digits are compared without separators, so "9,00" and "900" are not confused but "1,500" matches "1500"."""
    bad: list[str] = []
    fl = (facts or "").lower()
    fd = {_digits(m.group(0)).strip(".") for m in _NUM.finditer(facts or "")}
    for m in _NUM.finditer(text or ""):
        d = _digits(m.group(0)).strip(".")
        if d and d not in fd and d not in {"1", "2", "3"}:  # "1 session", "2 floors" are ordinary words; any other figure must be in the facts
            bad.append(m.group(0))
    have_times = {f"{int(h)}:{mm}" for h, mm in _CLOCK.findall(facts or "")}
    for h, mm in _CLOCK.findall(text or ""):  # a time of day must appear exactly as written in the facts: "4:45" is not grounded just because a "4" and a "45" are
        if f"{int(h)}:{mm}" not in have_times:
            bad.append(f"{h}:{mm}")
    for m in list(_URL.finditer(text or "")) + list(_EMAIL.finditer(text or "")):
        if m.group(0).lower().rstrip(".,)") not in fl:
            bad.append(m.group(0))
    return bad
