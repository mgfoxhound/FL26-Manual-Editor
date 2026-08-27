"""Binary EDIT file parser and manipulation engine for FL26.

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

# MAX allocated slots (vanilla PES21 / FL26 compatible)
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
        ef = EditFile()
        ef.load_bytes(decrypted_data)

        players = ef.get_all_players()
        teams = ef.get_all_teams()

        ef.transfer_player(player_id=12345, from_team=101, to_team=202)
        ef.save_bytes()  # Returns modified data
    """

    def __init__(self):
        self._data: bytearray = bytearray()
        self._undo_stack: List[bytearray] = []
        self._max_undo_depth = 50

        self.metadata = EditFileMetadata()
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

    def load_bytes(self, data: bytes) -> None:
        """Load from raw bytes."""
        self._data = bytearray(data)
        self._parse_header()
        self._calculate_offsets()
        logger.info(f"Loaded {len(self._data):,} bytes")

    def save_bytes(self) -> bytes:
        """Return modified data as bytes."""
        return bytes(self._data)

    def _parse_header(self) -> None:
        """Read entry counts from header."""
        if len(self._data) < HEADER_SIZE:
            raise ValueError(f"Data too small: {len(self._data)} < {HEADER_SIZE}")

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

        logger.info(f"Header: {self.metadata}")

    def _calculate_offsets(self) -> None:
        """Calculate table start positions."""
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
        """Undo last change."""
        if not self._undo_stack:
            return False
        self._data = self._undo_stack.pop()
        logger.info("Undo applied")
        return True

    def get_all_players(self) -> Dict[int, PlayerInfo]:
        """Read all players."""
        players: Dict[int, PlayerInfo] = {}

        for i in range(self.metadata.player_count):
            entry_offset = self.offsets["players"] + i * PLAYER_TOTAL_SIZE

            if entry_offset + PLAYER_ENTRY_SIZE > len(self._data):
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
                name=name or f"Player {player_id}",
                print_name=print_name or name,
            )

        logger.info(f"Read {len(players)} players")
        return players

    def get_all_teams(self) -> Dict[int, TeamInfo]:
        """Read all teams."""
        teams: Dict[int, TeamInfo] = {}

        for i in range(self.metadata.team_count):
            entry_offset = self.offsets["teams"] + i * TEAM_ENTRY_SIZE

            if entry_offset + TEAM_ENTRY_SIZE > len(self._data):
                break

            team_id = struct.unpack_from(
                "<I", self._data, entry_offset + TE_TEAM_ID
            )[0]
            manager_id = struct.unpack_from(
                "<I", self._data, entry_offset + TE_MANAGER_ID
            )[0]
            name = self._read_string(entry_offset + TE_TEAM_NAME, 70)

            if name or team_id > 0:
                teams[team_id] = TeamInfo(
                    team_id=team_id,
                    name=name or f"Team {team_id}",
                    manager_id=manager_id,
                )

        logger.info(f"Read {len(teams)} teams")
        return teams

    def get_all_managers(self) -> Dict[int, ManagerInfo]:
        """Read all managers."""
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
                    name=name or f"Manager {mgr_id}",
                    nationality=nat,
                )

        logger.info(f"Read {len(managers)} managers")
        return managers

    def get_team_roster(self, team_id: int) -> Optional[TeamRoster]:
        """Read a team's roster."""
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
        """Read all rosters."""
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
        """Find byte offset of team's roster entry."""
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
        """Transfer a player from one team to another."""
        self._push_undo()

        if from_team_id == to_team_id:
            logger.error("Source and destination are the same")
            return False

        from_entry = self._find_team_player_entry_offset(from_team_id)
        to_entry = self._find_team_player_entry_offset(to_team_id)

        if from_entry is None or to_entry is None:
            logger.error("Team not found")
            return False

        from_roster = self.get_team_roster(from_team_id)
        to_roster = self.get_team_roster(to_team_id)

        if from_roster is None or to_roster is None:
            return False

        player_idx = from_roster.get_player_index(player_id)
        if player_idx == -1:
            logger.error(f"Player {player_id} not found on team {from_team_id}")
            return False

        if to_roster.has_player(player_id):
            logger.warning(f"Player {player_id} already on destination team")
            return False

        if to_roster.is_full:
            logger.error(f"Destination team roster is full (40/40)")
            return False

        # Remove from source
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
        dest_slot = -1
        for i in range(TP_MAX_PLAYERS):
            if to_roster.player_ids[i] == 0:
                dest_slot = i
                break

        if dest_slot == -1:
            logger.error("No empty slot in destination")
            return False

        final_shirt = shirt_number if shirt_number else from_roster.shirt_numbers[player_idx]
        if final_shirt == 0:
            final_shirt = dest_slot + 1

        self._write_player_slot(to_entry, dest_slot, player_id, final_shirt)

        logger.info(
            f"Transferred player {player_id} from team {from_team_id} "
            f"to team {to_team_id} (shirt #{final_shirt})"
        )
        return True

    def release_player(self, player_id: int, from_team_id: int) -> bool:
        """Release a player from a team."""
        self._push_undo()

        from_entry = self._find_team_player_entry_offset(from_team_id)
        if from_entry is None:
            return False

        from_roster = self.get_team_roster(from_team_id)
        if from_roster is None:
            return False

        player_idx = from_roster.get_player_index(player_id)
        if player_idx == -1:
            return False

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
        """Update player's shirt number."""
        self._push_undo()

        if not 1 <= shirt_number <= 999:
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

        for i, sn in enumerate(roster.shirt_numbers):
            if i != idx and sn == shirt_number and roster.player_ids[i] != 0:
                logger.warning(f"Shirt #{shirt_number} already used")
                return False

        self._write_player_slot(entry, idx, player_id, shirt_number)
        logger.info(f"Updated player {player_id} shirt to #{shirt_number}")
        return True

    def validate_integrity(self) -> Tuple[bool, List[str]]:
        """Validate file structure."""
        errors: List[str] = []
        
        expected_size = (
            self.offsets["game_plan"] + MAX_GAME_PLANS * GAME_PLAN_ENTRY_SIZE
        )
        if len(self._data) != expected_size:
            errors.append(
                f"File size: {len(self._data):,} (expected {expected_size:,})"
            )

        if not 0 <= self.metadata.player_count <= MAX_PLAYERS:
            errors.append(f"Player count out of range: {self.metadata.player_count}")
        if not 0 <= self.metadata.team_count <= MAX_TEAMS:
            errors.append(f"Team count out of range: {self.metadata.team_count}")

        return len(errors) == 0, errors
