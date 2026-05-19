# pyqttyai/core/whisper_languages.py
"""Complete list of languages supported by Whisper, with display names."""

# 🌍 Whisper's official language codes → display names
# Source: https://github.com/openai/whisper/blob/main/whisper/tokenizer.py
WHISPER_LANGUAGES: dict[str, str] = {
    "af": "Afrikaans",      "am": "Amharic",        "ar": "Arabic",
    "as": "Assamese",       "az": "Azerbaijani",    "ba": "Bashkir",
    "be": "Belarusian",     "bg": "Bulgarian",      "bn": "Bengali",
    "bo": "Tibetan",        "br": "Breton",         "bs": "Bosnian",
    "ca": "Catalan",        "cs": "Czech",          "cy": "Welsh",
    "da": "Danish",         "de": "German",         "el": "Greek",
    "en": "English",        "es": "Spanish",        "et": "Estonian",
    "eu": "Basque",         "fa": "Persian",        "fi": "Finnish",
    "fo": "Faroese",        "fr": "French",         "gl": "Galician",
    "gu": "Gujarati",       "ha": "Hausa",          "haw": "Hawaiian",
    "he": "Hebrew",         "hi": "Hindi",          "hr": "Croatian",
    "ht": "Haitian Creole", "hu": "Hungarian",      "hy": "Armenian",
    "id": "Indonesian",     "is": "Icelandic",      "it": "Italian",
    "ja": "Japanese",       "jw": "Javanese",       "ka": "Georgian",
    "kk": "Kazakh",         "km": "Khmer",          "kn": "Kannada",
    "ko": "Korean",         "la": "Latin",          "lb": "Luxembourgish",
    "ln": "Lingala",        "lo": "Lao",            "lt": "Lithuanian",
    "lv": "Latvian",        "mg": "Malagasy",       "mi": "Maori",
    "mk": "Macedonian",     "ml": "Malayalam",      "mn": "Mongolian",
    "mr": "Marathi",        "ms": "Malay",          "mt": "Maltese",
    "my": "Myanmar",        "ne": "Nepali",         "nl": "Dutch",
    "nn": "Nynorsk",        "no": "Norwegian",      "oc": "Occitan",
    "pa": "Punjabi",        "pl": "Polish",         "ps": "Pashto",
    "pt": "Portuguese",     "ro": "Romanian",       "ru": "Russian",
    "sa": "Sanskrit",       "sd": "Sindhi",         "si": "Sinhala",
    "sk": "Slovak",         "sl": "Slovenian",      "sn": "Shona",
    "so": "Somali",         "sq": "Albanian",       "sr": "Serbian",
    "su": "Sundanese",      "sv": "Swedish",        "sw": "Swahili",
    "ta": "Tamil",          "te": "Telugu",         "tg": "Tajik",
    "th": "Thai",           "tk": "Turkmen",        "tl": "Tagalog",
    "tr": "Turkish",        "tt": "Tatar",          "uk": "Ukrainian",
    "ur": "Urdu",           "uz": "Uzbek",          "vi": "Vietnamese",
    "yi": "Yiddish",         "yo": "Yoruba",        "yue": "Cantonese",
    "zh": "Chinese",
}

# 🎯 Sentinel value for the "Auto-detect" option
AUTO_DETECT = ""

# 🌟 Most commonly used (shown at the top of the dropdown)
POPULAR_LANGUAGES: list[str] = [
    "en", "pt", "es", "fr", "de", "it", "ja", "zh", "ko", "ru",
]


def language_name(code: str) -> str:
    """Human-friendly name for a language code."""
    if code == AUTO_DETECT:
        return "Auto-detect"
    return WHISPER_LANGUAGES.get(code, code.upper())


def language_display(code: str) -> str:
    """Compact display: 'Portuguese (pt)'. Used in dropdowns."""
    if code == AUTO_DETECT:
        return "🤖 Auto-detect"
    name = WHISPER_LANGUAGES.get(code, code.upper())
    return f"{name} ({code})"


def is_english_only_model(model_name: str) -> bool:
    """True if the model only supports English (`.en` suffix)."""
    return model_name.startswith("distil-") or model_name.endswith(".en")


def sorted_language_codes() -> list[str]:
    """All Whisper languages sorted alphabetically by display name."""
    return sorted(
        WHISPER_LANGUAGES.keys(),
        key=lambda c: WHISPER_LANGUAGES[c].lower(),
    )
