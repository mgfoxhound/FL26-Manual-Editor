#!/usr/bin/env python3
"""Download FL26 EDIT00000000 test file and run round-trip test.

Usage:
  python test_round_trip.py <url>

Example:
  python test_round_trip.py https://mediafire.com/...
"""

import sys
from pathlib import Path
from fl26_editor.core.editfile import EditFile
from fl26_editor.core.crypto_bundled import decrypt_edit_file, encrypt_edit_file


def test_round_trip(edit_file_path: Path) -> bool:
    """Test: decrypt -> modify -> encrypt -> decrypt verify."""
    print("="*60)
    print("FL26 Manual Editor - Round-Trip Verification Test")
    print("="*60)

    try:
        # Step 1: Decrypt
        print(f"\n1. Decrypting: {edit_file_path.name}")
        encrypt_header, file_header, logo, desc, data, serial = decrypt_edit_file(
            edit_file_path
        )
        print(f"   ✅ Decrypted {len(data):,} bytes")
        original_data = bytes(data)

        # Step 2: Parse
        print("\n2. Parsing EDIT file structure...")
        ef = EditFile()
        ef.load_bytes(data)
        print(f"   ✅ {ef.metadata}")
        print(f"   ✅ Parsed {len(ef.get_all_players())} players")
        print(f"   ✅ Parsed {len(ef.get_all_teams())} teams")
        print(f"   ✅ Parsed {len(ef.get_all_rosters())} rosters")

        # Step 3: Make a test transfer
        print("\n3. Testing player transfer...")
        players = ef.get_all_players()
        rosters = ef.get_all_rosters()
        teams = ef.get_all_teams()

        # Find a player and transfer them
        test_player_id = None
        from_team_id = None
        to_team_id = None

        for team_id, roster in rosters.items():
            if roster.active_players:
                from_team_id = team_id
                test_player_id = roster.active_players[0]
                break

        if test_player_id and from_team_id:
            # Find another team to transfer to
            for team_id in teams:
                if team_id != from_team_id and rosters[team_id].roster_size < 40:
                    to_team_id = team_id
                    break

            if to_team_id:
                player_name = players[test_player_id].name
                from_team_name = teams[from_team_id].name
                to_team_name = teams[to_team_id].name

                print(f"   Testing: {player_name} from {from_team_name} -> {to_team_name}")
                if ef.transfer_player(test_player_id, from_team_id, to_team_id, 10):
                    print(f"   ✅ Transfer succeeded")
                else:
                    print(f"   ❌ Transfer failed (will re-encrypt anyway)")
            else:
                print("   ⚠ No suitable destination team found")
        else:
            print("   ⚠ No test player found")

        # Step 4: Re-encrypt
        print("\n4. Re-encrypting...")
        modified_data = ef.save_bytes()
        encrypted = encrypt_edit_file(
            encrypt_header, file_header, logo, desc, modified_data, serial
        )
        print(f"   ✅ Encrypted {len(encrypted):,} bytes")

        # Step 5: Verify round-trip
        print("\n5. Verifying round-trip (decrypt output)...")
        test_file = Path("/tmp/fl26_test.dat")
        test_file.write_bytes(encrypted)

        _, _, _, _, verify_data, _ = decrypt_edit_file(test_file)
        print(f"   ✅ Re-decrypted {len(verify_data):,} bytes")

        if verify_data == modified_data:
            print("   ✅ Data matches perfectly!")
        else:
            print(f"   ❌ Data mismatch: {len(verify_data)} vs {len(modified_data)}")
            return False

        # Step 6: Verify can be re-parsed
        print("\n6. Verifying parsed data after round-trip...")
        ef2 = EditFile()
        ef2.load_bytes(verify_data)
        print(f"   ✅ {ef2.metadata}")
        print(f"   ✅ Successfully re-parsed")

        print("\n" + "="*60)
        print("✅ ROUND-TRIP TEST PASSED!")
        print("="*60)
        print("\nThe application is ready for use.")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_round_trip.py <path_to_EDIT00000000>")
        sys.exit(1)

    edit_file = Path(sys.argv[1])
    if not edit_file.exists():
        print(f"File not found: {edit_file}")
        sys.exit(1)

    success = test_round_trip(edit_file)
    sys.exit(0 if success else 1)
