"""Shared offline TLD extractor.

By default tldextract fetches the Public Suffix List over the network on first
use. On a fresh Space (or an offline dev machine) that fetch fails and throws a
noisy traceback (seen in the app logs). We force the bundled snapshot instead —
`suffix_list_urls=()` — so domain parsing never touches the network. The snapshot
is refreshed with each tldextract release, which is accurate enough for our
registry and typosquatting checks.
"""
from __future__ import annotations

import tldextract

# No network: use the snapshot shipped with the tldextract package.
extract = tldextract.TLDExtract(suffix_list_urls=())
