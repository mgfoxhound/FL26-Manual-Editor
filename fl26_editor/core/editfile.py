"""Binary EDIT file parser and manipulation engine.

Reads and writes the decrypted data.dat file according to the PES 2021/FL26
edit-file binary format. Handles:
  - Player database (ID, name, stats)
  - Team database (ID, name, manager assignment)
  - Team rosters (player assignments, shirt numbers)
  - Manager database (ID, name, nationality)
  - Transfer operations (move player between teams)
  - Release operations (remove player from team)
  - Undo history
"""

import logging
import struct
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from copy import deepcopy

from fl26_editor.core.models import (
    PlayerInfo,
    TeamInfo,
    ManagerInfo,
    TeamRoster,
    EditFileMetadata,
)

logger = logging.getLogger(__name__)

# Entry sizes (bytes) — same across PES20/21/FL26
HEADER_SIZE = 0x7C  # 124 bytes
PLAYER_ENTRY_SIZE = 0xF0  # 240 bytes
PLAYER_APPEARANCE_SIZE = 0x48  # 72 bytes
PLAYER_TOTAL_SIZE = PLAYER_ENTRY_SIZE + PLAYER_APPEARANCE_SIZE  # 312 bytes
TEAM_ENTRY_SIZE = 0x24C  # 588 bytes
MANAGER_ENTRY_SIZE = 0x58  # 88 bytes
TEAM_PLAYER_ENTRY_SIZE = 0x11C  # 284 bytes
GAME_PLAN_ENTRY_SIZE = 0x274  # 628 bytes
COMPETITION_SECTION_SIZE = 0x1230  # 4656 bytes

# MAX allocated slots (vanilla PES21)
MAX_PLAYERS = 30_000
MAX_TEAMS = 750
MAX_MANAGERS = 1_300
MAX_STADIUMS = 65
MAX_COMPETITIONS = 65
MAX_UNKNOWN = 2_500
MAX_TEAM_PLAYER = 750
MAX_GAME_PLANS = 750

# Header field offsets (uint16 LE)
HDR_PLAYER_COUNT = 0x60
HDR_TEAM_COUNT = 0x64
HDR_MANAGER_COUNT = 0x66
HDR_STADIUM_COUNT = 0x68
HDR_COMPETITION_COUNT = 0x6A
HDR_UNKNOWN_COUNT = 0x6C
HDR_TEAM_PLAYER_COUNT = 0x70
HDR_GAME_PLAN_COUNT = 0x74

# Field offsets within entries
PE_PLAYER_ID = 0x00
PE_PLAYER_NAME = 0x36
PE_PRINT_NAME = 0x73

TE_TEAM_ID = 0x000
TE_MANAGER_ID = 0x004
TE_TEAM_NAME = 0x068

ME_MANAGER_ID = 0x000
ME_NATIONALITY = 0x004
ME_MANAGER_NAME = 0x009

TP_TEAM_ID = 0x00
TP_PLAYER_IDS = 0x04  # 40 × 4 bytes
TP_SHIRT_NUMBERS = 0xA4  # 40 × 2 bytes
TP_MAX_PLAYERS = 40

GP_TEAM_ID = 0x000
GP_LINEUP = 0x1E4  # 40 bytes


