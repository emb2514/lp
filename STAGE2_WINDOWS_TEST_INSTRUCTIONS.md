# Stage 2 Windows Test Instructions (for a non-programmer)

This guide explains how to try the new **desktop window** version of
Lender Package Builder on your Windows 11 computer. It assumes you have
never used Command Prompt, Python, or any developer tool before.

If you already set up the project for Stage 1 (the command-line
version), you can skip straight to Step 3.

---

## Step 1: Download and extract the updated project

1. Get the latest copy of the project folder (however it was shared
   with you -- as a ZIP download or an updated folder).
2. If it's a ZIP file: right-click it and choose **Extract All...**,
   pick a normal location like your Desktop or Documents folder, and
   click **Extract**.
3. Open the extracted folder. You should see files including
   `README.md`, `SETUP_AND_TEST.bat`, `RUN_STAGE1.bat`, and the new
   **`RUN_GUI.bat`**.

If you already have an existing copy of this project from Stage 1,
replace it with the new files (or extract the new ZIP over the same
location), keeping the same folder name.

## Step 2: Run the setup script

1. Double-click **`SETUP_AND_TEST.bat`**.
2. A black window (Command Prompt) opens and starts printing text --
   this is normal.
3. The first run needs an internet connection; it now also downloads
   the desktop interface components (a toolkit called "PySide6/Qt"),
   so it may take a few minutes longer than before.
4. If Windows shows a "Windows protected your PC" SmartScreen popup,
   click **More info**, then **Run anyway**.
5. You do not need to click "Run as administrator" -- a normal
   double-click is correct.

### What successful test output looks like

Near the end of the window you should see a long list of lines ending
in `PASSED`, followed by:

```
============================================================
 ALL TESTS PASSED
============================================================

Setup is complete and the application is working correctly
on this computer.

Next: double-click RUN_GUI.bat to open the desktop application,
or see STAGE2_WINDOWS_TEST_INSTRUCTIONS.md for a full walkthrough
(FIRST_TEST_INSTRUCTIONS.md covers the command-line version).
```

Press any key to close the window. If you instead see
`SOME TESTS FAILED`, follow "How to report an error" at the bottom of
this guide before continuing.

## Step 3: Launch the desktop application

Double-click **`RUN_GUI.bat`**.

A small black window may flash briefly -- that's normal, it's only
there to show error messages if something goes wrong. The actual
application window should then appear.

### What the initial window should look like

- A title at the top: **Lender Package Builder**, with a subtitle
  underneath and a small **"Local processing only"** badge in the top
  right corner.
- A large box in the middle with dashed borders that says
  **"Drop one lender ZIP, folder, or document here"**, with
  **Browse File** and **Browse Folder** buttons underneath it.
- A **Build Lender Packages** button near the bottom, greyed out
  (disabled) until you choose something to process.

If the window looks like this, everything is working correctly.

## Step 4: Create a harmless test ZIP file

Before trying anything real, create a small, throwaway test ZIP:

1. Create a new folder anywhere (e.g. on your Desktop) named
   `test_docs`.
2. Put 2-3 unimportant files in it -- for example, open Notepad, type a
   sentence, and save it as `note1.txt` and `note2.txt`. You can also
   add any harmless PDF or photo you have lying around.
3. Right-click the `test_docs` folder and choose **Send to** >
   **Compressed (zipped) folder**. This creates `test_docs.zip`.

## Step 5: Drag your test ZIP into the app

1. Open the folder containing `test_docs.zip` in a normal Windows
   Explorer window, side by side with the Lender Package Builder
   window.
2. Drag `test_docs.zip` and drop it onto the dashed box in the
   application.
3. If dragging is inconvenient, click **Browse File** instead and pick
   `test_docs.zip` from the file picker.

You should see the dashed box replaced by a summary card showing the
file name, its full path, its type, and its size. A moment later, an
estimate of its contents appears too. The **Build Lender Packages**
button should now be enabled (no longer greyed out).

## Step 6: Begin processing

Click **Build Lender Packages**.

The window switches to a processing view showing:

- The current stage (e.g. "Converting documents")
- A progress bar
- The current file being worked on
- A scrolling list of recent activity

For a tiny test ZIP like this, processing should finish in well under
a second.

## Step 7: Find your completed output

When processing finishes, the window shows a green **"Lender packages
built successfully"** banner (or an amber "Completed with items to
review" banner if something needed a placeholder -- both are normal,
successful outcomes) along with a summary of what happened: how many
documents were found, how many exact duplicates were removed, page
counts, and how many integrity checks passed.

A new folder appears **next to your test ZIP** (in the same folder as
`test_docs.zip`), named something like:

```
test_docs_Lender_Package_Output_20260101_143000
```

## Step 8: Which buttons open the Final package and reports

On the completion screen:

- **Open Output Folder** -- opens the whole output folder (OG, Final,
  Reports, Unconverted_Files, Logs).
- **Open Final Package Folder** -- opens directly to the `Final`
  folder, which may contain one or several PDF files (large packages
  are split into numbered parts; a small test ZIP will just have one).
- **Open Reports** -- opens the `Reports` folder. Open
  `Processing_Report.txt` in Notepad first.

## Step 9: How to verify the integrity-check result

On the completion screen, look at **"Integrity checks passed"** --
for a fully successful run it should read something like `22/22`
(all checks passed). You can also open
`Reports\Processing_Report.txt` and scroll to the bottom: every line
should start with `[PASS]`, ending in `OVERALL RESULT: SUCCESS`.

If the application ever shows a failure screen instead (a red
banner), it means something did not complete correctly -- see
"How to report an error" below.

## Step 10: Testing a larger, real lender package

Only after your small test ZIP succeeds:

1. Make a **copy** of a real lender ZIP -- never point the application
   at your only copy of something important.
2. Click **Process Another Package** to return to the start screen.
3. Drag (or browse to) the copied ZIP the same way as before.
4. If the package is large, you may see an amber notice that
   processing may take longer and use more disk space -- this is
   informational, you can continue.
5. If the package is unusually large (beyond the built-in safety
   threshold), a dialog will ask you to explicitly confirm before
   continuing. Read it, and only continue if you recognize the
   package as a real, intentional large lender file.
6. Click **Build Lender Packages** and wait for it to finish. Larger
   packages take longer -- the activity log will keep scrolling to
   show it is still working.

## What NOT to worry about

- Closing the window is blocked with a warning while a package is
  being built -- this is intentional, so a package is never left half
  written. Just wait for it to finish.
- The advanced "Maximum pages per output part" / "Maximum size per
  output part (MB)" settings are hidden behind a collapsed **Advanced
  Settings** section. You do not need to open or change them --
  the built-in defaults (750 pages / 100 MB) work well for most
  packages, and the whole point of those numbers is that no document
  is ever split to fit them.

## How to report an error

If setup fails, the app doesn't open, or a package shows a failure
screen:

1. If it's a failure screen inside the app: click **"Technical
   details"** to expand it, then click **Copy Error Details** and
   paste that into your message to Claude Code.
2. If a black Command Prompt window showed an error (during setup or
   while trying to launch `RUN_GUI.bat`): click inside it, press
   **Ctrl+A** then **Ctrl+C** to copy all the text, and paste that in.
3. Mention what you were doing when it happened (e.g. "I dragged a ZIP
   onto the app and clicked Build").
4. If a `Reports\Processing_Report.txt` file exists for that run,
   mention it too -- you may be asked to paste its contents.

You do not need to understand any of the text yourself -- just copy
and paste it exactly as shown.
