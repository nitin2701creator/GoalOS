"""WhatsApp Multilingual Service for GoalOS.

Provides lightweight language detection for incoming WhatsApp messages
and multilingual response generation.

Supported languages (with special attention for Indian languages):
- English
- Hindi (हिन्दी)
- Hinglish (Hindi-English mix)
- Bengali (বাংলা)
- Marathi (मराठी)
- Gujarati (ગુજરાતી)
- Tamil (தமிழ்)
- Telugu (తెలుగు)
- Kannada (ಕನ್ನಡ)
- Malayalam (മലയാളം)
- Punjabi (ਪੰਜਾਬੀ)

Detection is character-range based (lightweight, no external dependencies).
Responses are generated via the existing LLM abstraction, which can
produce output in any language the model supports.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language detection via Unicode character ranges
# ---------------------------------------------------------------------------

# Script ranges for Indian languages (Unicode blocks)
_SCRIPT_RANGES: list[tuple[str, str, str]] = [
    # (language, start_char, end_char) — using ordinals
    ("hindi", "\u0900", "\u097F"),       # Devanagari
    ("bengali", "\u0980", "\u09FF"),     # Bengali
    ("punjabi", "\u0A00", "\u0A7F"),     # Gurmukhi
    ("gujarati", "\u0A80", "\u0AFF"),    # Gujarati
    ("tamil", "\u0B80", "\u0BFF"),       # Tamil
    ("telugu", "\u0C00", "\u0C7F"),      # Telugu
    ("kannada", "\u0C80", "\u0CFF"),     # Kannada
    ("malayalam", "\u0D00", "\u0D7F"),   # Malayalam
    ("marathi", "\u0900", "\u097F"),     # Devanagari (same as Hindi)
]

# Detection confidence thresholds
_MIN_CHARS_FOR_DETECTION = 3
_MIN_SCRIPT_RATIO = 0.3  # At least 30% of chars in a script to detect


def detect_language(text: str) -> dict[str, Any]:
    """Detect the language of a text message using character-range analysis.

    Returns:
        {
            "language": str,          # detected language code
            "confidence": float,      # 0.0 to 1.0
            "script": str | None,     # detected script name
            "is_mixed": bool,         # True if multiple scripts detected
            "dominant_script": str | None,
        }
    """
    if not text or not text.strip():
        return {
            "language": "unknown",
            "confidence": 0.0,
            "script": None,
            "is_mixed": False,
            "dominant_script": None,
        }

    text = text.strip()

    # Count characters by script
    script_counts: dict[str, int] = {}
    latin_count = 0
    total_alpha = 0

    for char in text:
        if char.isalpha():
            total_alpha += 1
            code = ord(char)

            # Check each script range
            found = False
            for lang, start, end in _SCRIPT_RANGES:
                if ord(start) <= code <= ord(end):
                    # Marathi and Hindi share Devanagari — use heuristic
                    if lang == "marathi":
                        script_counts["devanagari"] = script_counts.get("devanagari", 0) + 1
                    else:
                        script_counts[lang] = script_counts.get(lang, 0) + 1
                    found = True
                    break

            if not found:
                # Check Latin range
                if (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
                    latin_count += 1
                    script_counts["latin"] = script_counts.get("latin", 0) + 1
                # Extended Latin (accented characters, common in European languages)
                elif (0x00C0 <= code <= 0x024F) or (0x1E00 <= code <= 0x1EFF):
                    latin_count += 1
                    script_counts["latin"] = script_counts.get("latin", 0) + 1

    if total_alpha == 0:
        return {
            "language": "unknown",
            "confidence": 0.0,
            "script": None,
            "is_mixed": False,
            "dominant_script": None,
        }

    # Determine dominant script
    if not script_counts:
        return {
            "language": "unknown",
            "confidence": 0.0,
            "script": None,
            "is_mixed": False,
            "dominant_script": None,
        }

    dominant_script = max(script_counts, key=script_counts.get)
    dominant_count = script_counts[dominant_script]
    confidence = dominant_count / total_alpha

    # Check for mixed scripts (Hinglish detection)
    scripts_present = [s for s, c in script_counts.items() if c > 0 and s != dominant_script]
    is_mixed = len(scripts_present) > 0 and confidence < 0.7

    # Map script to language
    if dominant_script == "latin":
        language = "english"
    elif dominant_script == "devanagari":
        # Distinguish Hindi vs Marathi via common markers
        text_lower = text.lower()
        marathi_markers = ["आहे", "ते", "मी", "तू", "करा", "होता", "नाही", "असे"]
        marathi_count = sum(1 for m in marathi_markers if m in text)
        if marathi_count >= 2:
            language = "marathi"
        else:
            language = "hindi"
    elif dominant_script in _SCRIPT_RANGES_MAP:
        language = _SCRIPT_RANGES_MAP[dominant_script]
    else:
        language = dominant_script

    # Hinglish detection: Latin + Devanagari mix (or predominantly Latin with Hindi context)
    if is_mixed and "latin" in script_counts and "devanagari" in script_counts:
        language = "hinglish"
        confidence = max(script_counts.get("latin", 0), script_counts.get("devanagari", 0)) / total_alpha
    # Also detect Hinglish when Latin-dominant but contains common Hindi/Urdu words in Latin script
    elif dominant_script == "latin" and confidence > 0.5:
        hinglish_markers = {"hai", "hain", "karo", "kya", "mera", "tumhara", "chahiye", "nahi", "ho", "tha", "se", "ko", "ka", "ki", "ke", "mein", "mai", "aap", "hum", "kaise", "karlo", "bhejo", "bolo", "suno", "deko", "jao", "aao", "lo", "do", "bol", "bolna", "samajh", "nhi", "haan", "ji", "na", "boss", "yaar", "bhai", "didi", "anna", "akka", "dada", "tau", "mama"}
        # Strip punctuation from words for matching
        import string
        words = set(w.strip(string.punctuation) for w in text.lower().split())
        hinglish_count = len(words & hinglish_markers)
        if hinglish_count >= 2:
            language = "hinglish"
            confidence = 0.7

    return {
        "language": language,
        "confidence": round(min(confidence, 1.0), 2),
        "script": dominant_script,
        "is_mixed": is_mixed,
        "dominant_script": dominant_script,
    }


# Script to language mapping
_SCRIPT_RANGES_MAP = {
    "bengali": "bengali",
    "punjabi": "punjabi",
    "gujarati": "gujarati",
    "tamil": "tamil",
    "telugu": "telugu",
    "kannada": "kannada",
    "malayalam": "malayalam",
}


# ---------------------------------------------------------------------------
# Multilingual system prompt augmentation
# ---------------------------------------------------------------------------

# Language display names for user-facing responses
LANGUAGE_NAMES: dict[str, str] = {
    "english": "English",
    "hindi": "Hindi",
    "hinglish": "Hinglish",
    "bengali": "Bengali",
    "marathi": "Marathi",
    "gujarati": "Gujarati",
    "tamil": "Tamil",
    "telugu": "Telugu",
    "kannada": "Kannada",
    "malayalam": "Malayalam",
    "punjabi": "Punjabi",
    "unknown": "Unknown",
}


def augment_prompt_with_language(
    base_prompt: str,
    detected_language: str,
    *,
    force_language: bool = True,
) -> str:
    """Augment the system prompt with language instructions.

    When force_language is True, the LLM will respond in the detected language.
    This preserves conversational continuity across languages.
    """
    if detected_language == "unknown" or not force_language:
        return base_prompt

    lang_name = LANGUAGE_NAMES.get(detected_language, "English")

    if detected_language == "hinglish":
        language_instruction = (
            "\n\nIMPORTANT: The customer is writing in Hinglish (Hindi-English mix). "
            "Respond in the same Hinglish style — mix Hindi and English naturally "
            "as the customer does. Do not switch to pure English or pure Hindi."
        )
    elif detected_language == "english":
        language_instruction = ""  # No extra instruction needed
    else:
        language_instruction = (
            f"\n\nIMPORTANT: The customer is writing in {lang_name}. "
            f"Respond in {lang_name}. Keep the same professional tone. "
            f"If you cannot respond well in {lang_name}, respond in English "
            f"and acknowledge the language difference."
        )

    return base_prompt + language_instruction


def get_language_display_name(language_code: str) -> str:
    """Get the display name for a language code."""
    return LANGUAGE_NAMES.get(language_code, language_code.title())


def is_indian_language(language: str) -> bool:
    """Check if a language is an Indian language."""
    indian_languages = {
        "hindi", "hinglish", "bengali", "marathi", "gujarati",
        "tamil", "telugu", "kannada", "malayalam", "punjabi",
    }
    return language.lower() in indian_languages