class EditFile:
    """Decrypted EDIT file reader/writer.

    Usage:
        ef = EditFile("path/to/data.dat")
        ef.load()

        # Read data
        players = ef.get_all_players()
        teams = ef.get_all_teams()
        roster = ef.get_team_roster(team_id=101)

        # Make changes
        ef.transfer_player(player_id=12345, from_team=101, to_team=202)

        # Undo if needed
        ef.undo()

        # Save
        ef.save("path/to/data.dat")
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self._data: bytearray = bytearray()
        self._original_data: bytearray = bytearray()  # For round-trip validation
        self._undo_stack: List[bytearray] = []  # Undo history
        self._max_undo_depth = 50

        # Metadata from header
        self.metadata = EditFileMetadata()

        # Cached offsets
        self.offsets = {
            "players": 0,
            "teams": 0,
            "managers": 0,
            "competitions": 0,
            "stadiums": 0,
            "unknown": 0,
            "team_player": 0,
            "competition_entry": 0,
            "game_plan": 0,
        }

    def load(self, path: Optional[Path] = None) -> None:
        """Load and parse data.dat from disk."""
        if path:
            self.path = Path(path)
        if not self.path or not self.path.exists():
            raise FileNotFoundError(f"data.dat not found: {self.path}")

        with open(self.path, "rb") as f:
            self._data = bytearray(f.read())

        self._original_data = bytearray(self._data)  # Keep copy for validation
        logger.info(f"Loaded {len(self._data):,} bytes from {self.path}")
        self._parse_header()
        self._calculate_offsets()

    def load_bytes(self, data: bytes) -> None:
        """Load from raw bytes (for testing)."""
        self._data = bytearray(data)
        self._original_data = bytearray(self._data)
        self._parse_header()
        self._calculate_offsets()

    def _parse_header(self) -> None:
        """Read entry counts from the header."""
        if len(self._data) < HEADER_SIZE:
            raise ValueError(
                f"Data too small ({len(self._data)} bytes), "
                f"expected at least {HEADER_SIZE}"
            )

        self.metadata.player_count = struct.unpack_from(
            "<H", self._data, HDR_PLAYER_COUNT
        )[0]
        self.metadata.team_count = struct.unpack_from(
            "<H", self._data, HDR_TEAM_COUNT
        )[0]
        self.metadata.manager_count = struct.unpack_from(
            "<H", self._data, HDR_MANAGER_COUNT
        )[0]
        self.metadata.stadium_count = struct.unpack_from(
            "<H", self._data, HDR_STADIUM_COUNT
        )[0]
        self.metadata.competition_count = struct.unpack_from(
            "<H", self._data, HDR_COMPETITION_COUNT
        )[0]
        self.metadata.unknown_count = struct.unpack_from(
            "<H", self._data, HDR_UNKNOWN_COUNT
        )[0]
        self.metadata.team_player_count = struct.unpack_from(
            "<H", self._data, HDR_TEAM_PLAYER_COUNT
        )[0]
        self.metadata.game_plan_count = struct.unpack_from(
            "<H", self._data, HDR_GAME_PLAN_COUNT
        )[0]

        logger.info(f"Parsed header: {self.metadata}")

    def _calculate_offsets(self) -> None:
        """Calculate table start positions from fixed MAX slot sizes."""
        player_start = HEADER_SIZE
        team_start = player_start + MAX_PLAYERS * PLAYER_TOTAL_SIZE
        manager_start = team_start + MAX_TEAMS * TEAM_ENTRY_SIZE
        competition_start = manager_start + MAX_MANAGERS * MANAGER_ENTRY_SIZE
        stadium_start = competition_start + MAX_COMPETITIONS * TEAM_ENTRY_SIZE
        unknown_start = stadium_start + MAX_STADIUMS * TEAM_ENTRY_SIZE
        team_player_start = unknown_start + MAX_UNKNOWN * TEAM_ENTRY_SIZE
        competition_entry_start = team_player_start + MAX_TEAM_PLAYER * TEAM_PLAYER_ENTRY_SIZE
        game_plan_start = competition_entry_start + COMPETITION_SECTION_SIZE

        self.offsets = {
            "players": player_start,
            "teams": team_start,
            "managers": manager_start,
            "competitions": competition_start,
            "stadiums": stadium_start,
            "unknown": unknown_start,
            "team_player": team_player_start,
            "competition_entry": competition_entry_start,
            "game_plan": game_plan_start,
        }
        logger.info(f"Calculated offsets: {self.offsets}")

    def _read_string(self, offset: int, max_len: int) -> str:
        """Read null-terminated string."""
        end = min(offset + max_len, len(self._data))
        raw = self._data[offset:end]
        null_pos = raw.find(0)
        if null_pos >= 0:
            raw = raw[:null_pos]
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return raw.decode("latin-1", errors="replace")

    def _push_undo(self) -> None:
        """Save current state to undo stack."""
        self._undo_stack.append(bytearray(self._data))
        if len(self._undo_stack) > self._max_undo_depth:
            self._undo_stack.pop(0)

    def undo(self) -> bool:
        """Undo the last change. Returns True if successful."""
        if not self._undo_stack:
            logger.warning("Undo stack is empty")
            return False
        self._data = self._undo_stack.pop()
        logger.info("Undo applied")
        return True

    def get_all_players(self) -> Dict[int, PlayerInfo]:
        """Read all players from the EDIT file.

        Returns:
            {player_id: PlayerInfo}
        """
        players: Dict[int, PlayerInfo] = {}

        for i in range(self.metadata.player_count):
            entry_offset = self.offsets["players"] + i * PLAYER_TOTAL_SIZE

            if entry_offset + PLAYER_ENTRY_SIZE > len(self._data):
                logger.warning(f"Player entry {i} exceeds data size")
                break

            player_id = struct.unpack_from(
                "<I", self._data, entry_offset + PE_PLAYER_ID
            )[0]
            if player_id == 0:
                continue

            name = self._read_string(entry_offset + PE_PLAYER_NAME, 61)
            print_name = self._read_string(entry_offset + PE_PRINT_NAME, 61)

            players[player_id] = PlayerInfo(
                player_id=player_id,
                name=name,
                print_name=print_name or name,
            )

        logger.info(f"Read {len(players)} players")
        return players

    def get_all_teams(self) -> Dict[int, TeamInfo]:
        """Read all teams.

        Returns:
            {team_id: TeamInfo}
        """
        teams: Dict[int, TeamInfo] = {}

        for i in range(self.metadata.team_count):
            entry_offset = self.offsets["teams"] + i * TEAM_ENTRY_SIZE

            if entry_offset + TEAM_ENTRY_SIZE > len(self._data):
                logger.warning(f"Team entry {i} exceeds data size")
                break

            team_id = struct.unpack_from(
                "<I", self._data, entry_offset + TE_TEAM_ID
            )[0]
            manager_id = struct.unpack_from(
                "<I", self._data, entry_offset + TE_MANAGER_ID
            )[0]
            name = self._read_string(entry_offset + TE_TEAM_NAME, 70)

            teams[team_id] = TeamInfo(
                team_id=team_id,
                name=name,
                manager_id=manager_id,
            )

        logger.info(f"Read {len(teams)} teams")
        return teams

    def get_all_managers(self) -> Dict[int, ManagerInfo]:
        """Read all managers.

        Returns:
            {manager_id: ManagerInfo}
        """
        managers: Dict[int, ManagerInfo] = {}

        for i in range(self.metadata.manager_count):
            entry_offset = self.offsets["managers"] + i * MANAGER_ENTRY_SIZE
            if entry_offset + MANAGER_ENTRY_SIZE > len(self._data):
                break

            mgr_id = struct.unpack_from(
                "<I", self._data, entry_offset + ME_MANAGER_ID
            )[0]
            nat = struct.unpack_from(
                "<H", self._data, entry_offset + ME_NATIONALITY
            )[0]
            name = self._read_string(entry_offset + ME_MANAGER_NAME, 79)

            if mgr_id != 0 or name:
                managers[mgr_id] = ManagerInfo(
                    manager_id=mgr_id,
                    name=name,
                    nationality=nat,
                )

        logger.info(f"Read {len(managers)} managers")
        return managers

    def get_team_roster(self, team_id: int) -> Optional[TeamRoster]:
        """Read a team's roster.

        Args:
            team_id: Team ID to look up.

        Returns:
            TeamRoster or None if not found.
        """
        for i in range(self.metadata.team_player_count):
            entry_offset = self.offsets["team_player"] + i * TEAM_PLAYER_ENTRY_SIZE

            if entry_offset + TEAM_PLAYER_ENTRY_SIZE > len(self._data):
                break

            tid = struct.unpack_from(
                "<I", self._data, entry_offset + TP_TEAM_ID
            )[0]
            if tid != team_id:
                continue

            player_ids = []
            for j in range(TP_MAX_PLAYERS):
                pid = struct.unpack_from(
                    "<I", self._data, entry_offset + TP_PLAYER_IDS + j * 4
                )[0]
                player_ids.append(pid)

            shirt_numbers = []
            for j in range(TP_MAX_PLAYERS):
                sn = struct.unpack_from(
                    "<H", self._data, entry_offset + TP_SHIRT_NUMBERS + j * 2
                )[0]
                shirt_numbers.append(sn)

            return TeamRoster(
                team_id=team_id,
                player_ids=player_ids,
                shirt_numbers=shirt_numbers,
            )

        return None

    def get_all_rosters(self) -> Dict[int, TeamRoster]:
        """Read all team rosters.

        Returns:
            {team_id: TeamRoster}
        """
        rosters: Dict[int, TeamRoster] = {}
        for i in range(self.metadata.team_player_count):
            entry_offset = self.offsets["team_player"] + i * TEAM_PLAYER_ENTRY_SIZE

            if entry_offset + TEAM_PLAYER_ENTRY_SIZE > len(self._data):
                break

            tid = struct.unpack_from(
                "<I", self._data, entry_offset + TP_TEAM_ID
            )[0]

            player_ids = []
            for j in range(TP_MAX_PLAYERS):
                pid = struct.unpack_from(
                    "<I", self._data, entry_offset + TP_PLAYER_IDS + j * 4
                )[0]
                player_ids.append(pid)

            shirt_numbers = []
            for j in range(TP_MAX_PLAYERS):
                sn = struct.unpack_from(
                    "<H", self._data, entry_offset + TP_SHIRT_NUMBERS + j * 2
                )[0]
                shirt_numbers.append(sn)

            rosters[tid] = TeamRoster(
                team_id=tid,
                player_ids=player_ids,
                shirt_numbers=shirt_numbers,
            )

        logger.info(f"Read {len(rosters)} rosters")
        return rosters

    def _find_team_player_entry_offset(self, team_id: int) -> Optional[int]:
        """Find byte offset of a team's Team-Player table entry."""
        for i in range(self.metadata.team_player_count):
            offset = self.offsets["team_player"] + i * TEAM_PLAYER_ENTRY_SIZE
            if offset + 4 > len(self._data):
                break
            tid = struct.unpack_from("<I", self._data, offset + TP_TEAM_ID)[0]
            if tid == team_id:
                return offset
        return None

    def _write_player_slot(
        self, entry_offset: int, slot_idx: int, player_id: int, shirt_num: int
    ) -> None:
        """Write player ID and shirt number to a roster slot."""
        if not 0 <= slot_idx < TP_MAX_PLAYERS:
            raise IndexError(f"Roster slot out of range: {slot_idx}")
        if not 0 <= player_id <= 0xFFFFFFFF:
            raise ValueError(f"Player ID out of uint32 range: {player_id}")
        if not 0 <= shirt_num <= 999:
            raise ValueError(f"Shirt number out of range: {shirt_num}")

        pid_offset = entry_offset + TP_PLAYER_IDS + slot_idx * 4
        sn_offset = entry_offset + TP_SHIRT_NUMBERS + slot_idx * 2

        struct.pack_into("<I", self._data, pid_offset, player_id)
        struct.pack_into("<H", self._data, sn_offset, shirt_num)

    def transfer_player(
        self,
        player_id: int,
        from_team_id: int,
        to_team_id: int,
        shirt_number: Optional[int] = None,
    ) -> bool:
        """Transfer a player from one team to another.

        Args:
            player_id: Player to transfer.
            from_team_id: Source team ID.
            to_team_id: Destination team ID.
            shirt_number: Optional preferred shirt number.

        Returns:
            True if successful, False otherwise.
        """
        self._push_undo()

        if from_team_id == to_team_id:
            logger.error("Source and destination are the same team")
            return False

        from_entry = self._find_team_player_entry_offset(from_team_id)
        to_entry = self._find_team_player_entry_offset(to_team_id)

        if from_entry is None:
            logger.error(f"Source team {from_team_id} not found")
            return False
        if to_entry is None:
            logger.error(f"Destination team {to_team_id} not found")
            return False

        from_roster = self.get_team_roster(from_team_id)
        to_roster = self.get_team_roster(to_team_id)

        if from_roster is None or to_roster is None:
            logger.error("Could not read rosters")
            return False

        # Find player in source
        player_idx = from_roster.get_player_index(player_id)
        if player_idx == -1:
            logger.error(f"Player {player_id} not found on team {from_team_id}")
            return False

        if to_roster.has_player(player_id):
            logger.warning(f"Player {player_id} already on destination team")
            return False

        if to_roster.is_full:
            logger.error(f"Destination team {to_team_id} roster is full (40/40)")
            return False

        # Remove from source (compact by shifting last player)
        last_idx = -1
        for k in range(TP_MAX_PLAYERS - 1, -1, -1):
            if from_roster.player_ids[k] != 0:
                last_idx = k
                break

        if last_idx == player_idx:
            self._write_player_slot(from_entry, player_idx, 0, 0)
        elif last_idx > player_idx:
            self._write_player_slot(
                from_entry,
                player_idx,
                from_roster.player_ids[last_idx],
                from_roster.shirt_numbers[last_idx],
            )
            self._write_player_slot(from_entry, last_idx, 0, 0)
        else:
            self._write_player_slot(from_entry, player_idx, 0, 0)

        # Add to destination
        dest_slot = to_roster.first_empty_slot() if hasattr(to_roster, 'first_empty_slot') else -1
        if dest_slot == -1:
            # Manual search
            for i in range(TP_MAX_PLAYERS):
                if to_roster.player_ids[i] == 0:
                    dest_slot = i
                    break

        if dest_slot == -1:
            logger.error("No empty slot in destination roster")
            return False

        final_shirt = shirt_number if shirt_number else from_roster.shirt_numbers[player_idx]
        if final_shirt == 0:
            final_shirt = dest_slot + 1  # Default to slot + 1

        self._write_player_slot(to_entry, dest_slot, player_id, final_shirt)

        logger.info(
            f"Transferred player {player_id} from team {from_team_id} "
            f"(slot {player_idx}) to team {to_team_id} (slot {dest_slot}, shirt #{final_shirt})"
        )
        return True

    def release_player(self, player_id: int, from_team_id: int) -> bool:
        """Release a player from a team (becomes Free Agent).

        Args:
            player_id: Player to release.
            from_team_id: Team to remove player from.

        Returns:
            True if successful, False otherwise.
        """
        self._push_undo()

        from_entry = self._find_team_player_entry_offset(from_team_id)
        if from_entry is None:
            logger.error(f"Team {from_team_id} not found")
            return False

        from_roster = self.get_team_roster(from_team_id)
        if from_roster is None:
            return False

        player_idx = from_roster.get_player_index(player_id)
        if player_idx == -1:
            logger.error(f"Player {player_id} not found on team {from_team_id}")
            return False

        # Find last player and compact
        last_idx = -1
        for k in range(TP_MAX_PLAYERS - 1, -1, -1):
            if from_roster.player_ids[k] != 0:
                last_idx = k
                break

        if last_idx == player_idx:
            self._write_player_slot(from_entry, player_idx, 0, 0)
        elif last_idx > player_idx:
            self._write_player_slot(
                from_entry,
                player_idx,
                from_roster.player_ids[last_idx],
                from_roster.shirt_numbers[last_idx],
            )
            self._write_player_slot(from_entry, last_idx, 0, 0)
        else:
            self._write_player_slot(from_entry, player_idx, 0, 0)

        logger.info(f"Released player {player_id} from team {from_team_id}")
        return True

    def update_shirt_number(
        self, team_id: int, player_id: int, shirt_number: int
    ) -> bool:
        """Update a player's shirt number.

        Args:
            team_id: Team ID.
            player_id: Player ID.
            shirt_number: New shirt number (1-999).

        Returns:
            True if successful, False otherwise.
        """
        self._push_undo()

        if not 1 <= shirt_number <= 999:
            logger.error(f"Invalid shirt number: {shirt_number}")
            return False

        entry = self._find_team_player_entry_offset(team_id)
        if entry is None:
            return False

        roster = self.get_team_roster(team_id)
        if roster is None:
            return False

        idx = roster.get_player_index(player_id)
        if idx == -1:
            return False

        # Check for duplicates
        for i, sn in enumerate(roster.shirt_numbers):
            if i != idx and sn == shirt_number and roster.player_ids[i] != 0:
                logger.warning(f"Shirt #{shirt_number} already used on team {team_id}")
                return False

        self._write_player_slot(entry, idx, player_id, shirt_number)
        logger.info(f"Updated player {player_id} shirt to #{shirt_number}")
        return True

    def save(self, path: Optional[Path] = None) -> None:
        """Write modified data to disk."""
        save_path = Path(path) if path else self.path
        if not save_path:
            raise ValueError("No save path specified")

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(self._data)

        logger.info(f"Saved {len(self._data):,} bytes to {save_path}")

    def validate_integrity(self) -> Tuple[bool, List[str]]:
        """Validate file structure. Returns (is_valid, error_list)."""
        errors: List[str] = []

        # Check file size
        expected_size = (
            self.offsets["game_plan"] + MAX_GAME_PLANS * GAME_PLAN_ENTRY_SIZE
        )
        if len(self._data) != expected_size:
            errors.append(
                f"File size mismatch: {len(self._data):,} vs expected {expected_size:,}"
            )

        # Check count limits
        if not 0 <= self.metadata.player_count <= MAX_PLAYERS:
            errors.append(f"Player count {self.metadata.player_count} out of range")
        if not 0 <= self.metadata.team_count <= MAX_TEAMS:
            errors.append(f"Team count {self.metadata.team_count} out of range")

        return len(errors) == 0, errors
