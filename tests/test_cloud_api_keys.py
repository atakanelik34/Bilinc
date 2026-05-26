from bilinc.cloud.api_keys import API_KEY_PREFIX, generate_api_key, hash_api_key, verify_api_key


def test_generate_api_key_returns_hash_not_raw_storage_material():
    material = generate_api_key()

    assert material.raw_key.startswith(API_KEY_PREFIX)
    assert material.prefix == material.raw_key[:16]
    assert material.secret_hash == hash_api_key(material.raw_key)
    assert material.raw_key not in material.secret_hash


def test_verify_api_key_rejects_wrong_secret():
    material = generate_api_key()

    assert verify_api_key(material.raw_key, material.secret_hash)
    assert not verify_api_key(f"{material.raw_key}x", material.secret_hash)
