"""Show Hindi as Hinglish: Devanagari words become English-script (Roman) words.

Done word by word, with one shared lookup, so the same word is always spelled the same way and a quote
still matches the transcript line it came from. New words are looked up with the language model once and
remembered in `hinglish_words.json` next to this file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from upsell_poc.schemas import Transcript

log = logging.getLogger(__name__)

DEVANAGARI = re.compile(r"[ऀ-ॣ०-ॿ]+")
_DANDA = re.compile(r"[।॥]")  # the Hindi full stop
SEED_FILE = Path(__file__).with_name("hinglish_words.json")  # ships with the code (read-only in a container)
# Words learned later are saved here; point HINGLISH_WORDS_FILE at the persistent disk when deployed.
LOOKUP_FILE = Path(os.environ.get("HINGLISH_WORDS_FILE") or SEED_FILE)
BATCH = 120
_lock = threading.Lock()

SYSTEM = (
    "You write Hindi words the way Indians type Hinglish in WhatsApp: English letters only, natural everyday "
    "spelling (for example: तीन -> teen, सौ -> sau, नहीं -> nahi, कीजिए -> kijiye, पैसे -> paise, है -> hai). "
    "Keep the meaning and pronunciation, no accents or diacritics, all lower case, and never translate to "
    "English. Return exactly one entry per word given, with the word copied unchanged."
)


class WordPair(BaseModel):
    word: str
    hinglish: str


class WordMap(BaseModel):
    items: list[WordPair]


def _read(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _load() -> dict[str, str]:
    """The shipped words plus any learned since (when those are kept in a separate file)."""
    if LOOKUP_FILE == SEED_FILE:
        return _read(SEED_FILE)
    return {**_read(SEED_FILE), **_read(LOOKUP_FILE)}


def _save(lookup: dict[str, str]) -> None:
    try:
        LOOKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LOOKUP_FILE.with_suffix(LOOKUP_FILE.suffix + ".tmp")  # write, then replace: no half-written file
        tmp.write_text(json.dumps(dict(sorted(lookup.items())), ensure_ascii=False, indent=0) + "\n", "utf-8")
        tmp.replace(LOOKUP_FILE)
    except OSError:
        # Not being able to remember a word must never fail an analysis; it is simply looked up again next time.
        log.warning("could not save Hinglish words to %s", LOOKUP_FILE, exc_info=True)


def known_words() -> dict[str, str]:
    """The Hindi words we already know how to spell in English letters (no model call)."""
    return _load()


def devanagari_words(text: str) -> set[str]:
    return set(DEVANAGARI.findall(text))


def ensure_words(words: set[str], chain: Any) -> dict[str, str]:
    """The lookup, extended (and saved) with any of `words` it does not know yet."""
    with _lock:
        lookup = _load()
        todo = sorted(w for w in words if w not in lookup)
        if todo and chain is None:
            log.warning("%d Hindi words left in Hindi script (no language model available)", len(todo))
            return lookup
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            try:
                result, _ = chain.generate(
                    step="romanize", system=SYSTEM, user="Words:\n" + "\n".join(batch), schema=WordMap
                )
            except Exception:  # noqa: BLE001 - spelling a word must never fail a finished analysis
                log.warning("could not spell %d Hindi words; leaving them", len(batch), exc_info=True)
                continue
            for pair in result.items:
                if pair.word in batch and pair.hinglish.strip():
                    lookup[pair.word] = pair.hinglish.strip()
        if todo:
            _save(lookup)
        return lookup


def romanize_text(text: str, lookup: dict[str, str]) -> str:
    text = DEVANAGARI.sub(lambda m: lookup.get(m.group(0), m.group(0)), text)
    return _DANDA.sub(".", text)


def romanize_obj(obj: Any, lookup: dict[str, str]) -> Any:
    """The same structure with every string romanized (dicts, lists and strings)."""
    if isinstance(obj, str):
        return romanize_text(obj, lookup)
    if isinstance(obj, list):
        return [romanize_obj(x, lookup) for x in obj]
    if isinstance(obj, dict):
        return {k: romanize_obj(v, lookup) for k, v in obj.items()}
    return obj


def strings_in(obj: Any) -> set[str]:
    if isinstance(obj, str):
        return devanagari_words(obj)
    if isinstance(obj, list):
        return set().union(*(strings_in(x) for x in obj)) if obj else set()
    if isinstance(obj, dict):
        return set().union(*(strings_in(v) for v in obj.values())) if obj else set()
    return set()


def romanize_transcript(transcript: Transcript, chain: Any) -> Transcript:
    """Transcript with Hindi script replaced by Hinglish (unchanged, and no model call, when there is none)."""
    words = set().union(*(devanagari_words(s.text) for s in transcript.segments)) if transcript.segments else set()
    if not words:
        return transcript
    lookup = ensure_words(words, chain)
    return transcript.model_copy(
        update={"segments": [s.model_copy(update={"text": romanize_text(s.text, lookup)}) for s in transcript.segments]}
    )


def romanize_document(doc: Any, chain: Any) -> Any:
    """Any JSON-like document (a report, a transcript file) with Hindi script replaced by Hinglish."""
    words = strings_in(doc)
    if not words:
        return doc
    return romanize_obj(doc, ensure_words(words, chain))
