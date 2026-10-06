# CATalyst 19ded88 primary package checkpoint

Source: `19ded8889582d0ede56a6cd49c8e327db84f99a0` on draft PR #220.

This candidate fails closed when the canonical user data directory cannot be
created. It cannot select `.env` or `bot.db` from the installation directory.
The isolated regression first failed on the old behavior, then passed with the
fix. The complete serial Windows backend passed 7,281 tests, with 232 skipped
and 433 subtests passed. Repository-wide Ruff check and format passed.

A clean detached PyInstaller build produced the EXE in the accompanying ZIP.
The bundled `bot_gui.html` has the same SHA-256 as the source HTML. The 192-file
ZIP passed CRC, contains the exact EXE, and contains no `.env`, `bot.db`, WAL,
SHM, or migration marker. Isolated packaged API, synthetic Sage RPC,
publication recovery, and native clean/duplicate/persisted/safety smokes
passed. A blocked data-directory package smoke entered read-only diagnostics;
after stopping the isolated process, no install-side profile file, test
listener, or test process remained.

The unsigned installer compiled from the same bundle. A unique-AppId,
current-user QA install placed the exact EXE in an isolated E: directory. Its
installed API smoke passed; uninstall removed the installed EXE and the QA
registration. Defender custom scans of the bundle, ZIP, and installer added
zero detections.

This is a package checkpoint, not release approval. PR #220 remains draft.
The exact candidate has not completed original TEST 7 live acceptance or its
24-hour stability windows. Active-offer lifecycle and recovery, secondary
original-profile acceptance, final installer/update acceptance, and final
review remain open. No new campaign or fee approval exists.
