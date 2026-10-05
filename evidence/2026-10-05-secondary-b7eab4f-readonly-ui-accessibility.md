# Secondary-PC b7eab4f read-only UI/accessibility pass

Date: 2026-10-05 (Europe/London)

Scope: one bounded, independent, read-only browser pass against the packaged
`b7eab4f263409c0b4c846d6a506b21e16335ee37` candidate and the existing lean
copy of the Harvestr profile. The original CATalyst profile and PR #220 were
not modified. No wallet card, Risk Disclosure bypass, configuration control,
fee approval, campaign control, bot control, or offer control was used.

## Candidate identity

- Package ZIP SHA-256:
  `D7E5066C33477A60A944EF6E2EB7A8FA4E2E583BC0CA58E44DC83584D533050D`
- Installer SHA-256:
  `4F68B683BB1FFE0D8495E5A546A29C08E71ED2310DD48C724C9670002C0E871B`
- `Catalyst.exe` SHA-256:
  `9EB27A8DFCB15B026318F75B797B6FAD628A9D46AB44DFC49C9CE2F9AACF3C8A`
- Packaged `bot_gui.html` SHA-256:
  `1FD778D4CC109562FF69942BD705D6CB107067017445C9B5E65E3514EC50A001`
- Source commit:
  `b7eab4f263409c0b4c846d6a506b21e16335ee37`

## Environment and safe boundary

- CATalyst was launched from the exact extracted package with `CMM_DATA_DIR`
  scoped to
  `profiles/b7eab4f-harvestr-copy-20261005` for the child process only.
- Sage 0.13.0 was launched for the pass.
- The normal Risk Disclosure controls were used; no DOM or API bypass was
  used.
- Startup reached `waiting_fingerprint` and displayed one wallet:
  `Harvestr test wallet`, fingerprint `3702373391`.
- The visible CAT identity was wallet ID 2, asset ID
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
  (`MZ_XCH`, 3 decimals).
- CATalyst remained stopped. The read-only final status showed zero open
  offers, zero pending cancels, zero locked XCH/CAT, zero blocking operations,
  zero reservations, and zero publication claims.
- The fingerprint card was not clicked. Its normal endpoint,
  `POST /api/sage/fingerprint`, persists `SAGE_FINGERPRINT`, so selecting it
  would have violated the delegated read-only/config-no-write boundary.

## Results

Passes:

1. Risk Disclosure had no horizontal overflow at desktop or 390 x 700.
2. Risk Disclosure content scrolled normally at 390 x 700.
3. Continue and Close had keyboard focus and a visible 2 px focus outline.
4. The fingerprint screen had no horizontal overflow at 390 x 700. The card
   stayed entirely inside the viewport (`left=54.6875`, `right=325.3125`,
   width `270.625`; viewport width `390`).
5. The fingerprint screen had a usable vertical scroll region
   (`scrollHeight=950`, `clientHeight=700`).
6. The wallet card received keyboard focus and displayed a 2 px focus outline.
7. No browser page error or console error occurred in the tested startup flow.
8. Only the expected normal startup request was observed before the card test:
   `POST /api/wallet/begin-startup`. Enter and Space caused no POST.
9. CATalyst and Sage both accepted `CloseMainWindow()` and exited; no process
   or listener remained on ports 5000 or 9257.
10. The original profile hashes remained byte-for-byte unchanged after the
    pass:
    - `bot.db`: `9DD7D388E0DDD38733284D051B862939AF2B411380973DF42F6979BB9392DD4D`
    - `bot.db-wal`: `C6E7782CDF41B127AA84B0936213BDD9500E2F87258C6657BA668D7F3693BEE4`
    - `bot.db-shm`: `A1AA05675CEDEB9A7B166918FE1FC0B2335EFB83AEEF3720A2D08BF2047B8BD3`
    - `.env`: `A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`

Failure:

### Keyboard-only wallet selection is impossible

The wallet card is rendered as a `DIV` with `tabindex="0"`, no `role`, no
`aria-label`, and an `onclick` handler only. With the Harvestr card focused:

- Enter sent no request, left `#startupFpSection` visible, and did not show
  `#startupStartingFeedback`.
- Space sent no request, left `#startupFpSection` visible, and did not show
  `#startupStartingFeedback`.

Source location: `bot_gui.html` lines 38336-38343 in the packaged source tree.
The smallest safe repair is to use a semantic `button` for each card, or add
button semantics plus Enter/Space handling. A regression should assert both
keyboard keys invoke the same selection function as a pointer click exactly
once, while preserving the existing focus treatment.

Evidence screenshot:

- `2026-10-05-secondary-b7eab4f-wallet-card-keyboard-mobile.png`
- SHA-256:
  `F5879BDECCCEBFAB7A34A46E14E1FCF74014AD6B09BBE01E21B133FB9B9A2783`

## Limitation

The rest of the Dashboard, Offers, P&L, Market Intel, Settings, Logs, Data
Reset, Help, About, and Doctor views could not be reached through the normal
startup flow without selecting the fingerprint. Because that normal action
persists configuration, the delegated read-only pass stopped at this boundary
instead of bypassing the startup gate. The earlier hydrated Harvestr-copy
evidence remains the coverage for those views.

Summary: 10 checks passed, 1 reproducible defect failed, and the post-startup
tab sweep was blocked by the explicit no-configuration-write boundary.
