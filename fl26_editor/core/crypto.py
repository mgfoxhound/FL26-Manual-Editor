"""pesXdecrypter wrapper for FL26 EDIT file encryption/decryption.

Handles the subprocess calls to decrypter21.exe and encrypter21.exe binaries.
The EDIT file structure (from pesXdecrypter):
  - Encryption header
  - File header
  - Thumbnail/logo
  - Description
  - data.dat (the actual game data we edit)
  - Version/serial string
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CryptoError(Exception):
    """Raised when decryption or encryption fails."""
    pass


def find_pesXdecrypter_binary(binary_name: str) -> Optional[Path]:
    """Find pesXdecrypter binary (decrypter21.exe or encrypter21.exe).

    Search order:
    1. ./vendor/pesXdecrypter/
    2. System PATH
    3. Common installation directories
    """
    # Check vendor directory first
    vendor_candidates = [
        Path("vendor/pesXdecrypter") / f"{binary_name}21.exe",
        Path("vendor/pesXdecrypter") / f"{binary_name}21",
        Path("vendor/pesXdecrypter") / binary_name,
    ]
    for candidate in vendor_candidates:
        if candidate.exists():
            logger.info(f"Found {binary_name} at {candidate}")
            return candidate

    # Check system PATH
    which_result = shutil.which(f"{binary_name}21.exe") or shutil.which(binary_name)
    if which_result:
        logger.info(f"Found {binary_name} in PATH: {which_result}")
        return Path(which_result)

    return None


def decrypt_edit_file(edit_file_path: Path) -> Path:
    """Decrypt an EDIT00000000 file into a temporary directory.

    Args:
        edit_file_path: Path to encrypted EDIT00000000 file.

    Returns:
        Path to temporary directory containing decrypted blocks.
        The actual game data is in <temp_dir>/data.dat

    Raises:
        CryptoError: If decryption fails.
        FileNotFoundError: If edit file or decrypter binary not found.
    """
    edit_file_path = Path(edit_file_path)
    if not edit_file_path.exists():
        raise FileNotFoundError(f"EDIT file not found: {edit_file_path}")

    decrypter = find_pesXdecrypter_binary("decrypter")
    if not decrypter:
        raise FileNotFoundError(
            "pesXdecrypter binary (decrypter21.exe) not found.\n"
            "Download from: https://github.com/the4chancup/pesXdecrypter/releases\n"
            "Place in: ./vendor/pesXdecrypter/ or add to PATH"
        )

    # Create temp directory for output
    temp_dir = Path(tempfile.mkdtemp(prefix="fl26_edit_dec_"))

    try:
        logger.info(f"Decrypting {edit_file_path} → {temp_dir}")
        result = subprocess.run(
            [str(decrypter), str(edit_file_path), str(temp_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise CryptoError(
                f"Decryption failed (exit code {result.returncode})\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        # Verify data.dat exists
        data_dat = temp_dir / "data.dat"
        if not data_dat.exists():
            raise CryptoError(
                f"Decryption produced no data.dat in {temp_dir}\n"
                f"Contents: {list(temp_dir.iterdir())}"
            )

        size = data_dat.stat().st_size
        logger.info(f"Decrypted successfully: data.dat ({size:,} bytes)")
        return temp_dir

    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise CryptoError("Decryption timed out after 60 seconds")
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def encrypt_edit_file(decrypted_dir: Path, output_path: Path) -> Path:
    """Re-encrypt decrypted blocks back into an EDIT file.

    Performs round-trip verification: decrypts the output to ensure
    encryption was successful before returning.

    Args:
        decrypted_dir: Directory containing decrypted blocks (from decrypt_edit_file).
        output_path: Where to write the encrypted EDIT file.

    Returns:
        Path to the encrypted file.

    Raises:
        CryptoError: If encryption or verification fails.
    """
    decrypted_dir = Path(decrypted_dir)
    output_path = Path(output_path)

    if not decrypted_dir.exists():
        raise FileNotFoundError(f"Decrypted directory not found: {decrypted_dir}")

    encrypter = find_pesXdecrypter_binary("encrypter")
    if not encrypter:
        raise FileNotFoundError(
            "pesXencrypter binary (encrypter21.exe) not found.\n"
            "Download from: https://github.com/the4chancup/pesXdecrypter/releases"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Use temp file to avoid partial writes
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    os.close(temp_fd)
    temp_output = Path(temp_name)
    verify_dir: Optional[Path] = None

    try:
        logger.info(f"Encrypting {decrypted_dir} → {output_path}")
        result = subprocess.run(
            [str(encrypter), str(decrypted_dir), str(temp_output)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise CryptoError(
                f"Encryption failed (exit code {result.returncode})\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        if not temp_output.exists() or temp_output.stat().st_size == 0:
            raise CryptoError(
                f"Encryption completed but output file invalid: {temp_output}"
            )

        # Round-trip verification: decrypt the output and compare blocks
        logger.info("Performing round-trip verification...")
        verify_dir = decrypt_edit_file(temp_output)

        block_names = (
            "encryptHeader.dat",
            "header.dat",
            "description.dat",
            "logo.png",
            "data.dat",
            "version.txt",
        )

        for block_name in block_names:
            source_block = decrypted_dir / block_name
            verified_block = verify_dir / block_name

            if not source_block.exists():
                continue  # Optional block

            if not verified_block.exists():
                raise CryptoError(f"Verification missing block: {block_name}")

            if source_block.read_bytes() != verified_block.read_bytes():
                raise CryptoError(f"Verification failed for block: {block_name}")

        # Atomic replace
        os.replace(temp_output, output_path)
        size = output_path.stat().st_size
        logger.info(f"Encrypted successfully: {output_path} ({size:,} bytes)")
        return output_path

    except subprocess.TimeoutExpired:
        raise CryptoError("Encryption timed out after 60 seconds")
    finally:
        if verify_dir is not None:
            shutil.rmtree(verify_dir, ignore_errors=True)
        if temp_output.exists():
            temp_output.unlink()


def cleanup_temp(temp_dir: Path) -> None:
    """Remove a temporary decryption directory."""
    if temp_dir and temp_dir.exists() and "fl26_edit_dec_" in str(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.debug(f"Cleaned up temp: {temp_dir}")
