# Windows Acceptance Test Checklist -- Lender Package Builder RC2

This checklist is for testing the portable Windows build on a real
Windows 11 computer. You do not need any programming experience to
follow it -- just follow each step in order and record what happens.

**Why this matters:** automated testing (including on GitHub Actions'
own Windows build machines) has already passed, but that is not the
same as running on a real physical computer with a real screen, a real
antivirus product, and real user interaction. This checklist is the
step that turns a "release candidate" into something the project owner
can confidently call finished.

---

## Before you start: record your environment

Fill this in first -- it helps explain any results that differ from
what's expected.

| Item | Your answer |
|---|---|
| Windows edition/build (Settings > System > About) | |
| Is Microsoft Office installed? (Yes/No, version if known) | |
| Is LibreOffice installed? (Yes/No, version if known) | |
| Antivirus product in use, if known | |
| Is this a personal or company-managed computer? | |

---

## Checklist

1. **Download the portable ZIP**
   - [ ] Downloaded the `LP_Builder_..._Windows_x64_Portable.zip` file
         from the location provided to you (the exact name includes the
         version label and a short build identifier, unique per build).

2. **Verify the checksum when practical**
   - [ ] Open PowerShell in the folder containing the downloaded ZIP.
   - [ ] Run: `Get-FileHash .\<the .zip filename> -Algorithm SHA256`
   - [ ] Compare the printed hash to the value in the matching
         `..._Portable_SHA256.txt` file next to it. They must match
         exactly.

3. **Extract the complete folder**
   - [ ] Right-click the ZIP > "Extract All..." to a normal folder
         (e.g. Desktop or Documents). Do not run anything from inside
         the ZIP viewer itself.

4. **Keep `_internal` and all files together**
   - [ ] Confirm the extracted folder contains `LenderPackageBuilder.exe`
         AND a `_internal` folder side by side. Do not separate them.

5. **Run `TEST_PORTABLE_APP.bat`**
   - [ ] Double-click it. A command window opens and runs several
         automated checks against the built .exe itself.

6. **Confirm the self-test says PASS**
   - [ ] Result: PASS / FAIL (circle one). If FAIL, stop here and
         report the output.

7. **Launch `LenderPackageBuilder.exe`**
   - [ ] Double-click it directly (not through the .bat file).

8. **Confirm no Python installation prompt appears**
   - [ ] Yes, none appeared / No, one appeared (describe below).

9. **Confirm no administrator prompt appears**
   - [ ] Yes, none appeared / No, one appeared (describe below).

10. **Confirm the GUI opens without a black console window**
    - [ ] Only the application window appeared -- no separate black
          command-line window stayed open.

11. **Test the bundled synthetic sample package**
    - [ ] Drag `Sample_Test_Package.zip` (from this folder) onto the
          open application window, or use "Browse File".
    - [ ] Click "Build Lender Packages".

12. **Confirm OG, Final, reports, and placeholders match the documented expectation**
    - [ ] Compare your results to
          `Sample_Test_Package_Expected_Results.txt`. They should match
          exactly (document counts, duplicate count, PASS/FAIL result).

13. **Close and reopen the app several times**
    - [ ] Closed and relaunched at least 3 times without errors.

14. **Test dragging a ZIP into the open window**
    - [ ] With the app already open, drag any test ZIP onto the window.
          It should be accepted the same way as "Browse File".

15. **Test dragging a ZIP onto the executable**
    - [ ] With the app CLOSED, drag a ZIP file directly onto
          `LenderPackageBuilder.exe`'s icon. The app should open with
          that file already selected, WITHOUT starting processing
          automatically. You should still have to click
          "Build Lender Packages" yourself.

16. **Test Browse File and Browse Folder**
    - [ ] Both buttons open a normal Windows file/folder picker and
          correctly select what you choose.

