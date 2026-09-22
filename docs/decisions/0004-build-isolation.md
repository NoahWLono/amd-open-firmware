# ADR 0004: Build isolation and repeatability

Date: 2026-09-22
Status: accepted for the initial implementation
Owner: Noah Weinberger

## Decision

Fetching and building are separate operations. Fetch verifies exact commits,
selected input hashes, and license documents. A build copies verified sources
into a new run directory and uses rootless bubblewrap with an unshared network
namespace. The selected run directory is writable inside the build. `/usr`
and `/etc` are read only, `/tmp` is temporary, and `/dev` is synthetic. No
physical firmware device or host home directory is passed through.

Builds limit job count, elapsed time, log size, ROM size, and minimum free
workspace space. Successful runs retain their configuration, log, CBFS listing,
artifact, and manifest. Failed runs retain partial output and logs for
diagnosis. Cleanup accepts only a directly named, project-marked target build
directory. It does not remove source checkouts or private surveys.

## Consequences and limits

The host supplies the compiler and build utilities. Their observed versions
are recorded in each manifest, and the project checks an explicit environment
lock when one is available. This is weaker than a hermetic compiler toolchain;
matching source pins on a different host does not imply identical bytes. The
`reproduce` command compares two independent run trees on the same host and
records any byte difference. A matching result supports only that stated
scope.

The project does not run builds as root, grant privileged device access, or
silently fetch from an offline build. Bubblewrap availability and user
namespace policy are host prerequisites. Record a missing prerequisite as a
build environment blocker. Upstream board support remains unassessed by that
failure.
