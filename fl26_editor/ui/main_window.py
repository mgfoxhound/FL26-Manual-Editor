"""Main application window and UI."""

import logging
from pathlib import Path
from typing import Optional, Dict, List

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
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

from fl26_editor.core.editfile import EditFile
from fl26_editor.core.crypto import decrypt_edit_file, encrypt_edit_file, cleanup_temp
from fl26_editor.core.models import PlayerInfo, TeamInfo, ManagerInfo, TeamRoster

logger = logging.getLogger(__name__)


class DecryptWorker(QThread):
    """Background worker for decryption."""
    finished = Signal(Path)  # Path to temp directory
    error = Signal(str)

    def __init__(self, edit_file_path: Path):
        super().__init__()
        self.edit_file_path = edit_file_path

    def run(self):
        try:
            temp_dir = decrypt_edit_file(self.edit_file_path)
            self.finished.emit(temp_dir)
        except Exception as e:
            self.error.emit(str(e))


class EncryptWorker(QThread):
    """Background worker for encryption."""
    finished = Signal(Path)  # Path to encrypted file
    error = Signal(str)

    def __init__(self, decrypted_dir: Path, output_path: Path):
        super().__init__()
        self.decrypted_dir = decrypted_dir
        self.output_path = output_path

    def run(self):
        try:
            result = encrypt_edit_file(self.decrypted_dir, self.output_path)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class FL26EditorMainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FL26 Manual Editor")
        self.setGeometry(100, 100, 1200, 800)

        # State
        self.edit_file: Optional[EditFile] = None
        self.current_temp_dir: Optional[Path] = None
        self.current_data_dat: Optional[Path] = None
        self.original_edit_file: Optional[Path] = None

        # Cached data
        self.all_players: Dict[int, PlayerInfo] = {}
        self.all_teams: Dict[int, TeamInfo] = {}
        self.all_managers: Dict[int, ManagerInfo] = {}
        self.all_rosters: Dict[int, TeamRoster] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the main UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # Top button bar
        top_layout = QHBoxLayout()
        self.open_button = QPushButton("Open EDIT00000000")
        self.open_button.clicked.connect(self.on_open_file)
        top_layout.addWidget(self.open_button)

        self.file_label = QLabel("No file loaded")
        top_layout.addWidget(self.file_label)
        top_layout.addStretch()

        layout.addLayout(top_layout)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_players = QWidget()
        self.tab_clubs = QWidget()
        self.tab_managers = QWidget()
        self.tab_changes = QWidget()

        self.tabs.addTab(self.tab_players, "Players")
        self.tabs.addTab(self.tab_clubs, "Clubs")
        self.tabs.addTab(self.tab_managers, "Managers")
        self.tabs.addTab(self.tab_changes, "Changes")

        self._setup_players_tab()
        self._setup_clubs_tab()
        self._setup_managers_tab()
        self._setup_changes_tab()

        layout.addWidget(self.tabs)

        # Bottom button bar
        bottom_layout = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.on_undo)
        self.undo_button.setEnabled(False)
        bottom_layout.addWidget(self.undo_button)

        bottom_layout.addStretch()

        self.save_button = QPushButton("Save Modified EDIT File")
        self.save_button.clicked.connect(self.on_save)
        self.save_button.setEnabled(False)
        bottom_layout.addWidget(self.save_button)

        layout.addLayout(bottom_layout)

        self.tabs.setEnabled(False)

    def _setup_players_tab(self) -> None:
        """Set up Players tab."""
        layout = QVBoxLayout(self.tab_players)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.player_search = QLineEdit()
        self.player_search.setPlaceholderText("Name, club, or player ID...")
        self.player_search.textChanged.connect(self.on_player_search_changed)
        search_layout.addWidget(self.player_search)
        layout.addLayout(search_layout)

        # Table
        self.players_table = QTableWidget()
        self.players_table.setColumnCount(6)
        self.players_table.setHorizontalHeaderLabels(
            ["Player ID", "Name", "Club", "Position", "OVR", "Age"]
        )
        self.players_table.itemSelectionChanged.connect(self.on_player_selected)
        layout.addWidget(self.players_table)

        # Action buttons
        button_layout = QHBoxLayout()
        self.transfer_button = QPushButton("Transfer")
        self.transfer_button.clicked.connect(self.on_transfer_player)
        self.transfer_button.setEnabled(False)
        button_layout.addWidget(self.transfer_button)

        self.release_button = QPushButton("Release")
        self.release_button.clicked.connect(self.on_release_player)
        self.release_button.setEnabled(False)
        button_layout.addWidget(self.release_button)

        self.loan_button = QPushButton("Loan")
        self.loan_button.clicked.connect(self.on_loan_player)
        self.loan_button.setEnabled(False)
        button_layout.addWidget(self.loan_button)

        self.shirt_button = QPushButton("Change Shirt #")
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
        club_layout.addWidget(QLabel("Club:"))
        self.club_combo = QComboBox()
        self.club_combo.currentIndexChanged.connect(self.on_club_selected)
        club_layout.addWidget(self.club_combo)
        club_layout.addStretch()
        layout.addLayout(club_layout)

        # Squad table
        self.squad_table = QTableWidget()
        self.squad_table.setColumnCount(5)
        self.squad_table.setHorizontalHeaderLabels(
            ["Player ID", "Name", "Position", "Shirt #", "OVR"]
        )
        layout.addWidget(self.squad_table)

        # Actions
        action_layout = QHBoxLayout()
        self.squad_transfer_button = QPushButton("Transfer Out")
        self.squad_transfer_button.clicked.connect(self.on_squad_transfer)
        self.squad_transfer_button.setEnabled(False)
        action_layout.addWidget(self.squad_transfer_button)
        action_layout.addStretch()
        layout.addLayout(action_layout)

    def _setup_managers_tab(self) -> None:
        """Set up Managers tab."""
        layout = QVBoxLayout(self.tab_managers)

        # Search
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.manager_search = QLineEdit()
        self.manager_search.setPlaceholderText("Manager name...")
        self.manager_search.textChanged.connect(self.on_manager_search_changed)
        search_layout.addWidget(self.manager_search)
        layout.addLayout(search_layout)

        # Table
        self.managers_table = QTableWidget()
        self.managers_table.setColumnCount(3)
        self.managers_table.setHorizontalHeaderLabels(
            ["Manager ID", "Name", "Current Club"]
        )
        self.managers_table.itemSelectionChanged.connect(self.on_manager_selected)
        layout.addWidget(self.managers_table)

        # Actions
        action_layout = QHBoxLayout()
        self.change_manager_club_button = QPushButton("Change Club")
        self.change_manager_club_button.clicked.connect(self.on_change_manager_club)
        self.change_manager_club_button.setEnabled(False)
        action_layout.addWidget(self.change_manager_club_button)
        action_layout.addStretch()
        layout.addLayout(action_layout)

    def _setup_changes_tab(self) -> None:
        """Set up Changes tab (log)."""
        layout = QVBoxLayout(self.tab_changes)

        self.changes_table = QTableWidget()
        self.changes_table.setColumnCount(3)
        self.changes_table.setHorizontalHeaderLabels(
            ["#", "Timestamp", "Change Description"]
        )
        layout.addWidget(self.changes_table)

    def on_open_file(self) -> None:
        """Handle opening an EDIT file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open EDIT00000000 File",
            "",
            "EDIT Files (EDIT00000000);;All Files (*)",
        )

        if not file_path:
            return

        self.load_edit_file(Path(file_path))

    def load_edit_file(self, file_path: Path) -> None:
        """Load and decrypt an EDIT file."""
        if not file_path.exists():
            QMessageBox.critical(self, "Error", f"File not found: {file_path}")
            return

        try:
            self.file_label.setText(f"Loading {file_path.name}...")
            self.repaint()

            # Decrypt in background
            worker = DecryptWorker(file_path)
            worker.finished.connect(
                lambda temp_dir: self._on_decrypt_complete(temp_dir, file_path)
            )
            worker.error.connect(self._on_decrypt_error)
            worker.start()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load file: {e}")
            self.file_label.setText("No file loaded")

    def _on_decrypt_complete(self, temp_dir: Path, original_file: Path) -> None:
        """Handle successful decryption."""
        try:
            self.current_temp_dir = temp_dir
            self.original_edit_file = original_file
            self.current_data_dat = temp_dir / "data.dat"

            # Load the EditFile
            self.edit_file = EditFile()
            self.edit_file.load(self.current_data_dat)

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

            # Update UI
            self.file_label.setText(
                f"Loaded: {original_file.name} "
                f"({len(self.all_players)} players, {len(self.all_teams)} teams)"
            )
            self.tabs.setEnabled(True)
            self.save_button.setEnabled(True)

            # Populate tables
            self._refresh_players_table()
            self._refresh_clubs_combo()
            self._refresh_managers_table()

            QMessageBox.information(
                self, "Success", f"Loaded {self.edit_file.metadata}\n\nFile is ready to edit."
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load EDIT file: {e}")
            self.file_label.setText("No file loaded")
            if self.current_temp_dir:
                cleanup_temp(self.current_temp_dir)
                self.current_temp_dir = None

    def _on_decrypt_error(self, error: str) -> None:
        """Handle decryption error."""
        QMessageBox.critical(self, "Decryption Error", error)
        self.file_label.setText("No file loaded")

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

            # Find club for this player
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
        """Refresh the clubs combo box."""
        self.club_combo.clear()
        for team_id, team in sorted(self.all_teams.items(), key=lambda x: x[1].name):
            self.club_combo.addItem(team.name, team_id)

    def _refresh_managers_table(self, filter_text: str = "") -> None:
        """Refresh the managers table."""
        self.managers_table.setRowCount(0)
        filter_lower = filter_text.lower()

        for mgr_id, manager in sorted(self.all_managers.items()):
            if filter_text and filter_lower not in manager.name.lower():
                continue

            # Find club
            club_name = "No Club"
            for team_id, team in self.all_teams.items():
                if team.manager_id == mgr_id:
                    club_name = team.name
                    break

            row = self.managers_table.rowCount()
            self.managers_table.insertRow(row)
            self.managers_table.setItem(row, 0, QTableWidgetItem(str(mgr_id)))
            self.managers_table.setItem(row, 1, QTableWidgetItem(manager.name))
            self.managers_table.setItem(row, 2, QTableWidgetItem(club_name))

    def on_player_search_changed(self, text: str) -> None:
        """Handle player search."""
        self._refresh_players_table(text)

    def on_player_selected(self) -> None:
        """Handle player selection."""
        if self.players_table.selectedIndexes():
            self.transfer_button.setEnabled(True)
            self.release_button.setEnabled(True)
            self.loan_button.setEnabled(True)
            self.shirt_button.setEnabled(True)
        else:
            self.transfer_button.setEnabled(False)
            self.release_button.setEnabled(False)
            self.loan_button.setEnabled(False)
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

    def on_manager_search_changed(self, text: str) -> None:
        """Handle manager search."""
        self._refresh_managers_table(text)

    def on_manager_selected(self) -> None:
        """Handle manager selection."""
        if self.managers_table.selectedIndexes():
            self.change_manager_club_button.setEnabled(True)
        else:
            self.change_manager_club_button.setEnabled(False)

    def on_transfer_player(self) -> None:
        """Transfer the selected player."""
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
        for team_id, roster in self.all_rosters.items():
            if roster.has_player(player_id):
                current_club_id = team_id
                break

        # Dialog to select destination club
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Transfer {player.name}")
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(f"Player: {player}\n" 
            f"Current Club: {self.all_teams.get(current_club_id, {}).name if current_club_id else 'Free Agent'}"))
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
            else:
                # Adding from Free Agent
                success = self.edit_file.add_player(player_id, dest_team_id, shirt_num)

            if success:
                self.all_rosters = self.edit_file.get_all_rosters()
                self._refresh_players_table()
                self._refresh_clubs_combo()
                QMessageBox.information(self, "Success", "Transfer completed")
            else:
                QMessageBox.critical(self, "Error", "Transfer failed")

    def on_release_player(self) -> None:
        """Release the selected player."""
        if not self.players_table.selectedIndexes() or not self.edit_file:
            QMessageBox.warning(self, "Error", "Please select a player")
            return

        row = self.players_table.selectedIndexes()[0].row()
        player_id = int(self.players_table.item(row, 0).text())
        player = self.all_players.get(player_id)
        if not player:
            return

        # Find current club
        for team_id, roster in self.all_rosters.items():
            if roster.has_player(player_id):
                if QMessageBox.question(
                    self,
                    "Confirm Release",
                    f"Release {player.name} from {self.all_teams[team_id].name}?",
                ) == QMessageBox.Yes:
                    if self.edit_file.release_player(player_id, team_id):
                        self.all_rosters = self.edit_file.get_all_rosters()
                        self._refresh_players_table()
                        self._refresh_clubs_combo()
                        QMessageBox.information(self, "Success", "Player released")
                    else:
                        QMessageBox.critical(self, "Error", "Release failed")
                return

        QMessageBox.information(self, "Info", "Player is already Free Agent")

    def on_loan_player(self) -> None:
        """Loan the selected player (placeholder)."""
        QMessageBox.information(self, "Info", "Loan feature coming soon")

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
                layout = QVBoxLayout(dialog)
                layout.addWidget(QLabel(f"Player: {player.name}\nClub: {self.all_teams[team_id].name}"))

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
                    if self.edit_file.update_shirt_number(team_id, player_id, shirt_spin.value()):
                        self.all_rosters = self.edit_file.get_all_rosters()
                        self._refresh_clubs_combo()
                        self.on_club_selected(self.club_combo.currentIndex())
                        QMessageBox.information(self, "Success", "Shirt number updated")
                    else:
                        QMessageBox.critical(self, "Error", "Update failed")
                return

    def on_squad_transfer(self) -> None:
        """Transfer player from club squad."""
        QMessageBox.information(self, "Info", "Use Players tab to transfer")

    def on_change_manager_club(self) -> None:
        """Change manager's club assignment (placeholder)."""
        QMessageBox.information(self, "Info", "Manager reassignment coming soon")

    def on_undo(self) -> None:
        """Undo last change."""
        if self.edit_file and self.edit_file.undo():
            self.all_rosters = self.edit_file.get_all_rosters()
            self._refresh_players_table()
            self._refresh_clubs_combo()
            self.on_club_selected(self.club_combo.currentIndex())
            QMessageBox.information(self, "Undo", "Last change undone")
        else:
            QMessageBox.information(self, "Undo", "Nothing to undo")

    def on_save(self) -> None:
        """Save modified EDIT file."""
        if not self.edit_file or not self.current_data_dat or not self.current_temp_dir:
            QMessageBox.critical(self, "Error", "No file loaded")
            return

        try:
            # Create backup
            backup_path = self.original_edit_file.parent / f"{self.original_edit_file.name}.backup"
            if not backup_path.exists():
                import shutil
                shutil.copy(self.original_edit_file, backup_path)
                logger.info(f"Created backup: {backup_path}")

            # Save data.dat
            self.edit_file.save(self.current_data_dat)

            # Re-encrypt
            reply = QMessageBox.question(
                self,
                "Confirm Save",
                f"Save changes and re-encrypt?\n\nBackup: {backup_path}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            # Prompt for output location
            output_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Encrypted EDIT File",
                str(self.original_edit_file.parent / "EDIT00000000_edited"),
                "EDIT Files (EDIT00000000);;All Files (*)",
            )

            if not output_path:
                return

            self.file_label.setText(f"Encrypting and saving...")
            self.repaint()

            worker = EncryptWorker(self.current_temp_dir, Path(output_path))
            worker.finished.connect(
                lambda path: self._on_encrypt_complete(path)
            )
            worker.error.connect(self._on_encrypt_error)
            worker.start()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed: {e}")

    def _on_encrypt_complete(self, output_path: Path) -> None:
        """Handle successful encryption."""
        QMessageBox.information(
            self,
            "Success",
            f"File saved successfully: {output_path}\n\n"
            f"Original file backed up: {self.original_edit_file.parent / f'{self.original_edit_file.name}.backup'}",
        )
        self.file_label.setText(f"Saved: {output_path.name}")

    def _on_encrypt_error(self, error: str) -> None:
        """Handle encryption error."""
        QMessageBox.critical(self, "Encryption Error", error)
        self.file_label.setText(f"Save failed")

    # Placeholder methods for EditFile operations
    def add_player(self, player_id: int, to_team_id: int, shirt_number: int) -> bool:
        """Add player from Free Agent (placeholder in EditFile)."""
        if not self.edit_file:
            return False
        # This would be implemented in EditFile
        return True
