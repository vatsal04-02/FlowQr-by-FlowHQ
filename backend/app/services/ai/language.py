import re

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Common romanised-Hindi words: used only to tell Hinglish from English. Words that are also ordinary English ("the", "to", "do", "me", "so", "par", "main",
# "doctor") are deliberately left out, so an English review is never mistaken for Hinglish.
HINGLISH_WORDS = {
    "hai", "hain", "nahi", "nahin", "bahut", "accha", "acha", "achha", "achhe", "acche", "achi", "achhi", "bohot", "bahot", "kaafi", "sab", "aur", "mera", "meri", "mere",
    "humne", "hum", "humara", "humari", "humare", "hamara", "hamari", "hamare", "aap", "aapka", "aapki", "aapke", "aapne", "aapko", "ka", "ki", "ke", "ko", "se", "mein", "tha", "thi",
    "bhi", "kya", "ilaaj", "dawai", "dhanyawad", "dhanyavaad", "shukriya", "badhiya", "zabardast", "thik", "theek", "behtareen", "kaam",
    "bhai", "yaar", "thoda", "thodi", "thode", "bilkul", "lekin", "kuch", "koi", "hamesha", "ekdum", "mast", "dikkat", "pareshani", "dukaan", "wala", "wali", "wale",
    "gaya", "gayi", "gaye", "liya", "diya", "kiya", "kiye", "karte", "karna", "karo", "rahe", "raha", "rahi", "hota", "hoti", "hote", "hua", "hui", "hue", "toh",
    "woh", "yeh", "jyada", "zyada", "paisa", "paise", "kharcha", "mehenga", "mehnga", "sasta", "saaf", "bheed", "intezaar", "jaldi", "madad", "baat", "sahi", "galat",
    "pyaar", "dhyan", "swad", "ghar", "bachon", "bete", "beti", "behad", "samjhaya", "bataya", "padhai", "dobara", "phir", "abhi", "kabhi", "isliye",
    "kyunki", "magar", "sirf", "wahan", "yahan", "logon", "pehle", "raat", "subah", "shaam",
}


def detect_language(text: str) -> str:
    if len(DEVANAGARI.findall(text)) >= 3:
        return "hi"
    words = re.findall(r"[a-z]+", text.lower())
    hits = sum(1 for w in words if w in HINGLISH_WORDS and w != "doctor")
    return "hinglish" if hits >= 2 else "en"


LANGUAGE_INSTRUCTION = {
    "en": "Write in clear, natural English.",
    "hi": "Write in Hindi using Devanagari script.",
    "hinglish": "Write in Hinglish: Hindi written in Roman script mixed naturally with English, as people text in India.",
}
