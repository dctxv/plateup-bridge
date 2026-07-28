# PlateUp Bridge working agreement

## Verification ledger

Whenever a feature, live-game behavior, replay, or acceptance test succeeds,
append the result to `docs/verified-successes.md` in the same change.

Each entry must identify:

- date/time;
- game and bridge versions;
- protocol and schema versions when relevant;
- exact command or procedure;
- numeric acceptance gate and observed result;
- durable evidence artifact, when one exists;
- limitations and whether the result is quick, formal, or provisional.

Retain failed and inconclusive outcomes in the ledger's separate section. Never
silently replace an earlier failure, promote a quick sample to a formal gate, or
claim a result that lacks live or saved evidence.
