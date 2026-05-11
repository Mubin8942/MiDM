import { platform } from '@tauri-apps/plugin-os';
import { openPath, revealItemInDir } from '@tauri-apps/plugin-opener';
import { join, downloadDir } from '@tauri-apps/api/path';

/**
 * Opens a folder in the native file manager.
 * - Windows: reveals the file (highlights it) if a file path is given
 * - macOS:   reveals the file in Finder
 * - Linux:   opens the folder (revealItemInDir is unsupported on Linux)
 *
 * @param {string|null} dir       - The folder path
 * @param {string|null} filename  - Optional filename inside dir to reveal
 * @returns {Promise<string|null>} - Error message string, or null on success
 */
export async function openFolder(dir = null, filename = null) {
  try {
    const os = await platform(); // 'windows' | 'macos' | 'linux'
    const folder = dir ?? (await downloadDir());

    if (filename) {
      const filePath = await join(folder, filename);

      if (os === 'linux') {
        // Linux: revealItemInDir is not supported — open the folder directly
        await openPath(folder);
      } else {
        // Windows + macOS: try to reveal/highlight the file
        try {
          await revealItemInDir(filePath);
        } catch {
          // File was moved/deleted — fall back to opening the folder
          await openPath(folder);
          return `"${filename}" was not found. It may have been moved or deleted.`;
        }
      }
    } else {
      await openPath(folder);
    }

    return null; // success
  } catch (e) {
    console.error('[openFolder] Failed:', e);
    return 'Could not open the downloads folder.';
  }
}