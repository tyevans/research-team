# Candidate direction: permission policy as a projection over decision history

Researched 2026-08-12. Research only, no code written.

Premise under evaluation: because this repo already records `ToolCallDecided`
(with `decided_by: human | policy` and `decision: approve | edit | reject |
respond`) and `AutonomyChanged` in `research_team/domain/events.py`, permission
policy can be a *read model over decision history* rather than configuration —
with event-sourced promotion, derived `FetchGrant`s
(`research_team/application/grants.py`), a model-free replay pre-check, and
asymmetric treatment of approve/edit/reject.

---

## Verdict: worth building — but only the narrow slice

**Build:** derived `FetchGrant` proposals + the replay pre-check.
**Do not extract:** the core idea is published prior art as of May 2026.
**The trap is the general form:** a promotion UI that suggests rules across all
tools from approval streaks. Three independent literatures say that specific
thing fails, and the failure is silent.

---

## 1. Prior art

### The idea is already published, including the parts believed novel

[**Options, Not Clicks: Lattice Refinement for Consent-Driven MCP
Authorization**](https://arxiv.org/pdf/2605.11360) (arXiv 2605.11360) is the
same design. It learns permission patterns from consent history for MCP tool
calls, generalizes approvals upward over a permission lattice, and — the two
features believed to be the differentiators here — **validates proposed
generalizations against the user's rejection history, blocking any
generalization that would contradict a prior denial**, and **treats rejections
as hard constraints while approvals are only starting points for inference**.

That is the asymmetry ("a single rejection is sticky; approval streaks merely
suggest") and the mechanical pre-check ("refuse to suggest a rule that would
have auto-approved something the human rejected"), both already in the
literature. This is the single most important finding in this report.

Two adjacent 2026 papers frame the same problem:
[Before the Tool Call: Deterministic Pre-Action Authorization](https://arxiv.org/html/2603.20953v1)
and [Intent-Governed Tool Authorization for AI Agents](https://arxiv.org/pdf/2606.22916).

### What commercial agents actually do

[How Agents Ask for Permission](https://arxiv.org/html/2607.13718v2)
(arXiv 2607.13718) audited Claude, Claude Cowork, ChatGPT and Codex in
May–June 2026. Findings relevant here:

- **No commercial agent derives or suggests rules from approve/reject
  history.** The paper states plainly that this is absent from the products
  evaluated, and cites Wu et al. (training a classifier on user decisions) as
  a literature-only approach.
- Claude Cowork grants "cannot be revoked by the user" once given — the exact
  failure the event-sourced-promotion idea fixes.
- Codex scopes enforcement to the current session; cross-session persistence is
  unaddressed.
- Claude's "Needs approval" setting produces *illusory control*: it reads as
  user-in-the-loop but triggers automatic LLM-based approval.

So: **the derivation is a real gap in shipped products, but not a gap in the
research literature.**

### DERIVE vs. merely LOG vs. VALIDATE

| System | Logs | Derives a proposal | Validates against past denials |
| --- | --- | --- | --- |
| [AWS IAM Access Analyzer policy generation](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-policy-generation.html) | CloudTrail | **Yes** — generates a policy from observed API calls | **No** |
| [GCP IAM Recommender / Policy Intelligence](https://docs.cloud.google.com/policy-intelligence/docs/role-recommendations-overview) | Access logs | **Yes** — ML-based role recommendations | No (predicts *future* need instead) |
| `audit2allow` (SELinux) | Audit denials | **Yes** — emits `allow` rules from denials | **No** |
| CIEM tools generally | Cloud logs | Yes (right-sizing) | No |
| [OPA decision logs](https://www.openpolicyagent.org/docs/management-decision-logs) | Yes, richly | **No** — logs are for audit/offline debugging | No |
| [Permit.io](https://www.permit.io/blog/why-ai-agents-choose-permitio-for-authorization) | Yes (uploads OPA logs) | No | No |
| APort / Open Agent Passport | Signed audit records | No | No |
| Android/iOS runtime permissions | Per-grant state | No — user picks scope | No |
| Claude Code / Cowork / Codex | Session or config state | No | No |
| **Lattice Refinement paper** | Consent history | **Yes** | **Yes** |

The pattern is stark: **everything that derives, derives from *usage*; nothing
in production derives from *human judgement*, and only one research paper
validates against denials.** The repo's proposal sits with that paper.

`audit2allow` is the closest structural analogue and it is instructive that it
derives from *denials* (make this work) rather than approvals (this was fine) —
the opposite polarity. IAM Access Analyzer is the closest by intent.

---

## 2. Failure modes, and which apply

### (a) Habituation — the strongest objection

[Wijesekera et al., USENIX Security 2015](https://www.usenix.org/system/files/conference/usenixsecurity15/sec15-paper-wijesekera.pdf)
measured permission requests at **213 per hour per user**. The established
finding: "once a user clicks through the same warning often enough, he or she
will switch from reading the warning before clicking on it to quickly clicking
through it without reading." [How to Ask For Permission](https://www.usenix.org/system/files/conference/hotsec12/hotsec12-final19.pdf)
makes habituation the central design constraint.

**This applies directly and it is close to fatal for the general form.** A row
reading "approved 40x, rejected 0" is *indistinguishable* from a row reading
"the human stopped reading after the fourth prompt." The design proposes to
treat streak length as evidence of consent, but streak length is precisely the
variable that predicts habituation. Promoting a rule from a long approval
streak launders click-through fatigue into durable policy, and the audit trail
will faithfully record that the human approved it 40 times — a confident lie of
the same species the context-strategies doc warns about.

The arXiv 2607.13718 paper independently names this: constant approvals make
users "prone to over-granting permissions, in a phenomenon known as 'privacy
fatigue.'"

*Mitigation that exists:* count distinct sessions and distinct days, not
distinct calls; require a deliberate, non-streak signal (an `edit` that was
then approved is a much better consent signal than the 40th `approve`, because
editing proves the human read the arguments). Weight `edit`-then-approve
heavily and raw `approve` streaks lightly — which inverts the proposal's
implied weighting.

### (b) Contextual integrity — the argument-projection is the hard part

The same Wijesekera paper's finding is that permission decisions depend on
**context** (what the app was doing, whether the user could see it), not on the
(app, resource) pair. A `(tool, host)` key throws that away. Forty approvals of
`fetch(docs.python.org)` during a documentation task say very little about
`fetch(docs.python.org)` issued on a turn whose prior message contained
attacker-controlled text. The repo's own summarizer prompt already worries
about exactly this class of confusion.

The projection problem also does not generalize. `host` is a genuinely good
projection for `fetch` — bounded, human-nameable, already the `FetchGrant`
unit. There is no comparable projection for `bash`, and for `write_file` the
natural one (path prefix) is the one `audit2allow` critiques warn about most.
The lattice paper exists *because* choosing the generalization is the hard
part; "argument-projection e.g. host for fetch" is a solved case being
mistaken for a general method.

### (c) Incomplete observation window

[IAM Access Analyzer](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-policy-generation.html)
caps at 90 days, and its documented weakness is that "the generated policy
won't include actions that were never used during the analysis period."

The mirror of this is the more dangerous version here: **the log only contains
calls the agent chose to make.** The replay pre-check validates a candidate
rule against *observed rejections*. It cannot validate against calls that were
never attempted, and *absence of a rejection is not approval*. A rule promoted
because it never conflicted with anything is a rule tested only against the
agent's past behaviour — and the agent's behaviour changes once the rule
exists, because the prompt-cost of the action drops to zero. This is a genuine
feedback loop, not a hypothetical one.

The pre-check is therefore **necessary and sound but much weaker than it
sounds**. It proves "this rule contradicts nothing you refused." It does not
prove "this rule is safe." Presenting it in the UI as validation would create
the illusory control that arXiv 2607.13718 criticises in Claude's "Needs
approval."

### (d) audit2allow's specific warning

Red Hat's guidance is that you "should not use audit2allow to generate a local
policy module as your first option," because feeding it denials "can result in
suggested SELinux policy statements that grant dangerous permissions — for
example, one case would grant a service the ability to write kernel memory."
([RHEL docs](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/7/html/selinux_users_and_administrators_guide/sect-security-enhanced_linux-troubleshooting-fixing_problems))

The mechanism is the one that applies here: the tool generalizes at the level
the log happens to record, which may be far broader than the operation the
human had in mind. Twenty years of practitioner experience says the generated
rule must be read line by line by someone who understands the domain — which
is most of the work the feature was meant to remove.

### (e) Self-confirmation

Once a row is promoted, the human leaves the loop, so the row stops
accumulating human decisions and starts accumulating policy ones. If the
projection counts both, the rule proves itself forever.

**This one the repo is already equipped for**: `ToolCallDecided.decided_by`
separates `human` from `policy`, and its docstring says exactly why ("an audit
trail that cannot tell them apart is a worse one"). The projection must filter
to `decided_by == "human"`. Worth stating as a test rather than a convention.

### (f) Sticky rejections cut both ways

"A single rejection is never erased by a later streak" is the right default and
matches the lattice paper. But an early rejection made for an incidental reason
— a typo'd host, a bad moment, a reject-then-retry — permanently poisons the
row. The only escape is a manual override, which is the configuration the
feature set out to eliminate. Event sourcing softens this (fold to before it,
or record a `RejectionRetracted`), but the UI must expose it or the system
becomes quietly unusable in exactly the sessions where it is used most.

### (g) GCP's inverse warning

IAM Recommender uses ML specifically to *avoid* over-removal, because "there
can be gaps in access logs data from sporadic individual behaviors such as
users taking vacations or changing projects." Google concluded that raw
observed usage is too sparse to act on and needed a model on top. That is a
direct counterexample to the model-free premise — though it argues for
*narrower* derivation here, not for adding a model.

---

## 3. What is genuinely good

Not everything survives the critique. Three things do:

1. **Event-sourced promotion with revert-by-fold is real and rare.** Every
   system surveyed loses provenance at the moment of promotion: IAM Access
   Analyzer emits a policy document and the CloudTrail lineage is gone;
   Claude Cowork's grants cannot be revoked at all. "Why is this auto?"
   answered by an event, revertible by folding to before it, is a genuine
   improvement over the state of the art in shipped products.
2. **`decided_by` already exists**, so the self-confirmation loop is closable
   by construction rather than by discipline.
3. **`FetchGrant` is the right first target and possibly the only one.** Hosts
   are a bounded, human-nameable projection; grants are already per-run and
   budget-limited (`grants.py`), so a badly derived grant is capped by the
   request budget rather than open-ended. The blast radius of getting it wrong
   is a bounded number of GETs to hosts the human has personally approved
   before. That is about as safe as a derived-authorization feature gets.

---

## 4. Recommendation

**Build the narrow slice:**
- A read model over `ToolCallDecided` filtered to `decided_by == "human"`.
- Derived `FetchGrant` *proposals* only — hosts the human has approved in past
  sessions, offered as a pre-filled list at run start. Not auto-applied.
- The replay pre-check, implemented and tested, but described in the UI
  honestly: "contradicts nothing you have refused," never "safe" or
  "validated."
- Weight `edit`-then-approve above raw `approve`; count distinct sessions and
  days rather than call count.

**Do not build** the general promotion UI across all tools. `bash` and
`write_file` have no defensible argument projection, and that is where
`audit2allow`'s twenty years of warnings land.

**Do not extract.** The idea is published (arXiv 2605.11360, May 2026)
including the denial-validation and the approve/reject asymmetry. What is
unpublished is the *event-sourced* rendering of it — and as with the context
strategies, that is architecture rather than a dependency: the value is the log
this repo already has, which a library cannot bring with it.

**Reasons the lead should suspect their own enthusiasm:** the two features that
feel most clever (the mechanical replay pre-check, the rejection asymmetry) are
both in a paper from three months ago; the signal the design leans on hardest
(approval streak length) is the one the HCI literature identifies as the
symptom of users not reading; and the projection step that makes the whole
thing work is easy for exactly one tool and unsolved for the rest.

---

## Sources

- [Options, Not Clicks: Lattice Refinement for Consent-Driven MCP Authorization (arXiv 2605.11360)](https://arxiv.org/pdf/2605.11360)
- [How Agents Ask for Permission: User Permissions for AI Agents (arXiv 2607.13718)](https://arxiv.org/html/2607.13718v2)
- [Before the Tool Call: Deterministic Pre-Action Authorization (arXiv 2603.20953)](https://arxiv.org/html/2603.20953v1)
- [Intent-Governed Tool Authorization for AI Agents (arXiv 2606.22916)](https://arxiv.org/pdf/2606.22916)
- [AWS IAM Access Analyzer policy generation](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-policy-generation.html)
- [IAM Access Analyzer for CloudFormation service roles](https://aws.amazon.com/blogs/security/use-iam-access-analyzer-policy-generation-to-grant-fine-grained-permissions-for-your-aws-cloudformation-service-roles/)
- [GCP role recommendations overview](https://docs.cloud.google.com/policy-intelligence/docs/role-recommendations-overview)
- [The security analytics that deliver IAM recommendations](https://cloud.google.com/blog/products/identity-security/the-security-analytics-that-deliver-iam-recommendations)
- [RHEL SELinux troubleshooting — audit2allow cautions](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/7/html/selinux_users_and_administrators_guide/sect-security-enhanced_linux-troubleshooting-fixing_problems)
- [OPA decision logs](https://www.openpolicyagent.org/docs/management-decision-logs)
- [Why AI Agents Choose Permit.io for Authorization](https://www.permit.io/blog/why-ai-agents-choose-permitio-for-authorization)
- [Wijesekera et al., Android Permissions Remystified (USENIX Security 2015)](https://www.usenix.org/system/files/conference/usenixsecurity15/sec15-paper-wijesekera.pdf)
- [How to Ask For Permission (HotSec 2012)](https://www.usenix.org/system/files/conference/hotsec12/hotsec12-final19.pdf)
- [Policy-as-Code for Agents: OPA, Rego](https://tianpan.co/blog/2026-04-25-policy-as-code-agent-permissions-opa-rego)
