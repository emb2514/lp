# First Test Instructions (for Windows, written for a non-programmer)

> **A desktop window version now exists.** Most people should use
> **STAGE2_WINDOWS_TEST_INSTRUCTIONS.md** instead of this file --
> it covers `RUN_GUI.bat`, a normal drag-and-drop window with no
> command line involved. This file (`FIRST_TEST_INSTRUCTIONS.md`)
> covers the original command-line version (`RUN_STAGE1.bat`), which
> still works and is still fully supported.

This guide assumes you have never used Command Prompt, Python, or any
developer tool before. Follow the steps in order. If anything on your
screen doesn't match what's described here, skip to "How to report a
problem" at the bottom.

---

## Step 1: Get the project folder onto your computer

You should have received this project as a single folder (or a ZIP
file containing a folder) named something like `lender-package-builder`.

- If you have a ZIP file: right-click it and choose **Extract All...**,
  then choose a simple location like your Desktop or Documents folder,
  and click **Extract**.
- If you already have a plain folder, just make sure it's somewhere
  normal like your Desktop or Documents -- not inside another ZIP file.

You should end up with a normal folder that contains files like
`README.md`, `SETUP_AND_TEST.bat`, and `RUN_STAGE1.bat`.

## Step 2: Run the setup script

1. Open that folder.
2. Double-click **`SETUP_AND_TEST.bat`**.
3. A black window (Command Prompt) will open and start printing text.
   This is normal -- it is not an error.
4. The first time you run it, it needs to download some files it
   depends on, so it will take a few minutes and requires an internet
   connection. Just wait.
5. If Windows shows a "Windows protected your PC" SmartScreen popup,
   click **More info**, then **Run anyway**. (This happens because the
   file is new/unsigned, not because anything is wrong.)
6. You do **not** need to click "Run as administrator." Regular
   double-click is correct.

### What successful output looks like

Near the end of the window, you should see a block that looks like
this:

```
============================================================
 ALL TESTS PASSED
============================================================

Setup is complete and the application is working correctly
on this computer.
```

Above that, you'll see a long list of lines ending in `PASSED` -- one
for every automated test. Seeing `PASSED` repeated many times, and no
line saying `FAILED`, means everything is working.

The window will end with `Press any key to continue . . .` -- press
any key to close it.

If instead you see **`SOME TESTS FAILED`**, do not continue to Step 3.
Go to "How to report a problem" below.

## Step 3: Create a harmless test ZIP file

Before trying this on anything real, create a small, throwaway test
ZIP so you can see how the tool works with zero risk:

1. Create a new folder anywhere, e.g. on your Desktop, named `test_docs`.
2. Put 2-3 unimportant files into it -- for example, open Notepad,
   type a sentence, and save it as `note1.txt` and `note2.txt` inside
   that folder. You could also copy in any harmless PDF or photo you
   have lying around.
3. Right-click the `test_docs` folder and choose **Send to** > **Compressed
   (zipped) folder**. This creates `test_docs.zip` next to it.

That ZIP is now a safe, disposable test package.

## Step 4: Run the tool on your test ZIP

Drag `test_docs.zip` from its folder and drop it directly onto
**`RUN_STAGE1.bat`** (drop it on the file icon itself, inside the
project folder).

A black window will open, show a short progress log, and finish with a
summary that ends in:

```
OVERALL RESULT: SUCCESS
```

Press any key to close the window.

## Step 5: Find your results

A new folder will appear **next to your test ZIP** (i.e., in the same
folder as `test_docs.zip`), named something like:

```
test_docs_Lender_Package_Output_20260101_143000
```

(The numbers are the date and time the tool ran.)

Open it. Inside you'll find:

- **`OG`** -- the complete package, every document included.
- **`Final`** -- the same, with exact duplicate files removed.
- **`Reports`** -- read this first (see below).
- **`Unconverted_Files`** -- originals of anything that couldn't be
  converted (should be empty for a simple test ZIP).
- **`Logs`** -- technical logs; you generally won't need these.

## Step 6: Which reports to open

Open **`Reports\Processing_Report.txt`** in Notepad (right-click it,
**Open with** > **Notepad**, or just double-click it).

Scroll to the very bottom. You should see:

```
OVERALL RESULT: SUCCESS
```

Above that is a list of checks, each starting with `[PASS]`. Every
single one should say `PASS`. If any say `FAIL`, something is wrong --
see "How to report a problem" below.

You can also open **`Reports\Duplicate_Removal_Log.txt`** to see
exactly which files (if any) were treated as exact duplicates and why.

## Step 7: Understanding PASS / FAIL

- **`[PASS]`** next to a check means that specific safety or accuracy
  rule was verified and held true for this run.
- **`[FAIL]`** means something did not match expectations, and the
  tool will report `OVERALL RESULT: FAILURE` rather than pretending
  everything is fine.
- The tool is intentionally strict: if even one check fails, it will
  not claim success.

## Step 8: Always test with copies, never originals

Before running this on a real lender package:

- **Always copy** the ZIP or folder first, and run the tool on the
  copy. Never point it at your only copy of something important.
- The tool never modifies or deletes your original files (this is
  verified automatically by one of the integrity checks), but keeping
  a habit of using copies costs nothing and removes all risk.
- Do not use real borrower/personal data for your *first* few test
  runs -- use the harmless `test_docs.zip` style test from Step 3
  until you're comfortable with how the tool behaves.

When you are ready to try a real (but still copied) lender ZIP, you can
use `RUN_ACCEPTANCE_TEST.bat` the same way you used `RUN_STAGE1.bat` in
Step 4 -- it runs the exact same engine with the default settings.

## How to report a problem back to Claude Code

If setup fails, a test fails, or a real run fails:

1. Do not close the black window yet.
2. Click inside the window, press **Ctrl+A** to select all the text,
   then **Ctrl+C** to copy it.
3. Paste that text (Ctrl+V) into your message to Claude Code, along
   with a short description of what you were doing (e.g., "I ran
   SETUP_AND_TEST.bat and this is what happened").
4. If a `Reports\Processing_Report.txt` file exists, mention that too
   -- Claude Code may ask you to paste its contents as well.

You do not need to understand any of the text yourself -- just copy and
paste it exactly as shown.
