# ADR 0002: Initial AMD board targets

Date: 2026-09-22
Status: accepted for the initial implementation
Owner: Noah Weinberger

## Decision

The first two build recipes target the exact upstream `pcengines/apu2` and
`starlabs/cezanne` mainboards at pinned coreboot 26.06 commit
`5cbf8afc4c08949c9b4ee1cb9dc5439add8a937e`. APU2 represents the older
AMD GX-412TC Puma path. The StarBook Mk VI AMD uses a Cezanne laptop
path. Each has a reviewed upstream board symbol, source files, and named
binary inputs. The recipes produce development artifacts only.

These targets provide distinct silicon and board integration paths. They do
not establish support for other machines with the same CPU family. In
particular, the HP 255 G10 is a survey-only case. The upstream
StarBook Cezanne port cannot be relabeled as an HP port.

## Consequences

The catalog contains many more upstream and historical AMD records than the
two implemented recipes. Each record carries its own evidence and readiness
state. Historical boards retain their older source revision and maintenance
context. A new recipe needs its own exact mainboard, revision constraints,
source pin, dependency hashes, build result, and publication review.

The source locations and limits behind the initial choices are in
`docs/research/evidence.md` and packaged `evidence.json`. Build reports must
record the actual artifact and tests. A catalog record alone cannot change a
target to `build-verified`.
