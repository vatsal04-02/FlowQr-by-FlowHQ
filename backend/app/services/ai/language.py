import re

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Common romanised-Hindi words: used only to tell Hinglish from English.
HINGLISH_WORDS = {
    "hai", "hain", "nahi", "nahin", "bahut", "accha", "acha", "achha", "bohot", "kaafi", "sab", "aur", "mera", "meri",
    "humne", "hum", "aap", "aapka", "doctor", "ka", "ki", "ke", "ko", "se", "mein", "main", "tha", "thi", "bhi", "kya",
    "ilaaj", "dawai", "dhanyawad", "shukriya", "badhiya", "zabardast", "thik", "theek", "behtareen", "kaam",
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
