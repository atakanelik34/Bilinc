"""Search normalization shared by every recall path.

One fold for queries and stored text, so a query matches whatever spelling a
memory used: case, Turkish dotted and dotless I, and diacritics are ignored
(``İstanbul``, ``ISTANBUL`` and ``istanbul`` are the same term, and so are
``ışık``, ``IŞIK`` and ``isik``). The fold is lossy on purpose: it is only
used to compare text, never to store or return it.

The SQLite full-text index applies the same fold in SQL (see
``bilinc.storage.sqlite.FTS_V2_TEXT_SQL``): ``unicode61`` with
``remove_diacritics 2`` covers case and diacritics, and the dotless ``ı``,
which has no decomposition, is replaced explicitly.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List

_TERM = re.compile(r"[^\W_]+")

# Recall folds every candidate on every pass, so the common letters skip
# Unicode decomposition: Turkish first, then frequent Latin accents.
_FAST_FOLD = str.maketrans({
    "İ": "i", "I": "i", "ı": "i",
    "Ç": "c", "ç": "c", "Ğ": "g", "ğ": "g", "Ö": "o", "ö": "o",
    "Ş": "s", "ş": "s", "Ü": "u", "ü": "u",
    "Â": "a", "â": "a", "Î": "i", "î": "i", "Û": "u", "û": "u",
    "Á": "a", "á": "a", "À": "a", "à": "a", "Ä": "a", "ä": "a",
    "É": "e", "é": "e", "È": "e", "è": "e", "Ë": "e", "ë": "e", "Ê": "e", "ê": "e",
    "Í": "i", "í": "i", "Ï": "i", "ï": "i",
    "Ó": "o", "ó": "o", "Ô": "o", "ô": "o",
    "Ú": "u", "ú": "u", "Ñ": "n", "ñ": "n",
})

# Function words that carry no topic in Turkish questions, in folded form.
TURKISH_STOPWORDS = frozenset(
    {
        "ve", "veya", "ile", "bir", "bu", "su", "o", "da", "de", "ki", "mi", "mu",
        "ne", "icin", "gibi", "ama", "cok", "daha", "mis", "mus", "musun", "misin",
        "midir", "mudur", "nedir", "neydi", "nasil", "neden", "hangi", "kim",
        "kimdi", "olan", "olarak", "var", "yok", "en", "her", "hem",
    }
)


def fold_text(text: object) -> str:
    """Lowercase, map every Turkish I to ``i`` and drop diacritics."""
    raw = str(text or "")
    if raw.isascii():
        return raw.lower()
    folded = unicodedata.normalize("NFC", raw).translate(_FAST_FOLD).lower()
    if folded.isascii():
        return folded
    decomposed = unicodedata.normalize("NFD", folded)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_TURKISH_LETTERS = frozenset("çÇğĞıİöÖşŞüÜ")


def has_turkish_letters(text: object) -> bool:
    """Whether text uses a letter that only Turkish (among en/tr) has."""
    return any(ch in _TURKISH_LETTERS for ch in str(text or ""))


def folded_terms(folded: str) -> List[str]:
    """Letter/digit runs of text that is already folded."""
    return _TERM.findall(folded)


def search_terms(text: object) -> List[str]:
    """Folded letter/digit runs; underscores and punctuation separate terms."""
    return _TERM.findall(fold_text(text))
