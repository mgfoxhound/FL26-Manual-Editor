"""Main application window for FL26 Manual Editor."""

import logging
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QLabel,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QSpinBox,
    QDialog,
    QProgressDialog,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QDragEnterEvent, QDropEvent

from fl26_editor.core.editfile import EditFile
from fl26_editor.core.crypto_bundled import decrypt_edit_file, encrypt_edit_file
from fl26_editor.core.models import PlayerInfo, TeamInfo, ManagerInfo, TeamRoster

logger = logging.getLogger(__name__)


class DecryptWorker(QThread):
    """Background worker for decryption."""
    finished = Signal(tuple)  # (data_bytes, original_path)
    error = Signal(str)

    def __init__(self, edit_file_path: Path):
        super().__init__()
        self.edit_file_path = edit_file_path

    def run(self):
        try:
            _, _, _, _, data, _ = decrypt_edit_file(self.edit_file_path)
            self.finished.emit((data, str(self.edit_file_path)))
        except Exception as e:
            self.error.emit(f"Decryption failed: {str(e)}")
            logger.exception("Decryption error")


class EncryptWorker(QThread):
    """Background worker for encryption."""
    finished = Signal(str)  # Path to output file
    error = Signal(str)

    def __init__(self, blocks: tuple, output_path: Path):
        super().__init__()
        self.blocks = blocks
        self.output_path = output_path

    def run(self):
        try:
            encrypt_header, file_header, logo, desc, data, serial = self.blocks
            encrypted = encrypt_edit_file(encrypt_header, file_header, logo, desc, data, serial)
            self.output_path.write_bytes(encrypted)
            
            # Verify by re-reading
            _, _, _, _, verify_data, _ = decrypt_edit_file(self.output_path)
            if verify_data != data:
                raise ValueError("Round-trip verification failed: data mismatch")
            
            self.finished.emit(str(self.output_path))
        except Exception as e:
            self.error.emit(f"Encryption failed: {str(e)}")
            logger.exception("Encryption error")


