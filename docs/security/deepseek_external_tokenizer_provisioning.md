# External Layer-A Tokenizer Provisioning

Story OS does not ship, copy, redistribute, discover, or download the audited
V3 asset. The unresolved license means the production Profile remains
unavailable.

The B1 seam accepts only server-side inputs:

1. explicit trusted provisioning enablement;
2. one absolute local `.json` file path;
3. one complete expected SHA-256;
4. an injected, offline loader returning the narrow
   `ConservativeTextCounter` interface.

B1-FIX opens the file once and passes the exact validated immutable bytes plus
the parsed non-empty JSON object to the loader. The loader does not receive a
path and cannot reopen a different file after hash verification. Files must be
regular, non-empty, no larger than 64 MiB, valid UTF-8 JSON, and have an object
at the top level.

It rejects missing files, relative paths, symlinks, non-files, unexpected
suffixes, malformed hashes, hash mismatches, loader failures, exact counters,
wrong scope, and missing counter revisions. It never searches home/cache,
executes archive scripts, uses `trust_remote_code`, or makes network calls.

Public output exposes no path, filename, configuration name, raw exception,
credential, or endpoint. Default safe status is
`CONSERVATIVE_COUNTER_ASSET_UNAVAILABLE`.

Provisioning a real asset or resolving its license requires a separate Owner
decision. B1 does not authorize that action.
