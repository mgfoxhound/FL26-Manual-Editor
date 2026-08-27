# FL26 Manual Editor - Standalone Windows Application

## Installation

1. **Download** `FL26ManualEditor.zip` from [Releases](../../releases)
2. **Extract** the folder anywhere (Desktop, Documents, etc.)
3. **Double-click** `FL26 Manual Editor.exe`

## Usage

### Open a File

**Method 1: Drag & Drop**
- Drag your `EDIT00000000` file onto the application window
- The file will load automatically

**Method 2: Open Button**
- Click "📁 Open EDIT00000000"
- Browse to select your file

### Make Changes

**Search & Transfer Players**
- Use the **👥 Players** tab to find players by name or club
- Select a player and click "🔄 Transfer" to move them to another club
- Set their shirt number when prompted

**Release Players**
- Select a player and click "❌ Release" to make them a Free Agent

**Change Shirt Numbers**
- Select a player and click "👕 Shirt #" to change their number

**View Club Squads**
- Use the **⚽ Clubs** tab to see all players at a specific club
- Click the club dropdown to switch teams

**Track Changes**
- The **📝 Changes** tab shows a log of all your edits

### Undo Changes

- Click **↶ Undo** to revert the last change (up to 50 steps)

### Save Your Work

1. Click **💾 Save As EDIT00000000**
2. Choose where to save (recommended: a new folder)
3. Your original file is never modified (automatically backed up)
4. Use the new file in FL26!

## FAQ

### Where do I get my EDIT00000000 file?

Your FL26 save file is located at:
```
Documents\KONAMI\eFootball PES 2021 SEASON UPDATE\2026\save\EDIT00000000
```

### Can I use the saved file immediately?

Yes! Once saved, copy the new `EDIT00000000` to your FL26 save folder:
```
Documents\KONAMI\eFootball PES 2021 SEASON UPDATE\2026\save\
```

### Will my original file be deleted?

No. The application creates a `.backup` file automatically and never modifies your original.

### Can I undo multiple changes?

Yes. Click ↶ Undo repeatedly to go back up to 50 changes.

### What if I want to start over?

Click "📁 Open EDIT00000000" again and select your original file. Undo history is cleared.

## Troubleshooting

### "Windows SmartScreen" Warning

This is normal for unsigned applications. Click **More info** → **Run anyway**.

### Application Won't Start

1. Ensure you extracted the entire folder
2. Don't move files around inside the folder
3. Try running as Administrator
4. Check `%USERPROFILE%\.fl26_editor\editor.log` for error details

### File Won't Load

- Ensure the file is a valid FL26 EDIT00000000 (not corrupted)
- The file should be from FL26 Update 2.2 or compatible version
- Check the log file for specific error messages

### Transfer/Release Fails

- Destination team might be full (40/40 players)
- Player might already be on that team
- Try using a different destination

## Support

Issues or feedback? Open an issue on GitHub:
https://github.com/mgfoxhound/FL26-Manual-Editor/issues

## License

MIT License - Free to use and modify
