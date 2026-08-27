"""Build configuration for PyInstaller.

This file contains settings for creating a standalone Windows executable.
"""

import os
import sys
from pathlib import Path

# Determine if running as frozen executable
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    APPLICATION_PATH = Path(sys.executable).parent
else:
    # Running as Python script
    APPLICATION_PATH = Path(__file__).parent

DEBUG = False
APP_NAME = "FL26 Manual Editor"
APP_VERSION = "1.0.0"
