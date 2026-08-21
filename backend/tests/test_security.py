import base64
import hashlib

from cryptography.fernet import Fernet

from app.security import TokenCipher, create_pkce_pair, token_hash


def test_pkce_pair_matches_s256_challenge() -> None:
    verifier, challenge = create_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    )
    assert challenge == expected
    assert len(verifier) >= 43


def test_token_cipher_round_trip() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt("github-token")
    assert encrypted != "github-token"
    assert cipher.decrypt(encrypted) == "github-token"


def test_token_hash_is_stable_and_not_plaintext() -> None:
    assert token_hash("secret") == token_hash("secret")
    assert token_hash("secret") != "secret"
