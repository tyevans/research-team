# What discovery finds, per project

The layer-3 gate. `docs/superpowers/specs/2026-08-15-inferred-ontology-design.md`
defers schema refinement until this count exists, because layer 3 needs
per-project schema selection — which does not exist today and is the largest
single cost in that design. It is only worth paying if more than one project
actually produces classes.

**Status on 2026-08-15: the count could not be taken, and this file records why
rather than standing in for it with a number.**

## Why it could not be taken

Three reasons, in descending order of how hard they are to remove.

**1. No model was reachable that could serve the prompts.** The configured
endpoint — `localhost:8080`, `qwen3.6-27b-mtp` per `config.DEFAULT_MODEL` — was
not listening. Ollama was, holding `qwen3.5:9b`, so the pass was run against
that instead. Measured on that machine:

| prompt | result |
|---|---|
| trivial (13 tokens) | answers instantly |
| 19,644 characters (~5k tokens) | no response within **500 s** |
| `ynab-irregular-income`, 25,114 characters | **timed out at 600 s** |

The corpus's largest document is 173,258 characters. The run was abandoned after
the first document. This is a property of the machine and the stand-in model,
not of the pass — but it is the binding constraint today.

**2. The corpus is missing the project the gate is about.** The measurement was
taken against a `local_copy` of the recovery snapshot, which is the only
pre-reset database available. It holds **2 of the 3 projects**:

| project | documents |
|---|---|
| `cf4d9a61…` Ancient Rome | 12 |
| `bbb418fd…` budgeting | 3 |
| `3881dec0…` **Project SEKAI** | **absent** |

SEKAI is the project the spec predicts *will* yield classes — it is where the
enumerating sentence and the rank table were measured. **A count over the other
two is not a test of the prediction; it is a test of the two corpora already
predicted to yield little.** Confirming "Ancient Rome states no classes" against
a database with SEKAI missing would restate the prediction, not check it.

**3. The live database was reset twice and is being re-gathered.** The real
number arrives after that gather.

## What *was* established

**The size ceiling no longer biases the result.** `MAX_DISCOVERY_CHARS` was
40,000 when the gate was specified. Measured against this same database:

| ceiling | documents refused | share of corpus by text |
|---|---|---|
| 40,000 (old) | 6 of 15 | **70%** |
| 200,000 (now) | 0 of 15 | 0% |

The six refused included `wiki-roman-religion` (173,258) and
`wiki-roman-economy` (82,764), which between them hold **100 of Ancient Rome's
116 `category` entities** — so the old ceiling refused precisely the documents
most likely to contain classes. A count taken under it would have reported that
Ancient Rome states none, which is the spec's own prediction arrived at for
entirely the wrong reason. That confound is now removed; see the constant's
comment for what replaced it and what the new number costs.

## What this does not settle

**It does not settle the layer-3 gate**, and nothing here should be read as
evidence for or against building per-project schema selection. The gate needs a
count over all three projects, taken against a corpus that includes SEKAI, on a
deployment that can serve the prompts.

The prediction on record, so it can still be scored when the count is taken:
SEKAI yields a handful of classes; Ancient Rome and budgeting yield near zero.
The evidence for it is in the spec's opening section — **zero enumerating
sentences across all five Ancient Rome documents**, against one in the SEKAI
document that is the whole basis of the feature. That measurement stands
independently of this one and was taken from the graph, not from the pass.

## What it would take to finish this

1. A reachable model that serves a ~50k-token prompt in reasonable time — the
   configured 27b endpoint, or any deployment where the table above does not
   look like it does.
2. A corpus holding all three projects. The re-gather covers this.
3. Then: run the per-document route over every document in each project, and
   record per project — classes found, members resolved vs unresolved, classes
   whose `declared_count` disagreed with `member_count`, and classes dropped by
   verification.

**Report resolved and unresolved members separately and do not add them
together.** They indict different things: few classes found indicts this pass or
a corpus that states none, while classes found with members largely unresolved
indicts extraction or chunking. Extraction chunks at 2,000 characters with a
sliding window, and a markdown table split across chunks leaves rows with no
header — so if that suppressed entity extraction from table rows, this pass
still finds the class (it reads the whole document) but its members resolve to
nothing. A merged count would read as "discovery found little" when the truth is
"discovery found it and the graph had nothing to attach it to", and that is how
a defect elsewhere vetoes layer 3 without anyone noticing.

Finally: judge the output by opening each class's evidence in the source, not by
counting rows. Twenty plausible classes the text does not state is a worse result
than two it does, and only the first is visible in a count.
