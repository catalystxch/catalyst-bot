# Secondary 61be438 isolated package evidence manifest

- Source candidate: `61be438d67c015c6f49ee4d401c34266cb6e8091`
- Parent artifact commit: `3792fa66f88f2e679c8a319f458097b7346a4193`
- Test date: `2026-10-06` (Europe/London)
- Scope: isolated, mock-Sage, no live wallet effects

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `REPORT.md` | 5,044 | `A1AAC7192C0CA902D90A935DBF18DB36F3BEE4E3762067DE31F30E7D348D3165` |
| `packaged-ui-result.json` | 550 | `EBF37F16233924C64A3CEBB21A12A7EAFC80003D62CDC5BFB68AE36668829888` |
| `packaged-ui-final.png` | 274,105 | `FAFA294417F4FCD9132A5FD703B2DBA4FC741A6C5787545CC7D661AFD505F20B` |

The report deliberately preserves the original cbd7d08 monitor's two
`unexpected_catalyst_process_count` alerts. They were recorded while the
requested isolated 61be438 package processes ran concurrently. They are
historical harness evidence and are not represented as a clean final-candidate
monitor window.
