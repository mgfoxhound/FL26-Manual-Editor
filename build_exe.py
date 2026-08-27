#!/usr/bin/env python3
"""Build standalone Windows EXE using PyInstaller.

Usage:
  python build_exe.py

Output:
  dist/FL26ManualEditor/FL26 Manual Editor.exe
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Build the standalone executable."""
    print("="*60)
    print("FL26 Manual Editor - Building Standalone Windows EXE")
    print("="*60)

    # Check PyInstaller
    try:
        import PyInstaller
        print("\n✅ PyInstaller found")
    except ImportError:
        print("\n❌ PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("\n✅ PyInstaller installed")

    # Build
    print("\nBuilding EXE...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "build_spec.spec",
            "--distpath", "./dist",
            "--buildpath", "./build",
            "-y",
        ],
        cwd=Path(__file__).parent,
    )

    if result.returncode == 0:
        print("\n" + "="*60)
        print("✅ BUILD SUCCESSFUL!")
        print("="*60)
        exe_path = Path("./dist/FL26ManualEditor/FL26 Manual Editor.exe")
        print(f"\nExecutable: {exe_path.resolve()}")
        print("\nTo run:")
        print(f"  1. Double-click: {exe_path.name}")
        print("  2. Drag EDIT00000000 onto the window")
        print("  3. Make changes")
        print("  4. Click 'Save As'")
        print("\nTo distribute:")
        print(f"  Zip the folder: dist/FL26ManualEditor/")
        print("="*60)
        return 0
    else:
        print("\n❌ Build failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
