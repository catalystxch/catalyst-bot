# Privacy policy

CATalyst is local-first desktop software. The CATalyst project does not operate an analytics, telemetry, advertising, account, or cloud-storage service. It does not automatically upload crash reports or diagnostic bundles to CATalyst maintainers.

CATalyst does communicate with wallet, market, peer-to-peer, blockchain, font, and software-update services as part of features requested or enabled by the operator. Those services receive the network address of the computer making the request and the public identifiers or payloads needed to answer it. Their own privacy policies and retention practices apply.

## Local data

By default, writable data is stored under `%APPDATA%\Catalyst` on Windows, `~/Library/Application Support/Catalyst` on macOS, and `~/.local/share/Catalyst` on Linux. The `CMM_DATA_DIR` environment variable can override this location.

Local data can include:

- the `.env` settings file, including wallet certificate paths and optional third-party API keys;
- the SQLite database and its WAL files, containing offer, fill, transaction, coin-management, settings, and P&L records;
- application, crash, runtime, and coin-prep logs;
- coin-prep, protected-offer, cancellation, window-state, migration, and recovery sidecars; and
- local database backups and user-created diagnostic bundles.

The Windows uninstaller removes the installed program but deliberately leaves `%APPDATA%\Catalyst` so an upgrade or reinstall preserves settings and trading history. An operator who wants a full local deletion must close CATalyst and Sage, uninstall CATalyst, and remove that data directory manually after keeping any records they need.

## Network communications

### Sage wallet

CATalyst connects to Sage's JSON-RPC service on loopback by default at `https://127.0.0.1:9257`. It requests wallet identity, synchronization, balances, coins, addresses, offers, and transaction information. When the operator runs coin prep, creates or cancels an offer, starts the bot, or performs another wallet action, CATalyst asks Sage to construct, sign, or submit the corresponding operation. Private wallet keys remain under Sage's control and are not requested by CATalyst.

### Dexie

CATalyst uses Dexie APIs for token metadata, public order books, offer lookup and status, and—when enabled—offer publication. Requests can contain CAT asset IDs, public coin/offer identifiers, and signed offer strings. Published offers are intended to be public and can be relayed, taken, or indexed by other participants.

### Splash peer-to-peer network

When the operator enables Splash, CATalyst can start the separately distributed `splash.exe` peer-to-peer node, broadcast public signed offers, discover peers, receive offers, and expose a loopback offer hook. Peers can observe the operator's network address and public offer data. CATalyst stores received offer state and source-network information locally for diagnostics and processing. Splash is an upstream open-source component and is not operated or signed by CATalyst.

### TibetSwap

CATalyst queries TibetSwap for pool, reserve, price, and swap-related market information and can monitor public Chia mempool activity associated with configured pools. Requests identify the selected public CAT/pair. CATalyst does not submit a TibetSwap swap unless the operator separately uses a feature that explicitly does so.

### Spacescan and Coinset

CATalyst can query Spacescan and Coinset for public on-chain confirmation, coin, transaction, token, holder, activity, supply, and price information. Requests can include public puzzle hashes, CAT asset IDs, coin IDs, transaction IDs, and offer-related chain identifiers. A Spacescan API key, if supplied, is stored locally and sent only to Spacescan requests.

### GitHub

CATalyst queries GitHub release endpoints for Sage compatibility information, CATalyst update metadata, signed manifests, installer downloads, and optional Splash release metadata/downloads. GitHub receives normal request data such as the operator's network address, requested release/version, and user agent.

### Web fonts and token images

The desktop interface can request fonts from Google Fonts and public token images from Dexie or Spacescan content hosts. Those hosts receive normal web request information, including the operator's network address and the requested asset.

## User-controlled disclosure

CATalyst can create a diagnostic ZIP when the operator requests one. It is kept locally until the operator chooses to share it. Logs and diagnostics may contain wallet fingerprints, public addresses, coin IDs, transaction IDs, asset IDs, offer strings, balances, settings, file paths, software versions, and failure details. Operators should inspect a bundle and share it only with a recipient they trust. Wallet seed phrases and private keys should never be placed in a diagnostic bundle or support message.

Opening external links in the CATalyst interface transfers the operator to the linked service in their browser. Nothing in this policy replaces those services' own notices.

## Changes and contact

Material privacy changes are made through the public repository history. Security or privacy concerns should be reported through [SECURITY.md](../SECURITY.md).
