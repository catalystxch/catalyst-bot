# Secondary-PC 6e4d61d wallet-picker fix verification

Date: 2026-10-05 (Europe/London)

Verdict: PASS for the four scoped UI fixes. No new regression was found.

## Identity and isolation

- Required and tested source:
  `6e4d61d32702330876ce5cfe26d77401f1c873ba`.
- Remote `origin/codex/coin-prep-fee-approval` resolved to that exact commit.
- Source was checked out detached in
  `work/catalyst-pr220-6e4d61d` and ended clean.
- CATalyst and Sage were stopped before the packaged launch.
- Packaged launch used a new isolated data directory:
  `profiles/6e4d61d-ui-readonly-20261005`.
- The original Harvestr profile was not opened or changed.

## Tests

Focused browser regressions:

```text
py -3 -m pytest -q tests/e2e/test_wallet_picker_accessibility.py tests/e2e/test_fingerprint_keyboard.py --e2e
...... [100%]
6 passed in 4.97s
```

Full browser suite:

```text
py -3 -m pytest -q tests/e2e --e2e
218 passed in 147.38s (0:02:27)
```

## Clean build identity

The clean local build used Python 3.14.3 and PyInstaller 6.22.3 and completed
successfully.

- `Catalyst.exe` size: `11,586,584` bytes.
- `Catalyst.exe` SHA-256:
  `3C14470C235605DE8B4DD3AFDAD0DE3DA32D76489962C239CA429BF814BDD164`.
- Source and bundled `bot_gui.html` SHA-256:
  `FD92FD2F301DD5343C3B0C5E1F96DBB13A2626712CC71508C679D24852DA0871`.

The bundled UI was byte-identical to the source UI.

## Independent built-UI probe

All HTTP/HTTPS calls were blocked and fingerprint data was stubbed. No wallet
or configuration mutation endpoint was reached.

### Toolbar activation

- `#fingerprintDisplay` is a native `BUTTON`.
- Accessible name: `Change wallet fingerprint`.
- Enter opened the wallet picker.
- The test recorded zero non-GET requests and zero page errors.

### Modal focus trap and return

Using the real toolbar opener at 390 x 700, the observed sequence stayed
inside the modal:

```text
wallet card -> Close -> wallet card -> Close -> wallet card
```

Escape closed the modal and restored focus to the real toolbar wallet button.

### Long-label layout

A 176-character unbroken label was tested.

At 390 x 700:

- card `clientWidth=260`, `scrollWidth=260`;
- card right `320.51`;
- label right `262.74`;
- arrow right `297.59`.

At 1280 x 900:

- card `clientWidth=452`, `scrollWidth=452`;
- card right `850.65`;
- label right `795.56`;
- arrow right `828.80`.

No content overflowed or displaced the arrow at either width.

### Disabled Start explanation

Chromium's accessibility tree reported:

- role: `button`;
- name: `▶ Start`;
- disabled: `true`;
- description:
  `Start blocked: waiting for a fresh runtime safety check. Review Safety Diagnostics if this persists.`

This verifies the live `startupStepStartDetail` text is now exposed as the
button's accessible description.

## Isolated packaged launch

The exact locally built executable served the startup UI on port 5000 using
only the new isolated directory.

- `/api/sage/startup-status`: `phase=idle`, empty fingerprint,
  `preload_running=false`.
- Sage did not start.
- Risk Disclosure rendered at 1280 x 900 and 390 x 700.
- Tab focus stayed inside the startup gate and cycled Continue/Close.
- No horizontal overflow at either width.
- No non-GET browser request, console error, or page error occurred.
- No wallet connection control was used.
- The process accepted a normal window-close request; no force termination was
  needed and port 5000 was released.

## Original-profile preservation

All original profile hashes exactly matched their pre-test values:

- `bot.db`: `9DD7D388E0DDD38733284D051B862939AF2B411380973DF42F6979BB9392DD4D`
- `bot.db-wal`: `C6E7782CDF41B127AA84B0936213BDD9500E2F87258C6657BA668D7F3693BEE4`
- `bot.db-shm`: `A1AA05675CEDEB9A7B166918FE1FC0B2335EFB83AEEF3720A2D08BF2047B8BD3`
- `.env`: `A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`

No wallet, offer, campaign, fee, live configuration, or original-profile
write occurred.
