# Secondary-PC a266464 read-only UI bug hunt

Date: 2026-10-05 (Europe/London)

Scope: exact detached source
`a266464cc1ad544dcf9c11df2c60dccfa26a3e4d` and the locally bundled HTML
whose SHA-256 exactly matches the primary PC's supplied hash:
`CDCF8EBD83D5EF011AC55B4304C90A82A1EF991E2FEA70B67E4F288EA0D4876B`.

All HTTP and HTTPS were blocked. Fingerprints and selection functions were
stubbed in Chromium. CATalyst and Sage stayed stopped. No wallet, config,
offer, campaign, fee, or profile write occurred.

## Passes

- At 390 x 700 the startup Risk Disclosure Tab order remained inside the
  visible gate and cycled exactly:
  `Continue to wallet connection` -> `Close app` -> Continue.
- The wallet-picker modal acquired `role="dialog"`, `aria-modal="true"`, and
  `aria-labelledby="walletPickerTitle"`.
- Opening the modal moved focus to its first wallet card.
- Escape closed the modal.
- Normal-length fingerprint cards retained visible 2 px focus outlines and
  stayed inside the 390 px viewport.

## Reproducible defects

### 1. Toolbar wallet selector cannot be used from the keyboard

Post-startup `#fingerprintDisplay` is a clickable `DIV` with:

- no `tabindex`;
- no role;
- no accessible label;
- computed `tabIndex=-1`.

It is absent from the Tab order, so Enter and Space cannot open the wallet
picker. Source: `bot_gui.html` around line 9189.

Minimal reproduction:

1. Hide the startup gate using the normal completed-startup test state.
2. Tab through the toolbar.
3. Observe that wallet fingerprint display is never focused.
4. Inspect the element and confirm it is a non-focusable `DIV` with only an
   `onclick` handler.

### 2. Wallet-picker modal does not trap focus

The generalized modal handler sets dialog semantics, initial focus and Escape
closing, but does not contain Tab focus.

Observed sequence after pointer-opening the picker with one stubbed wallet:

1. wallet card (inside modal);
2. Close button (inside modal);
3. `BODY` (outside modal);
4. Dashboard button (outside modal);
5. Offers button (outside modal).

Escape then closed the modal while focus remained on the background Offers
control instead of a wallet-picker opener. This leaves keyboard users
interacting with obscured page controls behind an active modal.

### 3. Long wallet labels overflow and clip picker-card content

Stub label:

```text
HARVESTR_WALLET_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

At 390 x 700:

- card `clientWidth=269`, `scrollWidth=1222`;
- label `clientWidth=1101`, `scrollWidth=1101`;
- card bounds `left=54.6875`, `right=325.3125`;
- label bounds `left=141.6875`, `right=1242.9375`;
- computed `overflow-wrap: normal`, `word-break: normal`.

At 1280 x 900 the defect remained: card `clientWidth=614`,
`scrollWidth=1222`, and label right edge `1515.25` exceeded the viewport.
Because startup and toolbar pickers share `.fp-card`, both are affected.

Screenshot:

- `2026-10-05-a266464-long-wallet-label-overflow-390.png`
- SHA-256:
  `82DB1C0F06B3B253CC697B588C0438CC731B0F819B201A1FC392F2C26F49A85C`

### 4. Disabled Start has no programmatically associated explanation

The toolbar Start button can be disabled while a detailed visual reason is
shown in `#startupStepStartDetail`, but `#startBtn` has neither `title` nor
`aria-describedby`. Its Chromium accessibility snapshot is only:

```text
- button "▶ Start" [disabled]
```

The separate visible reason during this probe was:

```text
Start blocked: waiting for a fresh runtime safety check. Review Safety Diagnostics if this persists.
```

Because disabled buttons are not in ordinary Tab order and the reason is not
associated with the control, keyboard and screen-reader users do not receive
the reason in the button's accessible description.

## Suggested regression boundaries

- Toolbar fingerprint trigger is a named button and opens with Enter/Space.
- While `walletPickerModal` is active, Tab and Shift+Tab cycle only through
  its enabled controls; close returns focus to the trigger.
- A 100-character unbroken wallet label does not increase card scroll width,
  displace the arrow, or exceed its card at 390 and 1280 px widths.
- Every disabled Start state exposes the current `startupStepStartDetail`
  through `aria-describedby` or an equivalent accessible description.

Verdict: the original a266464 fingerprint-card keyboard fix remains PASS, but
the broader bounded UI hunt found four additional reproducible accessibility
defects.