17. **Test a path containing spaces**
    - [ ] Copy the whole application folder to a location with a space
          in the path (e.g. `C:\Users\Your Name\Lender Package Builder Test\`)
          and confirm it still launches and processes correctly from
          there.

18. **Test advanced maximum settings**
    - [ ] Expand "Advanced Settings" before building and confirm you
          can change the maximum pages/size per part and that the
          build respects your changed values.

19. **Test a real lender ZIP only as a local copy after the synthetic test passes**
    - [ ] Only after steps 11-12 pass, optionally test with a real
          (already-authorized, locally copied) lender package if you
          have one available. Do not do this before the synthetic test
          passes.

20. **Review `Processing_Report.txt`**
    - [ ] Open it (in the run's `Reports\` folder) and confirm it reads
          clearly and matches what you saw in the app.

21. **Confirm all integrity checks say PASS**
    - [ ] Every line in the integrity checks section of the report (or
          the app's result screen) says PASS.

22. **Confirm no source document was split**
    - [ ] Spot-check that no source document appears partially in one
          output part and partially in another.

23. **Confirm every removal in `Duplicate_Removal_Log.txt` is explained**
    - [ ] RC2 adds content-aware duplicate detection on top of exact
          byte-for-byte matching -- `Duplicate_Removal_Log.txt` now has
          separate sections for exact-byte duplicates AND content-aware
          duplicates (same visible content despite different file
          bytes). Confirm every entry, in every section, has a clear
          reason and a Retained/Removed filename pair that makes sense
          for your input. A document should never be listed as removed
          without an explanation.
    - [ ] If your input included a large merged PDF plus a standalone
          copy of something already inside it, check
          `Merged_Document_Overlap_Report.txt` for the containment
          explanation instead.

23a. **Test the "Review Uncertain Matches" screen (RC2)**
    - [ ] If the result screen shows a "Review Uncertain Matches"
          button, click it. Confirm it opens without error, and that
          every listed item defaults to "Keep Both" (nothing pre-selects
          an exclusion).
    - [ ] Confirm clicking "Apply Decisions" with everything left on
          "Keep Both" changes nothing (no confirmation popup appears,
          and reopening Final shows the same documents as before).
    - [ ] Pick one item, select "Mark as duplicate to exclude" for one
          document, and click "Apply Decisions." Confirm a popup asks
          you to confirm before anything happens, and that clicking
          "No" leaves everything unchanged.
    - [ ] Repeat and click "Yes" this time. Confirm the chosen document
          is removed from the Final package, and that
          `Uncertain_Match_Review_Log.txt` (in the Reports folder)
          records your decision, the document you chose, and a
          timestamp.
    - [ ] Confirm the OG package still contains every document,
          including the one you just excluded from Final.

24. **Confirm output folders open correctly**
    - [ ] The "Open Output Folder" (or similar) button/link in the app
          opens the correct folder in Windows Explorer.

25. **Record any SmartScreen or company-security warning**
    - [ ] Warning seen: ______________________________________________
    - [ ] Exact wording, if possible: ________________________________

26. **Do not bypass company security policy**
    - [ ] Confirmed: if this is a company-managed computer and a
          warning blocked the app, you contacted IT rather than working
          around the block yourself.

27. **Provide the diagnostic report and local logs when reporting an error**
    - [ ] If anything above failed, ran `RUN_DIAGNOSTICS.bat` and saved
          its output alongside your report.

---

## Record your results

| Item | Value |
|---|---|
| Input package size (source ZIP) | |
| Source file count | |
| Total pages (approx.) | |
| Runtime (start to finish) | |
| Result (Success / Warning / Failure) | |
| Errors or warnings seen | |

---

## What to do next

- **Everything passed:** report back to the project owner with this
  completed checklist. Final `v1.0.0` publication still requires their
  explicit review and approval -- this checklist does not auto-approve
  anything.
- **Something failed:** stop, save the diagnostics output and any
  relevant `Logs\run.log` file, and report the failure with as much
  detail as you can (which step, what you saw, your environment table
  above).
