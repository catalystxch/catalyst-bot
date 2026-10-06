# Secondary 61be438 isolated package evidence manifest

- Source candidate: `61be438d67c015c6f49ee4d401c34266cb6e8091`
- Parent artifact commit: `3792fa66f88f2e679c8a319f458097b7346a4193`
- Test date: `2026-10-06` (Europe/London)
- Scope: isolated, mock-Sage, no live wallet effects

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `REPORT.md` | 5,034 | `5A202A8B6317A1098397DFC732640AFB06EDF40117D891DCF1B48B9DE42E664E` |
| `packaged-ui-result.json` | 576 | `317BB65ECC8FFF6F19ABA62DB2EF5E6225E2364F37181A84B3DDC886EA035C7F` |
| `packaged-ui-final.png` | 274,105 | `FAFA294417F4FCD9132A5FD703B2DBA4FC741A6C5787545CC7D661AFD505F20B` |

The report deliberately preserves the original cbd7d08 monitor's two
`unexpected_catalyst_process_count` alerts. They were recorded while the
requested isolated 61be438 package processes ran concurrently. They are
historical harness evidence and are not represented as a clean final-candidate
monitor window.
