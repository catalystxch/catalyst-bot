# Secondary-PC a266464 fingerprint keyboard verification

Date: 2026-10-05 (Europe/London)

Scope: independent, bounded verification of the keyboard-accessibility fix
reported at commit `a266464cc1ad544dcf9c11df2c60dccfa26a3e4d`. No
wallet, configuration, offer, campaign, fee, or live profile action was
performed.

## Identity

- Remote `origin/codex/coin-prep-fee-approval` resolved exactly to
  `a266464cc1ad544dcf9c11df2c60dccfa26a3e4d`.
- Verification checkout:
  `work/catalyst-pr220-a266464`, detached at the exact commit.
- Source and locally bundled `bot_gui.html` SHA-256:
  `CDCF8EBD83D5EF011AC55B4304C90A82A1EF991E2FEA70B67E4F288EA0D4876B`.
  This exactly matches the primary PC's supplied bundled-UI hash.
- Primary PC supplied clean-build EXE SHA-256:
  `F2A9475CF9DC3A0346F351C56468791F539772B87C52C9489C7C160ADCC794B1`.
- A clean local build used Python 3.14.3 and PyInstaller 6.22.3. Its EXE
  SHA-256 was
  `8E294E62F279931EAC5483A4BFB3FDCE0094A113CE617FB20C7259A1BD239492`,
  so that locally built executable was not launched or represented as the
  primary package. Its bundled UI was byte-identical to the supplied UI hash.

## Automated regression

Command:

```text
py -3 -m pytest -q tests/e2e/test_fingerprint_keyboard.py --e2e
```

Result: `2 passed in 3.44s`.

The regression covers both `startupShowFingerprints` and
`showWalletPickerModal`, with wallet calls stubbed.

## Independent Chromium probe

The independent probe loaded the byte-identical locally bundled HTML from
`dist/Catalyst/_internal/bot_gui.html`, blocked HTTP/HTTPS, replaced selection
functions with in-memory recorders, and tested at 390 x 700.

Both the startup picker and toolbar picker passed all checks:

1. Exactly one element was exposed through the accessibility tree as a button
   named `Harvestr test wallet 3702373391 →`.
2. The element was a native `BUTTON` with `type="button"`.
3. Enter caused exactly one recorded selection of `3702373391`.
4. Space caused exactly one additional recorded selection of `3702373391`.
5. No non-GET network request occurred.
6. Focus was visible with a 2 px solid outline.
7. The card stayed fully inside the 390 px viewport.

No further defect was found in the scoped startup/toolbar fingerprint-picker
fix.

## Safety and cleanup

- CATalyst and Sage remained stopped throughout this verification.
- The exact source checkout ended clean and detached at the required commit.
- The original CATalyst profile stayed byte-for-byte unchanged:
  - `bot.db`: `9DD7D388E0DDD38733284D051B862939AF2B411380973DF42F6979BB9392DD4D`
  - `bot.db-wal`: `C6E7782CDF41B127AA84B0936213BDD9500E2F87258C6657BA668D7F3693BEE4`
  - `bot.db-shm`: `A1AA05675CEDEB9A7B166918FE1FC0B2335EFB83AEEF3720A2D08BF2047B8BD3`
  - `.env`: `A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`

Verdict for the scoped fix: PASS. Exact primary executable-package launch
remains unverified on this PC because no file matching the supplied EXE hash
was available locally.
