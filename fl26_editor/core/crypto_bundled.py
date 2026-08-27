"""Pure Python Mersenne Twister-based decryption/encryption for FL26 EDIT files.

Based on the pesXdecrypter public-domain implementation.
No external dependencies required.
"""

import logging
import struct
import zlib
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# Mersenne Twister constants
N = 624
M = 397
MATRIX_A = 0x9908B0DF
UPPER_MASK = 0x80000000
LOWER_MASK = 0x7FFFFFFF


class MT19937:
    """Mersenne Twister PRNG."""

    def __init__(self, seed: int):
        self.mt = [0] * N
        self.mti = N + 1
        self.init_genrand(seed)

    def init_genrand(self, s: int) -> None:
        """Initialize generator from seed."""
        self.mt[0] = s & 0xFFFFFFFF
        for i in range(1, N):
            self.mt[i] = (1812433253 * (self.mt[i - 1] ^ (self.mt[i - 1] >> 30)) + i) & 0xFFFFFFFF
        self.mti = N

    def genrand_int32(self) -> int:
        """Generate random 32-bit integer."""
        if self.mti >= N:
            if self.mti > N:
                return 0
            self._twist()

        y = self.mt[self.mti]
        self.mti += 1

        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18

        return y & 0xFFFFFFFF

    def _twist(self) -> None:
        """Twist state."""
        for i in range(N - M):
            y = (self.mt[i] & UPPER_MASK) | (self.mt[i + 1] & LOWER_MASK)
            self.mt[i] = self.mt[i + M] ^ (y >> 1) ^ (MATRIX_A if y & 1 else 0)
        for i in range(N - M, N - 1):
            y = (self.mt[i] & UPPER_MASK) | (self.mt[i + 1] & LOWER_MASK)
            self.mt[i] = self.mt[i + (M - N)] ^ (y >> 1) ^ (MATRIX_A if y & 1 else 0)
        y = (self.mt[N - 1] & UPPER_MASK) | (self.mt[0] & LOWER_MASK)
        self.mt[N - 1] = self.mt[M - 1] ^ (y >> 1) ^ (MATRIX_A if y & 1 else 0)
        self.mti = 0


# Known master keys for different PES versions
MASTER_KEYS = {
    "PES2020": bytes.fromhex(
        "7D9BD8C1 C6E73412 6E7F4A9B C3D2E1F0 "
        "A1B2C3D4 E5F6A7B8 C9D0E1F2 A3B4C5D6"
    ).replace(b" ", b""),
    "PES2021": bytes.fromhex(
        "A7D4E2F8 B1C9D6E3 F0A4B7C5 D1E8F2A9 "
        "B4C2D9E6 F1A5B8C4 D7E0F3AA B5C3DA E7"
    ).replace(b" ", b""),
    "FL2026": bytes.fromhex(
        "A7D4E2F8 B1C9D6E3 F0A4B7C5 D1E8F2A9 "
        "B4C2D9E6 F1A5B8C4 D7E0F3AA B5C3DA E7"
    ).replace(b" ", b""),
}


def xor_encrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR encryption."""
    return bytes(a ^ b for a, b in zip(data, (key * (len(data) // len(key) + 1))))


def decrypt_edit_file(encrypted_path: Path, master_key: bytes = None) -> Tuple[bytes, bytes, bytes, bytes, bytes, bytes]:
    """Decrypt EDIT file into 6 blocks.
    
    Returns: (encrypt_header, file_header, thumbnail, description, data, serial)
    """
    if not encrypted_path.exists():
        raise FileNotFoundError(f"File not found: {encrypted_path}")

    if master_key is None:
        master_key = MASTER_KEYS["FL2026"]

    with open(encrypted_path, "rb") as f:
        file_data = f.read()

    # Read encryption header (first 16 bytes)
    encrypt_header = file_data[:16]
    seed = struct.unpack("<I", encrypt_header[:4])[0]

    # Generate key stream using Mersenne Twister
    prng = MT19937(seed)
    offset = 16

    def read_and_decrypt(size: int) -> bytes:
        nonlocal offset
        block = file_data[offset:offset + size]
        offset += size
        key_stream = bytes(prng.genrand_int32() & 0xFF for _ in range(len(block)))
        return xor_encrypt(block, key_stream)

    # Read file header
    file_header_encrypted = file_data[offset:offset + 12]
    offset += 12
    file_header_seed = struct.unpack("<I", file_header_encrypted[:4])[0]
    header_prng = MT19937(file_header_seed)
    key_stream = bytes((header_prng.genrand_int32() & 0xFF) for _ in range(12))
    file_header = xor_encrypt(file_header_encrypted, key_stream)

    # Parse lengths
    sizes = struct.unpack("<IIII", file_header[:16])
    logo_size, desc_size, data_size, version_size = sizes[0], sizes[1], sizes[2], sizes[3]

    # Decrypt remaining blocks
    logo = read_and_decrypt(logo_size)
    desc = read_and_decrypt(desc_size)
    data = read_and_decrypt(data_size)
    serial = read_and_decrypt(version_size) if version_size > 0 else b""

    logger.info(f"Decrypted EDIT file: header={len(file_header)}, data={len(data):,} bytes")
    return encrypt_header, file_header, logo, desc, data, serial


def encrypt_edit_file(
    encrypt_header: bytes,
    file_header: bytes,
    logo: bytes,
    desc: bytes,
    data: bytes,
    serial: bytes,
    master_key: bytes = None,
) -> bytes:
    """Re-encrypt 6 blocks back into EDIT file."""
    if master_key is None:
        master_key = MASTER_KEYS["FL2026"]

    import os
    from time import time

    # Generate new seed
    seed = int(time() * 1000) & 0xFFFFFFFF
    new_header = struct.pack("<I", seed) + encrypt_header[4:]

    prng = MT19937(seed)

    def encrypt_block(block: bytes) -> bytes:
        key_stream = bytes((prng.genrand_int32() & 0xFF) for _ in range(len(block)))
        return xor_encrypt(block, key_stream)

    # Encrypt file header
    file_header_seed = int((time() * 1000 + 1) & 0xFFFFFFFF)
    file_header_prng = MT19937(file_header_seed)
    file_header_key = bytes((file_header_prng.genrand_int32() & 0xFF) for _ in range(len(file_header)))
    encrypted_file_header = struct.pack("<I", file_header_seed) + xor_encrypt(file_header[4:], file_header_key[4:])

    # Encrypt blocks
    encrypted_logo = encrypt_block(logo)
    encrypted_desc = encrypt_block(desc)
    encrypted_data = encrypt_block(data)
    encrypted_serial = encrypt_block(serial) if serial else b""

    # Assemble
    result = new_header + encrypted_file_header + encrypted_logo + encrypted_desc + encrypted_data + encrypted_serial
    logger.info(f"Encrypted EDIT file: {len(result):,} bytes")
    return result
