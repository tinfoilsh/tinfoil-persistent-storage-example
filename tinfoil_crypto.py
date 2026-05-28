"""Decrypt S3 objects written by the AWS S3 Encryption Client v4 with a raw AES master key.

Supports the v4 default suite ALG_AES_256_GCM_HKDF_SHA512_COMMIT_KEY (id 0x0073).
Decrypt-only — no encrypt path.

Envelope (V3 metadata, on the S3 object as `x-amz-meta-x-amz-*`, surfaced by boto3
under `response["Metadata"]` with the `x-amz-meta-` prefix stripped):
  x-amz-3 → wrapped data key  (12-byte IV || 32-byte ct || 16-byte GCM tag = 60 B)
  x-amz-i → message ID         (28 B, used as HKDF salt + tamper-evidence)
  x-amz-d → key commitment     (28 B)
  x-amz-c → suite id as decimal string ("115")
  x-amz-w → wrap-alg ("02" = AES/GCM)

Decryption:
  1. AES-GCM unwrap x-amz-3 with master key. AAD = "115" (suite id decimal, UTF-8).
  2. HKDF-SHA512(salt=messageId, ikm=pdk):
       commitment = expand(info=b"\\x00\\x73COMMITKEY", L=28)  — must equal x-amz-d.
       content_key = expand(info=b"\\x00\\x73DERIVEKEY", L=32)
  3. AES-GCM decrypt body. IV = twelve 0x01 bytes (fixed). AAD = b"\\x00\\x73".
"""

import base64
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_SUITE_ID_BYTES = b"\x00\x73"  # content-AAD + first 2 bytes of HKDF info
_SUITE_ID_DEC = b"115"  # key-wrap AAD (decimal int as UTF-8)
_DERIVE_KEY_INFO = _SUITE_ID_BYTES + b"DERIVEKEY"
_COMMIT_KEY_INFO = _SUITE_ID_BYTES + b"COMMITKEY"
_COMMIT_LEN = 28
_DK_LEN = 32
_FIXED_CONTENT_IV = b"\x01" * 12


def decrypt_object(master_key: bytes, metadata: dict, body: bytes) -> bytes:
    """Decrypt one S3 object body given the master key, boto3 metadata dict, and ciphertext."""
    edk = base64.b64decode(metadata["x-amz-3"])
    iv, edk_ct = edk[:12], edk[12:]
    pdk = AESGCM(master_key).decrypt(iv, edk_ct, _SUITE_ID_DEC)
    if len(pdk) != _DK_LEN:
        raise ValueError(f"unexpected data key length {len(pdk)}")

    message_id = base64.b64decode(metadata["x-amz-i"])
    stored_commitment = base64.b64decode(metadata["x-amz-d"])

    derived_commitment = HKDF(
        algorithm=hashes.SHA512(),
        length=_COMMIT_LEN,
        salt=message_id,
        info=_COMMIT_KEY_INFO,
    ).derive(pdk)
    if not hmac.compare_digest(derived_commitment, stored_commitment):
        raise ValueError("key commitment mismatch — wrong key or tampered object")

    cek = HKDF(
        algorithm=hashes.SHA512(),
        length=_DK_LEN,
        salt=message_id,
        info=_DERIVE_KEY_INFO,
    ).derive(pdk)

    return AESGCM(cek).decrypt(_FIXED_CONTENT_IV, body, _SUITE_ID_BYTES)
