# Language metadata included with Kharakteres

- `iso639-3.json`: unmodified ISO 639-3 data distributed by pycountry from Debian iso-codes. LGPL-2.1; see `LICENSE-language-data.txt` and `COPYRIGHT-language-data.txt`.
- `language-provider-snapshot.json`: public WiktAPI language-list response; metadata only, not word definitions or the full lexical database. Its underlying lexical source is Wiktionary/Kaikki/Wiktextract.
- `language-data-sources.json`: retrieval timestamp, exact source URLs and SHA256 fingerprints.

No new Python package is required to read these files. Runtime refresh updates the provider availability cache outside this directory. ISO and provider metadata are not LLM capability tests. Filtering, aliases, type/voice-scope exclusions and user-facing limitations are documented in `doc/LANGUAGES.md`.

- `korean-language-names.json`: fixed selection of 229 code/name pairs with Korean display names already present in the original curated defaults or bundled provider snapshot. Only this subset is selectable, sorted by Korean name. Provider refresh changes availability, never membership or display names. Full source metadata remains bundled for normalization and reproducibility. The source manifest records the derived file hash.

Current UI groups are modern (209), classical (17: ISO ancient/historical), and extinct (3). Canonical ISO types remain unchanged for normalization/API compatibility. Catalog membership stays 229 across provider refresh; dictionary registration is not translation/IPA/STT/TTS certification. Local and Docker use the same bundled files and default `wiktapi` provider.
