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

# Turkish function words, in folded form, that are never content in English
# or technical text either; dropped from every query.
TURKISH_STOPWORDS = frozenset(
    {
        "ve", "veya", "ile", "bir", "bu", "icin", "gibi", "ama", "cok", "daha",
        "mis", "mus", "musun", "misin", "midir", "mudur", "nedir", "neydi", "nasil",
        "neden", "hangi", "kimdi", "olan", "olarak", "yok", "hem",
    }
)
# Turkish function words that are also English or technical terms ("su" the
# command, "var" the keyword, "en" the language code); dropped only from a
# query that reads as Turkish.
TURKISH_CONTEXT_STOPWORDS = frozenset({"su", "var", "en", "o", "ne", "da", "de", "ki", "mi", "mu", "her", "kim"})


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


# Function words that mark a query as Turkish even without Turkish letters.
# Short ones are left out: "ve" also comes from English contractions ("I've").
_TURKISH_QUERY_MARKERS = TURKISH_STOPWORDS - {"ve", "bu", "ama", "ile", "hem", "bir", "mis", "mus"}


def is_turkish_query(text: object) -> bool:
    """Whether a query reads as Turkish: a Turkish letter or a clearly Turkish function word."""
    return has_turkish_letters(text) or bool(_TURKISH_QUERY_MARKERS.intersection(search_terms(text)))


def query_stopwords(query: object, base: frozenset) -> frozenset:
    """The stopwords to drop from one query: ``base``, plus the ambiguous Turkish ones for a Turkish query."""
    return base | TURKISH_CONTEXT_STOPWORDS if is_turkish_query(query) else base


def folded_terms(folded: str) -> List[str]:
    """Letter/digit runs of text that is already folded."""
    return _TERM.findall(folded)


def search_terms(text: object) -> List[str]:
    """Folded letter/digit runs; underscores and punctuation separate terms."""
    return _TERM.findall(fold_text(text))
