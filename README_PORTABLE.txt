LENDER PACKAGE BUILDER 1.0.0 RC1 - PORTABLE WINDOWS APPLICATION
==================================================================

Thank you for using Lender Package Builder. This document explains
what you have, how to run it, and what to do if something goes wrong.
It is written for someone who is not a programmer.

------------------------------------------------------------------
WHAT THIS IS
------------------------------------------------------------------

Lender Package Builder turns a lender ZIP file, a folder, or a single
document into two organized PDF packages:

  - OG    -- every source document, in original order, nothing removed
  - Final -- the same, but with exact duplicate copies of the same
             file removed

Everything happens on THIS computer only. No file, filename, or piece
of information is ever sent anywhere over the internet. There is no
telemetry, no analytics, and no account required.

This is a "release candidate" (RC1) -- it has passed automated testing,
including on a real Windows GitHub Actions build machine, but it has
NOT yet been manually confirmed on a real, physical Windows 11
computer by the project owner. Treat it as ready for careful testing,
not yet as a fully approved final release. See
WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md.

------------------------------------------------------------------
WHAT'S IN THIS FOLDER
------------------------------------------------------------------

  LenderPackageBuilder.exe   The application itself. Double-click this
                               to run it.
  _internal\                  Required program files (Python runtime,
                               PySide6/Qt, and all other libraries the
                               application needs). This folder MUST
                               stay in the same place as the .exe --
                               do not move, rename, or delete it.
  config.toml                  Optional settings file. You can open
                               this in Notepad to change advanced
                               defaults (see "Configuration" below).
                               You do not need to touch it to use the
                               application.
  licenses\                    Full license text for every open-source
                               library bundled inside this application.
  TEST_PORTABLE_APP.bat        Double-click to verify this build is
                               working correctly on your computer.
  RUN_DIAGNOSTICS.bat          Double-click to see technical
                               information useful for troubleshooting.
  Sample_Test_Package.zip      A small, harmless, made-up test package
                               (no real data) you can use to try the
                               application safely.
  Sample_Test_Package_Expected_Results.txt
                                What you should see if you process the
                               sample package above.
  THIRD_PARTY_NOTICES.txt      Open-source license information.
  WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md
                                A step-by-step manual test checklist.
  RELEASE_NOTES_1.0.0_RC1.md   What's new/changed in this release.
  BUILD_MANIFEST.txt           Exactly how and when this specific copy
                               was built (for troubleshooting).

------------------------------------------------------------------
WHY THE "_internal" FOLDER MUST STAY WITH THE EXE
------------------------------------------------------------------

LenderPackageBuilder.exe is small on its own -- almost everything it
needs to run (the Python runtime, the PDF libraries, the desktop
interface toolkit) lives in the "_internal" folder next to it. This is
completely normal for a portable application packaged this way. If you
move LenderPackageBuilder.exe by itself to a different folder without
"_internal", it will not start.

If you want to move the whole application, move (or copy) the ENTIRE
folder -- LenderPackageBuilder.exe, _internal, config.toml, and
everything else together -- to the new location.

------------------------------------------------------------------
HOW TO LAUNCH IT
------------------------------------------------------------------

1. Extract the downloaded ZIP file completely (right-click it and
   choose "Extract All..."). Do not run the application directly from
   inside the ZIP.
2. Open the extracted folder.
3. Double-click LenderPackageBuilder.exe.
4. A window should open in a few seconds. No black command-line
   window should stay open, and no Python installer or setup wizard
   should appear.

You do NOT need to install Python. You do NOT need administrator
rights. You do NOT need to run an installer.

------------------------------------------------------------------
WINDOWS SECURITY WARNINGS (SmartScreen / antivirus)
------------------------------------------------------------------

Because this application is not yet signed with a paid commercial code
certificate, Windows SmartScreen or your antivirus software may show a
warning like "Windows protected your PC" or flag the file for review
the first time you run it. This is expected for a new, unsigned
application and does not by itself mean anything is wrong. See
WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md for what to record if you see
this, and do not bypass your company's security policy to run it --
ask your IT department for approval first if you are on a managed
work computer.

