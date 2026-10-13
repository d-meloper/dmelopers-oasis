# Git and backup experience

## Working bytes and object identity

K11/K12 in the [migration reference](../../../../.oasis/manual/migration-lessons.md)
show that committed object backup does not include dirty, staged, untracked or
ignored bytes, and equal trees do not establish equal history. Preserve working
bytes separately when a requested transition needs them; compare commit/tree
types and refs for the result being claimed.

K15/K16/K36 cover inherited repository environment, MSYS/native paths and text
translation at subprocess boundaries. Use explicit native paths and byte-encoded
protocol input when the command's byte identity matters. K31's autocrlf fixture
protects content-addressed baseline blobs while leaving ordinary text policy
unchanged.

## Backup and uncertain recovery

K19 observed a completed commit with failed synchronous backup. Check the exact
triggering commit and backup outcome independently. K20/K21 distinguish immutable
destination identity, catalog history and restored snapshot scope; restored
copies begin inactive and later ref changes need their own backup.

K32-K37 cover retained object closure, a restore target changed during intake,
effective global configuration, durable unresolved intent and Windows command
length with many refs. These are implementation review/local-fixture mechanisms,
not claims of every live restore succeeding. Reconcile uncertain pushes against
the configured repository before retrying, and retain recoverable committed work.
Use [the manual](../../../../.oasis/manual/git-backup.md) for current commands.
