#!/usr/bin/env python3
"""Entry point for FL26 Manual Editor."""

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from fl26_editor.ui.main_window import FL26EditorMainWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(Path.home() / ".fl26_editor" / "editor.log"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


def main():
    """Launch the application."""
    app = QApplication(sys.argv)
    app.setApplicationName("FL26 Manual Editor")
    app.setApplicationVersion("0.1.0")

    window = FL26EditorMainWindow()
    window.show()

    logger.info("Application started")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
