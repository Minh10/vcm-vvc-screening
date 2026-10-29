import pytest


@pytest.fixture(autouse=True)
def _isolated_hash_cache(tmp_path, monkeypatch):
    """Never touch the user's persistent hash cache from the tests."""
    monkeypatch.setenv("VCM_HASH_CACHE", str(tmp_path / "sha256_cache.json"))
