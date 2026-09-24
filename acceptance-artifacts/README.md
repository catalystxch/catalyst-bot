# CATalyst secondary-PC acceptance artifact

This branch is a binary-delivery branch for independent acceptance testing. It
is not a release and must not be merged into `main`.

- Application source commit: `5b54d9465555aaa5bbd7dd43ff51f299cab89ca6`
- ZIP: `CATalyst-5b54d94-secondary-pc.zip`
- ZIP SHA-256: `28267F5906705EFFEA88DD720F8BA0AB7DA30FCD428858E100110649B59B50F2`
- Extracted `Catalyst.exe` SHA-256: `696BEAD6A79CED2B846E67781F59F73A6EA05FF694BDE649AF43A3B1FFD62A25`

The package contains `ACCEPTANCE_BUILD.txt` with source identity and smoke-test
provenance. Verify both hashes before launch. Use the source commit above for
code inspection and the package only for the Windows acceptance run.
