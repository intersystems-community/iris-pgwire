# Phase 0 Spikes — Local-First Sync

Three questions gate the change-feed design in [`../research.md`](../research.md). Each spike
answers one, and each has a **kill criterion** that changes the plan if it fails.

| Spike | Question | Kills what, if it fails |
|---|---|---|
| Q1 | Can a journal reader **seek to a saved position** and roll across files? | Journal CDC (§4.2) as a feed — permanently. §4.1 outbox becomes the only answer. |
| Q2 | Does `%Dictionary.CompiledStorage` resolve globals for **DDL-created (hashed)** tables? | Journal CDC's row mapping. Also proves whether name inference is unsafe. |
| Q3 | What does an outbox trigger cost on the write path? | The outbox as default, if it breaches the 5 ms constitutional budget. |

Run Q2 first — it is fastest and its answer feeds Q1.

## Requirements

A running IRIS instance. Community Edition is sufficient for all three.

```bash
docker run -d --name iris-pgwire-db \
  -p 2972:1972 -p 52776:52773 \
  -e IRIS_PASSWORD=SYS -e IRISUSERNAME=_SYSTEM -e IRISPASSWORD=SYS \
  intersystemsdc/iris-community:2026.1
```

Or use the repo's compose stack (`docker compose up -d iris`), which starts the same image as
`iris-pgwire-db`.

Q1 requires the **`%SYS` namespace** and journalling enabled (it is on by default).

## Running

```bash
python3 specs/043-local-first-sync/spikes/run_spikes.py          # all three
python3 specs/043-local-first-sync/spikes/run_spikes.py q2       # one
python3 specs/043-local-first-sync/spikes/run_spikes.py q1 q3    # several
```

Configuration, all optional:

| Env var | Default | Meaning |
|---|---|---|
| `IRIS_CONTAINER` | `iris-pgwire-db` | Container to `docker exec` into |
| `IRIS_SESSION` | *(unset)* | Set to run `iris session` directly instead of via docker |
| `SPIKE_KEEP` | *(unset)* | Set to skip teardown of spike tables/globals |
| `SPIKE_ROWS` | `1000` | Insert count for Q3 |

Transport is `iris session IRIS -U <namespace>` with ObjectScript on stdin — the same mechanism the
compose healthcheck uses. No Python driver is needed inside IRIS, and no extra packages are needed
outside it.

## Reading the output

Each spike prints numbered probes and ends with a verdict line:

```
Q2 VERDICT: PASS — storage resolution returned ^EW3K.B3vA.1 and data was found there
Q2 VERDICT: FAIL — <reason>
Q2 VERDICT: INCONCLUSIVE — <reason>
```

`INCONCLUSIVE` means the probe itself did not run correctly (wrong namespace, missing privilege,
API absent on this IRIS version) — it is not an answer to the question. Fix the environment and
re-run rather than recording it as a result.

**Record results back into `../research.md`** — §7 open questions Q1–Q3, and the risk register.
State the IRIS version tested (`write $ZV`), which the driver prints in its header.

## Status

**The ObjectScript in these spikes has not yet been executed against a live instance.** It was
written from verified API notes in `intersystems-community/iris-agentic-dev` (see the provenance
note in `../research.md` §10) but the egress policy in the authoring session blocked both
`containers.intersystems.com` and Docker Hub's blob CDN, so no container could be started to
validate it. Expect to fix syntax on first run. The probes are deliberately defensive — each is
wrapped in `try/catch` and reports its own failure — so a broken probe should degrade to
`INCONCLUSIVE` rather than taking down the run.

Q1 in particular is written as an **API probe**: it tries several candidate seek mechanisms because
no working seek-by-address pattern is documented anywhere we could find. Some of them are expected
to fail. The spike's job is to report which one works, if any.
