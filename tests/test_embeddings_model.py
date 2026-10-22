"""The real int8 e5 graph. Downloads the pinned model, so it runs only when BILINC_TEST_EMBEDDINGS_MODEL is set."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("BILINC_TEST_EMBEDDINGS_MODEL"), reason="BILINC_TEST_EMBEDDINGS_MODEL not set"
)


def test_e5_int8_encodes_turkish_and_english_meaningfully():
    np = pytest.importorskip("numpy")
    from bilinc.embeddings.encoder import OnnxE5Encoder
    from bilinc.embeddings.text import PASSAGE_PREFIX, QUERY_PREFIX

    encoder = OnnxE5Encoder(threads=1)
    docs = encoder.encode([
        PASSAGE_PREFIX + "Girişimci yarışmasına başvuru 7 Ekim'de gönderildi.",
        PASSAGE_PREFIX + "The backup encryption key is kept in the password manager.",
    ])
    assert docs.shape == (2, 384) and docs.dtype == np.float32
    assert np.allclose(np.linalg.norm(docs, axis=1), 1.0, atol=1e-4)
    tr_query = encoder.encode([QUERY_PREFIX + "yarışma başvurusu ne zaman yapıldı?"])[0]
    en_query = encoder.encode([QUERY_PREFIX + "where is the backup key stored?"])[0]
    assert (docs @ tr_query).argmax() == 0
    assert (docs @ en_query).argmax() == 1
    again = encoder.encode([QUERY_PREFIX + "where is the backup key stored?"])[0]
    assert np.allclose(again, en_query, atol=1e-6)
