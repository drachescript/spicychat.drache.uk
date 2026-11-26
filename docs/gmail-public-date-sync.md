# Gmail publication-date worker

Runs every six hours, with the existing shared data-writer concurrency group.
Uses Gmail readonly OAuth and the original scanner's matching rules. Confirmed
dates and the public JSON schema are unchanged.

## Sync and quota behavior

- First run: list historical matching IDs, then retrieve at most 40 raw messages
  per run. Requests (including retries) are spaced at least 3.25 seconds apart.
- Subsequent runs: fixed timestamp window with a 48-hour overlap, plus a monthly
  full-ID reconciliation. Only previously unseen IDs need a raw read.
- At most 10 list attempts and 40 raw attempts per execution. Long rate limits,
  auth failures and network failures stop the run; pending IDs survive.
- Each completed list page and successful message is saved locally. GitHub
  Actions commits the encrypted state even after a recoverable scan failure.
  A hard runner termination before the commit can repeat the current bounded
  batch, but cannot skip it.
- Approval dates are evaluated only when discovery and the pending queue are
  complete. Unparseable/deleted messages retry three times, then appear as
  unresolved in the summary; manual retry is available. Cached parsed approvals
  are evaluated again if a bot's public observation arrives later.

## Storage and retention

Only the encrypted state is committed to .github/gmail-public-date-state.enc.
It contains the cursor, pending IDs and minimal extracted name/date pairs, never
raw MIME, attachments or OAuth tokens. The existing Gmail refresh token is used
to derive an encryption key by default. An optional high-entropy repository
secret GMAIL_SYNC_STATE_KEY can instead be configured **before the initial
run**. Changing the effective key requires migrating/restoring the state or
using the explicit reset-state maintenance option; decryption failures stop
rather than silently losing the cache.

Git history retains ciphertext, so this is not equivalent to automatic
deletion. Keep the key restricted and review the retention of Gmail-derived
data and older scan exports against applicable Google terms. If deletion is
required, remove the state/history as appropriate and rotate the dedicated
key. Existing publicly confirmed publication dates are separate. Do not put
raw Gmail data or the key into the repository or Actions logs.

## Maintenance

The workflow supports full reconciliation (does not reread cached messages),
retry unresolved messages, and explicit state reset (rebuilds from Gmail in
bounded batches, never overwrites confirmed dates). Do not run reset routinely.
The regular schedule needs no additional infrastructure or new mandatory secret.
For local dry runs use --scan-only; it writes neither the state nor public data.

The Actions summary reports raw/list attempts, retries, pending/unresolved
messages and updates applied. Verify the Google dashboard after catch-up;
the code cannot guarantee a particular dashboard utilization or zero throttles
from other clients. The separate Discord Apps Script is not changed.
