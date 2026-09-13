# MF Analyser — go-live checklist (print this page)

Machine name: ______________________  IP: _______________  DHCP reservation / static: ☐ yes ☐ asked IT
Installed by: ______________________  Date: _____________  Mode: ☐ NSSM service ☐ Scheduled Task

Every step has a box. Tick it only when you saw the result described. If a step fails, stop,
note what you saw in the margin, and send this page plus `C:\MFAnalyser\data\logs\mf-analyser.log`.

## A. Install (on the always-on machine, 20–30 minutes)

- ☐ A1. The repo is at a **local** folder such as `C:\MFAnalyser\app` (not OneDrive, not a network drive).
- ☐ A2. Open PowerShell **as administrator**, `cd C:\MFAnalyser\app`, run
  `powershell -ExecutionPolicy Bypass -File deploy\install.ps1`.
  If antivirus quarantines `nssm.exe`, run it again with `-UseScheduledTask`.
- ☐ A3. You were asked for the shared password twice and typed the same 8+ characters.
- ☐ A4. The installer ended with `OK  healthy` and printed two URLs. Write the first one here:
  `http://______________________:8000/`
- ☐ A5. `deploy\status.ps1` shows `state: Running` (service) or `state: Running`/`Ready` (task) and `OK  health`.
- ☐ A5a. The same output says `PDF: available`. If it says `unavailable: GTK not found`, install the GTK3 runtime it names, run `deploy\restart.ps1`, and check again. Result: ☐ available ☐ installed later
- ☐ A5b. The same output names the backup mirror (`mirror: \\server\share …`). If it says `mirror: none`, the backups are single-disk: write the share or OneDrive folder here and rerun the installer with `-BackupMirror`: ______________________
- ☐ A6. On this machine, a browser at `http://localhost:8000/` shows the sign-in screen; the password opens the console.

## B. Survives a reboot

- ☐ B1. Restart Windows. **Do not sign in** to Windows afterwards.
- ☐ B2. From the second PC (step C1) the page loads within two minutes of the reboot. Time it: ______ s.
- ☐ B3. Now sign in to Windows and run `deploy\status.ps1`: still `Running`.

## C. Second user over the network

- ☐ C1. On the other PC, type the URL from A4. The sign-in screen appears.
  If it does not: try the numeric URL the installer printed; if that works, the machine name does not resolve (tell IT). If neither works, the firewall rule is missing: rerun the installer.
- ☐ C2. Sign in with the shared password. The dashboard renders with the greeting and the executive summary.
- ☐ C3. "Sign out" in the top bar returns to the sign-in screen; signing back in works.

## D. Monthly routine, end to end, from the second PC

- ☐ D1. Close Excel. Copy this month's master into `C:\MFAnalyser\data\inbox` on the server (or anywhere on the second PC).
- ☐ D2. Console → Upload → choose the copy. Upload finishes and shows the validation result. Time: ______ s.
- ☐ D3. Versions → the new version → the diff against the active one reads sensibly (logic / data / structural counts).
- ☐ D4. Activate it. The version pill in the top bar now names the new file.
- ☐ D5. Dashboard, Funds and Movement reflect the new month ("since <date>" in the narrative).

## E. Two people at once

- ☐ E1. On both PCs open Workbook mode → Inputs, change the same parameter, and click Run within a second of each other.
- ☐ E2. One PC completes; the other shows "another run is in progress" and then completes by itself. Both finished: ☐

## F. Backup and restore drill

- ☐ F1. On the server (admin PowerShell): `deploy\backup-now.ps1` prints `backup written to C:\MFAnalyser\backups\<today>`.
- ☐ F2. `deploy\restore.ps1 -Date <today>` ends with `OK  restored <today> and healthy`.
- ☐ F3. Reload the console on the second PC: the same versions are listed and the dashboard is unchanged.
- ☐ F4. Task Scheduler → Task Scheduler Library → "MFAnalyser Backup" exists, next run 02:00.
- ☐ F5. Open the mirror folder from the **second PC**: today's dated folder is there with `mf-analyser.db`, `workbooks\` and `manifest.json`.

## G. Record

| What | Result |
| --- | --- |
| Reboot to page-up (B2) | ______ s |
| Upload + validate (D2) | ______ s |
| Concurrent what-if (E2) | ☐ second waited, then completed |
| Restore drill (F2) | ☐ ok |
| Deviations / notes | |

Signed: ______________________
