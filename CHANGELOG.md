# Changelog
All notable changes to this project will be documented in this file.

## [1.10.0] - 2026-02-23

### Added
- **Snap to Screen** (`S` key): While in the capture overlay, press `S` to instantly snap the capture rectangle to exactly cover the display it is currently on — no more manual pixel-perfect dragging when you want to capture a full screen
  - The snap targets the screen whose centre overlaps the capture rectangle; if the centre falls in a gap between monitors it falls back to the screen with the greatest overlap
  - The dimension spinboxes in the main window update automatically to reflect the snapped size
  - A visual hint ("Press S to snap to screen") is shown just below the capture rectangle, and the instruction bar at the bottom is updated accordingly

---

## [1.9.0] - 2026-02-23

- **Capture Profiles**: Save and reload complete settings snapshots so you can switch between different capture configurations in one click
  - A new **Profiles** panel appears above the Settings section with a dropdown list of all saved profiles
  - **Save as…** — prompts for a name and stores the current hotkey, save folder, file prefix, dimensions, aspect-ratio mode, ratio lock state, clipboard option, and last capture regions for both portrait and landscape modes
  - **Load** — restores all of the above settings from the selected profile and immediately updates every UI field; the hotkey is re-registered if it changed
  - **Delete** — removes the selected profile after a confirmation prompt
  - Multiple profiles are supported; the dropdown is kept sorted alphabetically
  - Profiles are persisted in the existing `~/.portrait_screenshot_settings.json` file under a `profiles` key, so they survive restarts

---

## [1.8.1] - 2026-02-07

### Fixed
- Fixed startup bug where the last captured region was not remembered until switching modes once
  - The application now correctly saves and loads the active ratio mode (portrait/landscape) in settings
  - On startup, the app now uses the saved `ratio_mode` to load the correct last capture region
  - This ensures your capture area appears exactly where you left it, regardless of which mode you were using

### Technical Details
- Added `ratio_mode` and `lock_ratio` to default settings for persistence across sessions
- Modified `get_valid_last_region` to use the saved ratio mode instead of inferring from dimensions
- Updated `apply_settings` to ensure ratio mode is always saved when settings are applied

## [1.8.0] - 2026-02-07

### Added
- **Separate Memory for Portrait and Landscape Modes**: The application now remembers the last captured region independently for portrait (9:16) and landscape (16:9) modes
  - When you switch to portrait mode, it will restore the last position you used in portrait mode
  - When you switch to landscape mode, it will restore the last position you used in landscape mode
  - This allows you to have different preferred capture areas for different aspect ratios

### Changed
- **Improved Mode Switching**: Switching between portrait and landscape modes now properly applies default dimensions
  - Portrait mode (9:16): Automatically sets to 607×1080 pixels
  - Landscape mode (16:9): Automatically sets to 1920×1080 pixels
  - Both radio buttons (Portrait and Landscape) are now properly connected to handle mode changes

### Fixed
- Fixed issue where landscape mode dimensions were not updating correctly when switching from portrait mode
- Fixed radio button handler that was only connected to the portrait button, causing landscape mode to be unresponsive

### Technical Details
- Settings storage now uses `last_capture_rect_9:16` for portrait mode regions
- Settings storage now uses `last_capture_rect_16:9` for landscape mode regions
- Legacy `last_capture_rect` key is deprecated but won't affect existing installations

---

## [1.7.0] - 2026-02-01

1. **File Prefix Setting (Optional)**
   - Added a new "File prefix" field in the UI
   - **Default behavior**: Leave empty to use timestamp naming (original feature preserved)
   - **Custom prefix**: Enter a prefix like "picture", "screenshot", "image" to use sequential numbering

2. **Two Naming Modes**

   **Mode 1: Timestamp (Default - when prefix is empty)**
   - Filenames: `Portrait_2024-02-01_14-30-45.png`
   - This is the original behavior - keeps working as before
   
   **Mode 2: Sequential Numbering (when you enter a prefix)**
   - Filenames: `{prefix}1.png`, `{prefix}2.png`, `{prefix}3.png`, etc.
   - For example, with prefix "picture": `picture1.png`, `picture2.png`, `picture3.png`

3. **Smart Sequence Detection**
   - When using a custom prefix, the app scans the save folder
   - Finds the highest number used with your current prefix
   - Automatically uses the next number in sequence
   - If you delete old screenshots, the numbering adjusts dynamically

## [1.6.0] - 2026-02-01

1. **File Prefix Setting**
   - Added a new "File prefix" field in the UI where users can specify a custom prefix for screenshot filenames
   - Default prefix is "Portrait"
   - Users can change it to anything like "picture", "screenshot", "image", etc.

2. **Auto-Incrementing Sequence Numbers**
   - Screenshots now save as: `{prefix}1.png`, `{prefix}2.png`, `{prefix}3.png`, etc.
   - For example, with prefix "picture": `picture1.png`, `picture2.png`, `picture3.png`

3. **Smart Sequence Detection**
   - The app scans the save folder every time you take a screenshot
   - It finds the highest number used with your current prefix
   - Automatically uses the next number in sequence
   - If you delete old screenshots, the numbering adjusts dynamically

## [1.5.0] - 2025-12-25
### Changed
- Reorganize project structure to be more GitHub-friendly
- Move `main.py` into the `src/` directory

### Added
- Application icon (`icon.ico`)
- Screenshot (`screenshot.png`) under `res/`

---

## [1.4.0] - 2025-12-07
### Added
- Resizable capture rectangle with live dimension updates
- Visual region overlay during selection
- Dynamic width and height display

---

## [1.3.0] - 2025-12-07
### Added
- Clipboard copy option via checkbox

---

## [1.2.0] - 2025-12-07
### Added
- Auto-dismissing toast notifications
- Improved overlay visibility by dimming only outside the capture area

---

## [1.1.0] - 2025-12-07
### Added
- Region memory to restore the last capture location

---

## [1.0.0] - 2025-11-15
### Added
- Initial beta release