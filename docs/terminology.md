# Terminology

**CPU family** describes a processor grouping; it does not name a board.
**SoC implementation** is upstream source for a particular silicon platform;
it does not initialize every board using that silicon. **Mainboard target** is
an exact upstream board configuration. **Recipe** is this project's pinned
configuration and verified input policy for that target. **Build-verified**
means a recipe produced an artifact in a recorded environment and passed the
stated static checks. **Reproducible** means two independent clean builds had
matching bytes, when that comparison was actually run. **Hardware-tested**
requires a separately identified exact artifact and board revision.

**Opaque input** is content the inspector cannot classify or independently
validate. **Signed** describes the presence of signature metadata;
**cryptographically verified** requires a completed trust-chain procedure.
**Update package** may contain only part of installed firmware and is not
assumed to be a full SPI restoration image.