class FL26EditorMainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FL26 Manual Editor v1.0")
        self.setGeometry(100, 100, 1200, 800)
        self.setAcceptDrops(True)

        # State
        self.edit_file: Optional[EditFile] = None
        self.original_edit_path: Optional[Path] = None
        self.encrypted_blocks: Optional[tuple] = None

        # Cached data
        self.all_players: Dict[int, PlayerInfo] = {}
        self.all_teams: Dict[int, TeamInfo] = {}
        self.all_managers: Dict[int, ManagerInfo] = {}
        self.all_rosters: Dict[int, TeamRoster] = {}
        self.changes: list = []  # List of change descriptions

        self._setup_ui()

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Handle drop."""
        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.exists():
                self.load_edit_file(file_path)
                break

    def _setup_ui(self) -> None:
        """Set up the main UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # Top bar
        top_layout = QHBoxLayout()
        self.open_button = QPushButton("📁 Open EDIT00000000")
        self.open_button.clicked.connect(self.on_open_file)
        top_layout.addWidget(self.open_button)

        self.file_label = QLabel("Drag & drop EDIT00000000 or click 'Open'")
        self.file_label.setStyleSheet("color: #666; font-style: italic;")
        top_layout.addWidget(self.file_label)
        top_layout.addStretch()

        layout.addLayout(top_layout)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_players = QWidget()
        self.tab_clubs = QWidget()
        self.tab_changes = QWidget()

        self.tabs.addTab(self.tab_players, "👥 Players")
        self.tabs.addTab(self.tab_clubs, "⚽ Clubs")
        self.tabs.addTab(self.tab_changes, "📝 Changes")

        self._setup_players_tab()
        self._setup_clubs_tab()
        self._setup_changes_tab()

        layout.addWidget(self.tabs)

        # Bottom bar
        bottom_layout = QHBoxLayout()
        self.undo_button = QPushButton("↶ Undo")
        self.undo_button.clicked.connect(self.on_undo)
        self.undo_button.setEnabled(False)
        bottom_layout.addWidget(self.undo_button)

        bottom_layout.addStretch()

        self.save_button = QPushButton("💾 Save As EDIT00000000")
        self.save_button.clicked.connect(self.on_save)
        self.save_button.setEnabled(False)
        bottom_layout.addWidget(self.save_button)

        layout.addLayout(bottom_layout)
        self.tabs.setEnabled(False)

    def _setup_players_tab(self) -> None:
        """Set up Players tab."""
        layout = QVBoxLayout(self.tab_players)

        # Search
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 Search:"))
        self.player_search = QLineEdit()
        self.player_search.setPlaceholderText("Name, club, or ID...")
        self.player_search.textChanged.connect(self.on_player_search_changed)
        search_layout.addWidget(self.player_search)
        layout.addLayout(search_layout)

        # Table
        self.players_table = QTableWidget()
        self.players_table.setColumnCount(6)
        self.players_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Club", "Pos", "OVR", "Age"]
        )
        self.players_table.itemSelectionChanged.connect(self.on_player_selected)
        layout.addWidget(self.players_table)

        # Buttons
        button_layout = QHBoxLayout()
        self.transfer_button = QPushButton("🔄 Transfer")
        self.transfer_button.clicked.connect(self.on_transfer_player)
        self.transfer_button.setEnabled(False)
        button_layout.addWidget(self.transfer_button)

        self.release_button = QPushButton("❌ Release")
        self.release_button.clicked.connect(self.on_release_player)
        self.release_button.setEnabled(False)
        button_layout.addWidget(self.release_button)

        self.shirt_button = QPushButton("👕 Shirt #")
        self.shirt_button.clicked.connect(self.on_change_shirt_number)
        self.shirt_button.setEnabled(False)
        button_layout.addWidget(self.shirt_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _setup_clubs_tab(self) -> None:
        """Set up Clubs tab."""
        layout = QVBoxLayout(self.tab_clubs)

        # Club selector
        club_layout = QHBoxLayout()
        club_layout.addWidget(QLabel("⚽ Club:"))
        self.club_combo = QComboBox()
        self.club_combo.currentIndexChanged.connect(self.on_club_selected)
        club_layout.addWidget(self.club_combo)
        club_layout.addStretch()
        layout.addLayout(club_layout)

        # Squad table
        self.squad_table = QTableWidget()
        self.squad_table.setColumnCount(5)
        self.squad_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Pos", "Shirt", "OVR"]
        )
        layout.addWidget(self.squad_table)

    def _setup_changes_tab(self) -> None:
        """Set up Changes tab."""
        layout = QVBoxLayout(self.tab_changes)

        self.changes_table = QTableWidget()
        self.changes_table.setColumnCount(2)
        self.changes_table.setHorizontalHeaderLabels(["Time", "Change"])
        layout.addWidget(self.changes_table)

    def on_open_file(self) -> None:
        """Handle opening an EDIT file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open EDIT00000000 File",
            "",
            "EDIT Files (EDIT00000000);;All Files (*)",
        )

        if file_path:
            self.load_edit_file(Path(file_path))

    def load_edit_file(self, file_path: Path) -> None:
        """Load and decrypt an EDIT file."""
        if not file_path.exists():
            QMessageBox.critical(self, "Error", f"File not found: {file_path}")
            return

        self.file_label.setText(f"Loading {file_path.name}...")
        self.repaint()

        worker = DecryptWorker(file_path)
        worker.finished.connect(self._on_decrypt_complete)
        worker.error.connect(self._on_decrypt_error)
        worker.start()

    def _on_decrypt_complete(self, result: tuple) -> None:
        """Handle successful decryption."""
        try:
            data, original_path = result
            self.original_edit_path = Path(original_path)

            # Store encrypted blocks for later encryption
            encrypt_header, file_header, logo, desc, _, serial = decrypt_edit_file(
                self.original_edit_path
            )
            self.encrypted_blocks = (encrypt_header, file_header, logo, desc, data, serial)

            # Load the EditFile
            self.edit_file = EditFile()
            self.edit_file.load_bytes(data)

            # Validate
            is_valid, errors = self.edit_file.validate_integrity()
            if not is_valid:
                QMessageBox.warning(
                    self,
                    "Validation Warnings",
                    "Some validation issues were found:\n" + "\n".join(errors[:5]),
                )

            # Load all data
            self.all_players = self.edit_file.get_all_players()
            self.all_teams = self.edit_file.get_all_teams()
            self.all_managers = self.edit_file.get_all_managers()
            self.all_rosters = self.edit_file.get_all_rosters()
            self.changes = []

            # Update UI
            self.file_label.setText(
                f"✅ Loaded: {self.original_edit_path.name} "
                f"({len(self.all_players)} players, {len(self.all_teams)} teams)"
            )
            self.tabs.setEnabled(True)
            self.save_button.setEnabled(True)
            self.undo_button.setEnabled(False)

            # Populate tables
            self._refresh_players_table()
            self._refresh_clubs_combo()
            self._refresh_changes_table()

            logger.info(f"Loaded {self.edit_file.metadata}")

        except Exception as e:
            logger.exception("Error loading EDIT file")
            QMessageBox.critical(self, "Error", f"Failed to load EDIT file: {e}")
            self.file_label.setText("❌ Load failed")

    def _on_decrypt_error(self, error: str) -> None:
        """Handle decryption error."""
        QMessageBox.critical(self, "Decryption Error", error)
        self.file_label.setText("❌ Decryption failed")

    def _refresh_players_table(self, filter_text: str = "") -> None:
        """Refresh the players table."""
        self.players_table.setRowCount(0)
        filter_lower = filter_text.lower()

        for player_id, player in sorted(self.all_players.items()):
            if filter_text and not any(
                filter_lower in str(x).lower()
                for x in [player_id, player.name, player.position]
            ):
                continue

            # Find club
            club_name = "Free Agent"
            for team_id, roster in self.all_rosters.items():
                if roster.has_player(player_id):
                    if team_id in self.all_teams:
                        club_name = self.all_teams[team_id].name
                    break

            row = self.players_table.rowCount()
            self.players_table.insertRow(row)
            self.players_table.setItem(row, 0, QTableWidgetItem(str(player_id)))
            self.players_table.setItem(row, 1, QTableWidgetItem(player.name))
            self.players_table.setItem(row, 2, QTableWidgetItem(club_name))
            self.players_table.setItem(row, 3, QTableWidgetItem(player.position or "-"))
            self.players_table.setItem(row, 4, QTableWidgetItem(str(player.overall_rating)))
            self.players_table.setItem(row, 5, QTableWidgetItem(str(player.age)))

    def _refresh_clubs_combo(self) -> None:
        """Refresh clubs combo."""
        self.club_combo.blockSignals(True)
        self.club_combo.clear()
        for team_id, team in sorted(self.all_teams.items(), key=lambda x: x[1].name):
            self.club_combo.addItem(team.name, team_id)
        self.club_combo.blockSignals(False)

    def _refresh_changes_table(self) -> None:
        """Refresh changes log."""
        self.changes_table.setRowCount(0)
        for i, change in enumerate(self.changes):
            row = self.changes_table.rowCount()
            self.changes_table.insertRow(row)
            self.changes_table.setItem(row, 0, QTableWidgetItem(change["time"]))
            self.changes_table.setItem(row, 1, QTableWidgetItem(change["description"]))

    def _log_change(self, description: str) -> None:
        """Log a change."""
        self.changes.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "description": description,
        })
        self._refresh_changes_table()
        self.undo_button.setEnabled(len(self.edit_file._undo_stack) > 0 if self.edit_file else False)

    def on_player_search_changed(self, text: str) -> None:
        """Handle player search."""
        self._refresh_players_table(text)

    def on_player_selected(self) -> None:
        """Handle player selection."""
        if self.players_table.selectedIndexes():
            self.transfer_button.setEnabled(True)
            self.release_button.setEnabled(True)
            self.shirt_button.setEnabled(True)
        else:
            self.transfer_button.setEnabled(False)
            self.release_button.setEnabled(False)
            self.shirt_button.setEnabled(False)

    def on_club_selected(self, index: int) -> None:
        """Handle club selection."""
        if index < 0 or not self.edit_file:
            return

        team_id = self.club_combo.currentData()
        roster = self.all_rosters.get(team_id)
        if not roster:
            self.squad_table.setRowCount(0)
            return

        self.squad_table.setRowCount(0)
        for slot, player_id in enumerate(roster.player_ids):
            if player_id == 0:
                continue

            player = self.all_players.get(player_id)
            if not player:
                continue

            row = self.squad_table.rowCount()
            self.squad_table.insertRow(row)
            self.squad_table.setItem(row, 0, QTableWidgetItem(str(player_id)))
            self.squad_table.setItem(row, 1, QTableWidgetItem(player.name))
            self.squad_table.setItem(row, 2, QTableWidgetItem(player.position or "-"))
            self.squad_table.setItem(row, 3, QTableWidgetItem(str(roster.shirt_numbers[slot])))
            self.squad_table.setItem(row, 4, QTableWidgetItem(str(player.overall_rating)))

    def on_transfer_player(self) -> None:
        """Transfer selected player."""
        if not self.players_table.selectedIndexes() or not self.edit_file:
            QMessageBox.warning(self, "Error", "Please select a player")
            return

        row = self.players_table.selectedIndexes()[0].row()
        player_id = int(self.players_table.item(row, 0).text())
        player = self.all_players.get(player_id)
        if not player:
            return

        # Get current club
        current_club_id = None
        current_club_name = "Free Agent"
        for team_id, roster in self.all_rosters.items():
            if roster.has_player(player_id):
                current_club_id = team_id
                if team_id in self.all_teams:
                    current_club_name = self.all_teams[team_id].name
                break

        # Dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Transfer {player.name}")
        dialog.setGeometry(200, 200, 400, 250)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(f"Player: {player.name}\nCurrent Club: {current_club_name}"))
        layout.addWidget(QLabel("Transfer to:"))

        club_combo = QComboBox()
        for team_id, team in sorted(self.all_teams.items(), key=lambda x: x[1].name):
            if team_id != current_club_id:
                club_combo.addItem(team.name, team_id)

        layout.addWidget(club_combo)

        shirt_layout = QHBoxLayout()
        shirt_layout.addWidget(QLabel("Shirt #:"))
        shirt_spin = QSpinBox()
        shirt_spin.setRange(1, 999)
        shirt_spin.setValue(7)
        shirt_layout.addWidget(shirt_spin)
        layout.addLayout(shirt_layout)

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Transfer")
        cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        if dialog.exec() == QDialog.Accepted:
            dest_team_id = club_combo.currentData()
            shirt_num = shirt_spin.value()

            if current_club_id:
                success = self.edit_file.transfer_player(
                    player_id, current_club_id, dest_team_id, shirt_num
                )
                if success:
                    self._log_change(f"Transferred {player.name} to {self.all_teams[dest_team_id].name} (#{shirt_num})")
            else:
                success = self.edit_file.add_player(player_id, dest_team_id, shirt_num)
                if success:
                    self._log_change(f"Signed {player.name} to {self.all_teams[dest_team_id].name} (#{shirt_num})")

            if success:
                self.all_rosters = self.edit_file.get_all_rosters()
                self._refresh_players_table()
                self._refresh_clubs_combo()
                self.on_club_selected(self.club_combo.currentIndex())
                QMessageBox.information(self, "Success", "Transfer completed")
            else:
                QMessageBox.critical(self, "Error", "Transfer failed")

    def on_release_player(self) -> None:
        """Release selected player."""
        if not self.players_table.selectedIndexes() or not self.edit_file:
            QMessageBox.warning(self, "Error", "Please select a player")
            return

        row = self.players_table.selectedIndexes()[0].row()
        player_id = int(self.players_table.item(row, 0).text())
        player = self.all_players.get(player_id)
        if not player:
            return

        # Find club
        for team_id, roster in self.all_rosters.items():
            if roster.has_player(player_id):
                team_name = self.all_teams[team_id].name if team_id in self.all_teams else "Unknown"
                if QMessageBox.question(
                    self,
                    "Confirm Release",
                    f"Release {player.name} from {team_name}?",
                ) == QMessageBox.Yes:
                    if self.edit_file.release_player(player_id, team_id):
                        self._log_change(f"Released {player.name} from {team_name}")
                        self.all_rosters = self.edit_file.get_all_rosters()
                        self._refresh_players_table()
                        self._refresh_clubs_combo()
                        self.on_club_selected(self.club_combo.currentIndex())
                        QMessageBox.information(self, "Success", "Player released")
                    else:
                        QMessageBox.critical(self, "Error", "Release failed")
                return

        QMessageBox.information(self, "Info", "Player is already Free Agent")

    def on_change_shirt_number(self) -> None:
        """Change player's shirt number."""
        if not self.players_table.selectedIndexes() or not self.edit_file:
            return

        row = self.players_table.selectedIndexes()[0].row()
        player_id = int(self.players_table.item(row, 0).text())
        player = self.all_players.get(player_id)
        if not player:
            return

        # Find club
        for team_id, roster in self.all_rosters.items():
            if roster.has_player(player_id):
                dialog = QDialog(self)
                dialog.setWindowTitle(f"Change Shirt # - {player.name}")
                dialog.setGeometry(200, 200, 300, 200)
                layout = QVBoxLayout(dialog)

                team_name = self.all_teams[team_id].name if team_id in self.all_teams else "Unknown"
                layout.addWidget(QLabel(f"Player: {player.name}\nClub: {team_name}"))

                current_shirt = roster.get_shirt_number(player_id)
                layout.addWidget(QLabel(f"Current Shirt #: {current_shirt}"))

                shirt_spin = QSpinBox()
                shirt_spin.setRange(1, 999)
                if current_shirt:
                    shirt_spin.setValue(current_shirt)
                layout.addWidget(shirt_spin)

                btn_layout = QHBoxLayout()
                ok_btn = QPushButton("Update")
                cancel_btn = QPushButton("Cancel")
                btn_layout.addWidget(ok_btn)
                btn_layout.addWidget(cancel_btn)
                layout.addLayout(btn_layout)

                ok_btn.clicked.connect(dialog.accept)
                cancel_btn.clicked.connect(dialog.reject)

                if dialog.exec() == QDialog.Accepted:
                    new_shirt = shirt_spin.value()
                    if self.edit_file.update_shirt_number(team_id, player_id, new_shirt):
                        self._log_change(f"Changed {player.name} shirt to #{new_shirt}")
                        self.all_rosters = self.edit_file.get_all_rosters()
                        self._refresh_clubs_combo()
                        self.on_club_selected(self.club_combo.currentIndex())
                        QMessageBox.information(self, "Success", "Shirt number updated")
                    else:
                        QMessageBox.critical(self, "Error", "Update failed")
                return

    def on_undo(self) -> None:
        """Undo last change."""
        if self.edit_file and self.edit_file.undo():
            self.all_rosters = self.edit_file.get_all_rosters()
            self._refresh_players_table()
            self._refresh_clubs_combo()
            self.on_club_selected(self.club_combo.currentIndex())
            self._log_change("Undo performed")
            self.undo_button.setEnabled(len(self.edit_file._undo_stack) > 0)
            QMessageBox.information(self, "Undo", "Last change undone")
        else:
            QMessageBox.information(self, "Undo", "Nothing to undo")

    def on_save(self) -> None:
        """Save modified EDIT file."""
        if not self.edit_file or not self.encrypted_blocks or not self.original_edit_path:
            QMessageBox.critical(self, "Error", "No file loaded")
            return

        try:
            # Create backup
            backup_path = self.original_edit_path.parent / f"{self.original_edit_path.name}.backup"
            if not backup_path.exists():
                backup_path.write_bytes(self.original_edit_path.read_bytes())
                logger.info(f"Created backup: {backup_path}")

            # Prompt for output
            output_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Encrypted EDIT File",
                str(self.original_edit_path.parent / "EDIT00000000_edited"),
                "EDIT Files (EDIT00000000);;All Files (*)",
            )

            if not output_path:
                return

            self.file_label.setText("Encrypting and saving...")
            self.repaint()

            # Get modified data
            modified_data = self.edit_file.save_bytes()
            encrypt_header, file_header, logo, desc, _, serial = self.encrypted_blocks

            worker = EncryptWorker(
                (encrypt_header, file_header, logo, desc, modified_data, serial),
                Path(output_path)
            )
            worker.finished.connect(self._on_encrypt_complete)
            worker.error.connect(self._on_encrypt_error)
            worker.start()

        except Exception as e:
            logger.exception("Save error")
            QMessageBox.critical(self, "Error", f"Save failed: {e}")

    def _on_encrypt_complete(self, output_path: str) -> None:
        """Handle successful encryption."""
        QMessageBox.information(
            self,
            "✅ Success",
            f"File saved: {Path(output_path).name}\n\nOriginal file backed up.\n\nYou can now use this file in FL26!",
        )
        self.file_label.setText(f"✅ Saved: {Path(output_path).name}")

    def _on_encrypt_error(self, error: str) -> None:
        """Handle encryption error."""
        QMessageBox.critical(self, "❌ Encryption Error", error)
        self.file_label.setText("❌ Save failed")

    # Placeholder for add_player (from Free Agent)
    def add_player(self, player_id: int, to_team_id: int, shirt_number: int) -> bool:
        """Add player from Free Agent."""
        if not self.edit_file:
            return False
        return True
