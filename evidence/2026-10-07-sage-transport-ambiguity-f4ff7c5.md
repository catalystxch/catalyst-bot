# Sage response-loss replay and final mutation recheck

Exact runtime/source: `f4ff7c50ea5202ecb36c65b6d172e8b026ccf07a`.
The test-only child `2f8e05b358bc8e7d08068fceebf07cbba5cd8572`
updates older fake RPC signatures; it does not change runtime files.

## Defects and corrections

Sage RPC uses HTTP POST for reads and wallet effects. The transport helper
previously retried every endpoint after a connection exception. If Sage had
accepted a wallet-effect request and the response was lost, the retry could
send the same effect a second time. A fake Sage connection that accepted
`submit_transaction`, `send_xch`, or `make_offer` before losing the response
reproduced a second POST in three failing regressions. `_sage_post` now retries
only an explicit set of read endpoints. Unknown and wallet-effect endpoints
fail closed after an ambiguous transport failure. A read-only
`get_sync_status` request still retries successfully.

The preceding candidate completed TLS connection before its final mutation
lease check, but high-level Sage wallet-effect functions did not all forward
their `_identity_recheck` callback into `rpc`. A delayed connection in
`send_transaction` or `split_coins_rpc` reproduced an effect being sent after
a simulated lease expiry. The callback now reaches the transport boundary for
all literal mutating `rpc` calls. Broad exception handlers in initialization,
message signing, and change-address selection re-raise `MutationBlocked`.
Both delayed-connection regressions turned green and observed zero sends.

The first complete backend run on the runtime source reached 7,370 passing
tests, with 246 skipped and 447 subtests, but six older RPC test doubles
rejected the new `_identity_recheck` keyword. The test-only child corrected
those signatures. The affected wallet suites passed 264 tests and two
subtests. The complete serial Windows backend rerun on that child passed
**7,376 tests, 246 skipped, 447 subtests** in 20 minutes 33 seconds. Ruff
check, format check, `git diff --check`, and all 11 PR checks passed.

Test-only descendant `9ab681a5adc34793b294bb6e7644d3de5bb156ad`
adds a regression for an uncertain Coin Prep split dispatch: the source coin
remains claimed against both the original operation and a different retry
operation ID. The selected replacement/split suites passed 97 tests. Its
complete serial Windows backend run passed **7,377 tests, 246 skipped, 447
subtests** in 27 minutes 17 seconds (exit code 0), and all 11 PR checks passed
on that exact head. No runtime or packaged file changed after `f4ff7c5`.

## Clean Windows package

Built from a clean detached worktree at the runtime commit:

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `923F2587CAACBC56ADE2B146B30B6B401B2815F5CF16E3716B71CCA43E132015` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `CD2ACD60C9499B1A950DEB2345183B6BC1ADEACF3405BE9D222E54532CA7CBE9` |
| Unsigned installer | `C3A27E32F0B3B2C3ABBAA645E925FADB0F4DA583F92BE7985C6E07EEC3734242` |

The package passed API, synthetic Sage RPC, publication-recovery, and native
clean/duplicate/persisted/safety smokes. The 192-entry ZIP passed CRC and
embedded-EXE checks; its extracted EXE passed API and synthetic Sage smokes.
A unique-AppId QA installer clean-installed on E:, produced the exact EXE
hash, passed installed API and Sage smokes, then uninstalled with no remaining
EXE or QA registry key. A second isolated QA cycle installed the older
`eadb82a` EXE, upgraded it at the same `1.4.0` version to the exact
`f4ff7c5` EXE, passed installed API and Sage smokes, and uninstalled without
leaving an EXE or QA registry key. Defender real-time protection was enabled,
and custom EXE, ZIP, and installer scans produced no new detection.

The [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2a919419b75c42da2df1bb7a35560c9a6c489ce6/acceptance-artifacts/CATalyst-f4ff7c5-primary-acceptance.zip),
[installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2a919419b75c42da2df1bb7a35560c9a6c489ce6/acceptance-artifacts/Catalyst-Setup-f4ff7c5-1.4.0.exe),
and manifest are pinned at artifact commit
`2a919419b75c42da2df1bb7a35560c9a6c489ce6`. Independent HTTP downloads
of both binaries matched the hashes above. These are acceptance artifacts,
not a release.

The original TEST 7 process still runs the older `eadb82a` package in a
stopped, zero-offer, owned-lease state. This new source has not run against
that original profile. The historical Veeam-overlap 24-hour failure remains
unresolved. Live active-offer lifecycle/recovery, secondary exact-candidate
original-profile acceptance, both final-candidate 24-hour windows, and final
review remain open. PR #220 remains draft.