You can verify the ZIP file you downloaded has not been tampered with
by checking its SHA-256 checksum against the value in
Lender_Package_Builder_1.0.0_RC1_Windows_x64_Portable_SHA256.txt
(see WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md for how).

------------------------------------------------------------------
HOW TO RUN THE SELF-TEST
------------------------------------------------------------------

Double-click TEST_PORTABLE_APP.bat. This runs several automatic
checks built into the application itself (it does not need Python,
pytest, or an internet connection) and tells you PASS or FAIL for
each one, then pauses so you can read the results. If everything
says PASS, the application is working correctly on this computer.

------------------------------------------------------------------
HOW TO PROCESS A PACKAGE
------------------------------------------------------------------

1. Launch LenderPackageBuilder.exe.
2. Drag a ZIP file, a folder, or a single document onto the window
   (or use the "Browse File" / "Browse Folder" buttons).
   You can also drag a single ZIP, folder, or file directly onto
   LenderPackageBuilder.exe itself -- the application will open with
   that input already selected (it will not start processing until
   you click the button).
3. Review the estimated size shown, then click
   "Build Lender Packages".
4. Watch the progress screen. When it finishes, you'll see a summary
   with a link to open the output folder, which is created next to
   your original input.

The output folder contains OG\, Final\, Reports\, and (if any files
could not be converted) Unconverted_Files\ subfolders.

------------------------------------------------------------------
HOW OPTIONAL OFFICE/LIBREOFFICE CONVERSION WORKS
------------------------------------------------------------------

For Word (.docx/.doc) and Excel (.xlsx/.xls) files, the application
tries, in order:

  1. LibreOffice, if it is installed on this computer (best quality)
  2. Microsoft Office, if it is installed on this computer (best
     quality, Word/Excel only, .doc/.xls and .docx/.xlsx)
  3. A built-in basic renderer for modern .docx/.xlsx files only
     (text and table/cell values only -- fonts, images, and exact
     layout are NOT preserved)
  4. If none of the above can produce a result (for example, a legacy
     .doc/.xls file with neither LibreOffice nor Office installed),
     the original file is preserved and a placeholder page is used in
     its place in the output

Neither LibreOffice nor Microsoft Office is required to use this
application. Run RUN_DIAGNOSTICS.bat to see which of these are
available on this computer.

------------------------------------------------------------------
WHAT PLACEHOLDERS MEAN
------------------------------------------------------------------

If a file cannot be converted to PDF at all, the application does NOT
skip it or fail the whole job. Instead it inserts a clearly labeled
placeholder page in its place (explaining why) and keeps a full copy
of the original file in the Unconverted_Files\ folder. Nothing is ever
silently dropped.

------------------------------------------------------------------
WHERE LOGS ARE STORED
------------------------------------------------------------------

Every processing run writes its own Reports\ and Logs\ folders next to
its output. Separately, if something goes wrong before that output
folder even exists (for example, a crash at startup), a diagnostic log
is written to:

  %LOCALAPPDATA%\LenderPackageBuilder\Logs

Nothing in these logs is ever uploaded anywhere.

------------------------------------------------------------------
HOW TO REPORT A PROBLEM
------------------------------------------------------------------

1. Run RUN_DIAGNOSTICS.bat and keep the window open (or copy its text).
2. Note exactly what you were doing when the problem happened.
3. If a specific processing run failed, find its Logs\ folder (inside
   that run's output folder) and include the run.log file.
4. Share this information with whoever is supporting this application.
   Do not include real borrower documents unless specifically asked.

------------------------------------------------------------------
PROCESSING IS LOCAL -- NO INSTALLER, NO PYTHON REQUIRED
------------------------------------------------------------------

To repeat the most important points:

  - Everything runs on this computer. Nothing is uploaded.
  - No installer is used or required.
  - No separate Python installation is used or required -- the Python
    runtime this application needs is bundled inside the _internal
    folder, for this application's exclusive use only.
  - No administrator rights are required.
  - Closing the application removes nothing you have already saved.
