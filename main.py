"""Standalone FL26 Manual Editor - Main application entry point.

No Python, pip, or external setup required. Just run the EXE.
"""

import logging
import sys
from pathlib import Path

# Configure logging
log_dir = Path.home() / ".fl26_editor"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "editor.log"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from fl26_editor.ui.main_window import FL26EditorMainWindow
except ImportError as e:
    print(f"Fatal: Missing required module: {e}")
    print("This is a standalone Windows executable and should not be missing dependencies.")
    sys.exit(1)


def main():
    """Launch the FL26 Manual Editor."""
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("FL26 Manual Editor")
        app.setApplicationVersion("1.0.0")

        window = FL26EditorMainWindow()
        window.show()

        logger.info("FL26 Manual Editor started")
        sys.exit(app.exec())
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        print(f"\nFATAL ERROR: {e}")
        input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
