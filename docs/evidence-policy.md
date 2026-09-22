# Evidence policy

Every catalog assertion cites a primary source in `evidence.json`, with an
exact source location, revision or document version where known, retrieval
date, supported claim, and limit. A source file in a pinned coreboot tree can
establish that a target exists at that revision. It cannot establish a
successful local build or physical boot. Vendor documentation can establish a
stated dependency; it does not grant redistribution rights unless its terms
say so.

The evidence ledger is appendable. On source updates, add a new record for
changed claims rather than silently rewriting an old revision into a new one.
Keep failed builds and unavailable dependencies as results. Treat prior
assistant summaries as leads to verify, not as observations. Survey files may
be incomplete or internally inconsistent. The importer preserves collection
gaps and never infers success from a filename alone.
