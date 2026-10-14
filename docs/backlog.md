# Backlog

Non-spec ideas and `SPEC-QUESTION:` entries for spec gaps (AGENTS.md). The
questions below are kept verbatim as the record of what the implementing
agents had to decide; settled questions point at their answer in
`docs/decisions.md`. Spec §20 items deferred to v0.2 are listed first.

## v0.2 open items (spec §20)

Mirrored from the closing note of `docs/design.md` §20:

- Web UI commit workflows (Git commit, branch and push from the browser).
  The optional local read/edit UI is specified in `docs/design.md` §21.
- History/diff between refs and baselines.
- Merge driver for sidecars.
- Exports (other than the Mermaid graph).
- Query language over the graph.
- Sentence linting.
- User-defined edge types.
- Per-type typed `extra` fields.
- CR overlay in graph export.
- CR verification state.
- `undeprecate` scope intent.

Comparing baselines is likewise out of scope for v0.1 (§12.4: the manifest
format is fixed now so v0.2 can diff them).

## Spec questions (S1–S19)

SPEC-QUESTION: Where does `OperationRefused(finding)` live? Spec §16.2 and
appendix C require refusals to raise it, but the complete layout of §16.1 has
no errors module and S1's model list omits it. Most conservative reading: it is
a small exception carrying a `Finding` and belongs next to `Finding` in
`core/models.py` (or `core/operations.py` since that is what raises it).
Decide when the first refusal lands (S12/S13) and record the choice in
docs/decisions.md.

SPEC-QUESTION: Does a glossary term sidecar contain a `template` field? The
§10.2 example JSON omits it ("no `template` pinning beyond the shipped `term`
template (pinned anyway for uniformity)" — ambiguous), while appendix B.3's
`Term` model includes `template: TemplateRef` and the same sentence says the
template is "pinned anyway for uniformity". Most conservative reading: B.3 is
the schema of record and `template` is mandatory (S1's `Term` model and S3
stand-in tests include it). Reconcile the §10.2 example with B.3.



SPEC-QUESTION: Are the example UUID/ID pairs in §5.4 and §9.2 illustrative
only? The §5.4 pair (`6f3c2f1e-8b3e-4a4c-9a3d-2d0f5b7a9c11` → `RE-7F3K2Q`)
cannot be produced by the §4.1 derivation rule under any "first 30 bits"
reading of the UUID (most-significant 30 bits give `RE-DWY2Y7`; no 30-bit
window of the UUID decodes to `7F3K2Q`). S1 implemented the normative §4.1
text: Crockford base32 of the most significant 30 bits of `uuid.int`,
6 characters, MSB-first. The spec examples should be regenerated from the
rule or the rule clarified.

SPEC-QUESTION: Does the Term sidecar really pin a `template` field? Appendix
B.3 gives `Term.template: TemplateRef` ("pinned anyway for uniformity" per
§10.2 prose) but the §10.2 example sidecar has no `template` key, so that
example is not valid against B.3. S1 implemented B.3 literally: `template` is
required on `Term`. Either the example should show the field or B.3 should
gain a default.

SPEC-QUESTION: When a document's `id` has the wrong prefix but the correct
body, do `E-ID-DERIVATION` (id not derivable from uuid *with the configured
prefix*, §4.3) and `W-PREFIX-MISMATCH` (prefix ≠ configured prefix, §14) both
fire? The wording allows a fatal `E-ID-DERIVATION` for every document after a
manual prefix change (§4.3: "unsupported operation … reports every document
whose prefix mismatches" sounds like a warning). S1 provides `is_derivable_from`
(full comparison with the configured prefix, per §4.3 wording) plus `split_id`
so validate can report body-mismatch and prefix-mismatch separately if that is
the intent.

SPEC-QUESTION: What is the exact placeholder text for template sections that
appendix B.2 does not quote? B.2 gives literal placeholders only for `epic`
Hypothesis, `user-story` Story and Acceptance criteria, and describes
`requirement-ears` Statement only as "placeholder lists the five EARS
patterns"; all other sections' placeholder wording is unspecified, yet §5.5
and B.2 require placeholder text on the line under each heading in *italics*.
Most conservative reading (S4): brief instructive one-line sentences as
placeholders, frozen as golden data in `tests/test_builtin_templates.py`; the
Statement placeholder lists the five standard EARS patterns (ubiquitous,
event-driven, state-driven, unwanted behaviour, optional) in one italic line.
Confirm the intended wording or bless the authored text.

SPEC-QUESTION: How does `section_is_empty` (§5.5) match a skeleton's italic
placeholder? B.2 stores placeholders in template.md as `*text*` while the §5.5
descriptor example stores bare `text`, so an untouched section's content
(`*text*`) never equals the descriptor placeholder and would not count as
empty. Most conservative reading (S4): descriptors hold the bare text per the
§5.5 example (and S1's model tests), template.md wraps it in `*…*` per B.2;
S5's engine should compare against the italic form or strip emphasis when
checking emptiness.

SPEC-QUESTION: Does shipped `user-story` v1 use section heading "Rationale"
(B.2) or "Motivation" (implied by the §5.5 example, where v2 renames
"Motivation" → "Rationale" via `renamed_from`)? B.2 is authoritative and lists
v1 with "Rationale", which makes the §5.5 rename example unreachable from
shipped v1. Most conservative reading (S4): B.2 literally — v1 has "Rationale"
and `renamed_from: []` everywhere. Either the §5.5 example should be renumbered
or B.2's `user-story` row should say "Motivation".

SPEC-QUESTION: What finding code does the §8 missing-baseline warning use? §8
says status "degrades to `unknown` with a warning" when the baseline branch is
missing locally, but §14's catalogue has no code for it (nor for degraded
mode, which §12.1 covers with its `note:` channel instead). Most conservative
reading (S8): severity-W `W-BASELINE-MISSING` (subject:
`.gregraph/config.toml`) and no finding in degraded mode — the plan's
acceptance distinguishes "degraded mode → unknown" from "missing baseline
branch → unknown + warning". Confirm the official code or provide one.

SPEC-QUESTION: Is the WIP state (§8) itself knowable without Git? Only "any
document has unbumped modifications" is hash-based (§7.1 refinement 1); the
draft and uncommitted conditions need Git and the baseline branch. Most
conservative reading (S8): WIP is computed from the knowable facts only and
stays binary, so in degraded mode a brand-new untracked draft does not set WIP
(only hash mismatches do) and `WIP: no` can be printed while an invisible
draft exists. Should WIP degrade to `unknown` too?

SPEC-QUESTION: Which items do the WIP conditions of §8 cover? The status model
applies to "documents and glossary terms", but the WIP paragraph says "any
document is draft, any document has unbumped modifications" — whether glossary
terms and change requests count is unclear (both have `body_hash`/`version`
and reconcile treats them alike, §7.5). Most conservative reading (S8): the
status subjects (documents + terms) feed the draft and modified counts; CRs
affect WIP only via "any file under the managed directories is uncommitted".
Confirm, or widen the modified count to CRs.

SPEC-QUESTION: S10 resolution of the `E-ID-DERIVATION`/`W-PREFIX-MISMATCH`
overlap above. §14/§4.3 read literally make `E-ID-DERIVATION` (id not
derivable from uuid *with the configured prefix*) fire for **every** prefix
mismatch, so `W-PREFIX-MISMATCH` is a strict subset that always co-occurs
with the error after a prefix change. S10 implemented that literal
double-report (error + warning), not the disjoint split via `split_id`
(where pure prefix drift would warn only). Confirm the intent, or redefine
`E-ID-DERIVATION` as body-vs-uuid consistency under the document's own
prefix.

SPEC-QUESTION: Does `validate` report `W-NO-GIT-IDENTITY` in degraded mode?
The code says "Git identity unset" (§14) and §12.2's warning wording
("user.name/user.email not configured") presupposes a Git repository, but
`identity()` is `None` in degraded mode too, and §5.4 says `new` warns
whenever `created_by` cannot be filled. Most conservative reading (S10,
mirroring the S8 `W-BASELINE-MISSING` precedent): warn only when
`git.is_repo()` is true and the identity is unset; degraded mode is covered
by the §12.1 `note:` channel and stays silent. Confirm, or widen the
warning to degraded mode.

SPEC-QUESTION: What should `validate` report for a corrupt template tree
(version directory gap or unparsable `template.json` in
`.gregraph/templates/`, §5.5)? The §14 catalogue has no code for it.
Most conservative reading (S10): no finding is invented — template loading
raises (like a corrupt `config.toml`) and the CLI maps it to the
environment-error exit code (3) or internal error (5). Confirm, or add a
catalogue code (e.g. `E-TEMPLATE-INVALID`).

SPEC-QUESTION: Do `E-TARGET-SUPERSEDED`/`E-TARGET-DEPRECATED` and
`W-LINK-STALE` double-report the same edge? §7.4 defines stale as "target is
deprecated or superseded (regardless of version)" (`W-LINK-STALE`) while §14
says the link-time refusals are "also reported by validate if found in files"
(`E-TARGET-*`) — and §7.6/§11.2 describe inbound links that "become stale and
are listed" / "the reviewer decides" as a *later* step after `supersede`/
`deprecate`, which an error (hook-blocking per §7.5) would forbid. The two
states are indistinguishable in files: validate cannot tell a link that
legitimately predates the target's death from a hand-added one. Most
conservative reading (S11): implement both rules mechanically, so a directed
non-`supersedes` link to a dead target reports `W-LINK-STALE` *and*
`E-TARGET-*`; `supersede`/`deprecate` then implies "refresh/unlink inbound
links before the next commit passes the hook". Confirm, or suppress
`E-TARGET-*` whenever `W-LINK-STALE` fires (making `E-TARGET-*` unreachable
from validate), or scope hook errors to the staged set.

SPEC-QUESTION: Are symmetric edges subject to the `E-TARGET-*` rule? §7.6/§8
say a dead document "can no longer be linked as a target of any new
*directed* edge except `supersedes`", but `Graph.check_link` (S6, per the
§13.3 picker wording) refuses *all* non-`supersedes` types at link time, and
§11.2 blesses `conflicts-with` edges remaining on superseded/deprecated
documents "as history". Most conservative reading (S11): validate reports
`E-TARGET-*` only for directed non-`supersedes` edges (the §7.6/§8 prose), so
history edges are not errors, while every non-`supersedes` link to a dead
target still warns `W-LINK-STALE`. Confirm, or align `check_link` and validate
on one side of the wording.

SPEC-QUESTION: Are `supersedes` links stale? Applied mechanically, §7.4
("target is deprecated or superseded, regardless of version") makes every
edge of a supersession chain permanently `W-LINK-STALE`, and §13.5's
`link refresh --follow` ("re-point to the successor") would rewrite
`C supersedes A` onto its own successor. §7.6's "OLD's inbound links are left
untouched; they become stale" reads as links that *predate* the supersession.
Most conservative reading (S11): `supersedes` links are exempt from
`W-LINK-STALE` (and from `E-TARGET-*`, which §7.6/§8 already exempt); chains
and forks are quiet. Confirm the §7.4 definition should say so.

SPEC-QUESTION: Does `W-MENTION-UNLINKED` fire for a document's mention of its
own ID? §5.2 says "mentions a document ID with no edge either way" and names
only the CR exemption; literally a self-mention has no edge, but no self-edge
is a sane fix (self `refines` is `E-CYCLE`; a self `relates-to` is nonsense),
so the warning would be permanent noise. Most conservative reading (S11):
self-mentions are exempt alongside CR IDs. Confirm, or define the legal
self-reference fix.

SPEC-QUESTION: How do `E-LINK-TYPE-UNKNOWN` and `E-SIDECAR-INVALID` split an
unknown edge type? `Link.type` is a typed literal (appendix B.3), so a
hand-edited `"type": "refine"` fails sidecar schema at load time and reports
`E-SIDECAR-INVALID`; the specific code is then only visible in the raw JSON.
Most conservative reading (S11): validate scans raw document sidecars for
`links[].type` outside the fixed set and reports `E-LINK-TYPE-UNKNOWN`
*in addition to* the load-layer `E-SIDECAR-INVALID` (both fire). Confirm, or
make the load layer report the specific code instead of/alongside the generic
one, or drop one of the two catalogue rows for this case.

SPEC-QUESTION: Which codes carry the §13 refusal findings that the §14
catalogue does not list? §13.3 names `E-CYCLE`/`E-EDGE-*`/`E-TARGET-*`, §13.5
names `E-SUPERSEDE-FORK` (itself absent from §14's table), but naming a
non-existent ID as an argument (`link` source, `set`, `supersede`,
`deprecate`, `link refresh --from/--to`, `new --cr`), an unsupported `set` key
(§13.6 "refused with a pointer to the right command"), a malformed assignment
or a tag outside the §5.4 `[a-z0-9-]+` format have no catalogue code at all —
yet §16.2 requires refusals to raise `OperationRefused` *with a Finding* (code
is mandatory). Most conservative reading (S12): `E-ID-UNKNOWN`, `E-SET-KEY`,
`E-SET-VALUE` and `E-TAG-INVALID` as refusal-only codes (never emitted by
`validate`), mirroring the spec-named `E-SUPERSEDE-FORK`; `E-TYPE-UNKNOWN`,
`E-TEMPLATE-UNKNOWN`, `E-LINK-TARGET-MISSING`, `E-CR-DISABLED` are reused
where they fit. Confirm the official codes or add a §14 "refusal codes" row
set for them.

SPEC-QUESTION: `supersede` defaults for the multi-target compromise (§7.6.6)
are underspecified. (a) With no `--type` and targets of different types (same
kind), which type does the new document get? S12 uses the first target's type
and prints a notice. (b) "copy-body (default on when the template is the
same)": is "the template" the (name, version) pin (S12: on iff every target
pins exactly the resolved name+version, so an evolved template means no copy)
or just the template name (copy across versions)? (c) When a copied edge fails
the §13.3 checks ("cycle and rule checks run for each"), does the whole
supersede refuse or is only that edge dropped? S12 drops it and lists the
refusal in `skipped_links` (§11.2 "duplicates collapsed and shown for
review"; a compromise must still succeed when A and B hold incompatible
links). (d) Multi-target `--copy-body` copies the *first* target's body —
merge semantics are undefined.

SPEC-QUESTION: `link refresh` on a stale link *without* `--follow` ("offers
(interactive) or performs (`--follow`) re-pointing", §13.5/§7.6.5): when the
user declines or interactivity is unavailable, does the command still write
`target_version` to the (dead) target's effective version (the sentence "Sets
target_version … for the selected links" is unconditional) or leave the link
completely untouched? S12 leaves it untouched and reports it with its
supersession chain (`W-LINK-STALE`), because a stale link is stale "regardless
of version" (§7.4) so a version write is a meaningless diff. Also confirm the
re-point exemptions: S12 never re-points `supersedes` links (S11: chains stay
quiet) or `conflicts-with` links (§11.2 "it remains on the superseded/
deprecated documents as history"), while `--follow` still refuses
`E-TARGET-DEPRECATED` for `conflicts-with` targets (the §11.2 pattern-2
"reviewer decides" path is `unlink`/re-link).

SPEC-QUESTION: The §15 ">300 nodes" warning has no catalogue code (§14 has
no row for it) and no natural subject: it is diagram-level, while `Finding`
subjects are document/CR IDs or repository paths (§14 `validate --json`
shape). S16 returns it as a `Finding` with the invented code `W-GRAPH-LARGE`,
subject `Path("graph")`, and `fix` suggesting `--root`. Add a §14 row and a
subject convention for command-level warnings, or confirm the warning stays
plain text outside the `Finding` catalogue.

SPEC-QUESTION: §13.13's default scope excludes deprecated *and* superseded
nodes, but the only widening flag is `--include-superseded` — how do
deprecated nodes ever get included? §15 says "Deprecated/superseded nodes
(when included) get a `classDef` with dashed border", which implies one
inclusion switch covering both. S16 reads `include_superseded` as "include
deprecated and superseded nodes" (one switch, one dashed classDef). Confirm,
or add `--include-deprecated` to §13.13.

SPEC-QUESTION: `--depth N` without `--root` is undefined (§13.13 lists them
as separate flags, §15 only defines `--root ID --depth N` together). S16
ignores `depth` unless `roots` are given — it only limits the root downstream
subgraph. Also: "Title truncated to 40 chars" (§15) does not say whether the
truncation marker is an ellipsis; S16 truncates plainly (`title[:40]`).

SPEC-QUESTION: What exactly does `scope_hash` cover (§9.2 "sha256 of the
canonical JSON of `scope` (sorted by `id`)")? S9's `versioning.scope_hash`
hashes the sorted **id list** only (its tests lock "intent changes do not
change the scope hash"), so `intent`/`base_version` changes are invisible to
the reconcile inputs. S13 stores exactly that hash (so the stored field and
reconcile can never disagree) and records `cr reanalyze` base-version updates
as explicit one-step version bumps, which is what makes BOOT-302's
`W-CR-MODIFIED-AFTER-DECISION` fire. If `scope_hash` is meant to hash the full
entries (`id`, `intent`, `base_version`), S9's helper needs to change and the
explicit bump can go away.

SPEC-QUESTION: Which decision does `W-CR-MODIFIED-AFTER-DECISION` compare
against (§9.3)? The spec text is "if the **last decision** is not `open` and
the effective version is greater than that decision's `at_version`"; the S13
handoff paraphrases it as "the last **non-open** decision's `at_version`".
S13 implements the §9.3 text: after a reopen the warning is silent (that is
the point of reopening) and it returns when the CR is decided again. The
paraphrase would keep warning through the open state until re-decision.

SPEC-QUESTION: Is an empty `decisions` list valid? §9.2 says "lists may be
empty" while §9.3 says creation appends the initial `open` decision with
`at_version = 1`. S13 reports `E-CR-STATUS` ("missing the initial open
decision") for an empty history — the strict reading of the state machine
`(created) → open`. Confirm, or make `decisions: []` a silent valid state.

SPEC-QUESTION: Is `cr set CR status=<current>` a transition (§9.3 table has
no self-transitions) or a reaffirmation? S13 refuses it with `E-CR-STATUS`
and points at `gregraph cr reaffirm CR`, keeping one command per intent.
Confirm, or allow `cr set` to append same-status decisions like `reaffirm`.

SPEC-QUESTION: Does the §9.8 impact set include the scope targets themselves?
"for every scope target, one level upstream and unlimited depth downstream"
reads as the neighbour set (the targets are already listed as scope rows);
S13 excludes them (and de-duplicates across targets). Confirm the Impact
section wants only the beyond-scope fallout.

SPEC-QUESTION: §9.2 says the CR body "is validated against it exactly like a
document body (section 5.5)" and "the H1 rule (5.6) applies", but S10's
template/section/title checks iterate `index.documents` only (while the
identifier/serialisation checks iterate documents **and** CRs). S13's CR
check therefore applies §5.5/§5.6 to CR bodies itself (E-TITLE-MISSING,
E-TEMPLATE-UNKNOWN, W-TEMPLATE-DEPRECATED, E-SECTION-*, W-SECTION-*). It does
not apply `E-FRONTMATTER-FORBIDDEN` (§5.2) to CR bodies — confirm the full
§5.2 convention set should cover CRs too, or that S10's checks should iterate
CRs instead.

SPEC-QUESTION: Should drift cover a CR whose effective status is `none` (§9.6
evaluates drift "only while the CR's effective status is `open` or
`accepted`")? A never-merged CR (single-PR workflow before the merge) has no
effective status and gets no drift check. BOOT-302 passes because the CR is
merged first (proposal-first); confirm drift should also run for `none`, or
that `none` counts as "not yet effective, no drift".

SPEC-QUESTION: Which refusal codes carry the §13.20 term refusals that the §14
catalogue does not list? The catalogue has exactly two term rows
(`E-TERM-SLUG` "slug/filename mismatch or H1 ≠ term", `E-TERM-ALIAS-CLASH`
"Alias collides") but `term add` must also refuse an already-taken slug
(§10.2 lists "slug uniqueness" under validation without naming a code) and
every `term` command must refuse an unknown slug (§16.2 requires refusals to
carry a Finding). Most conservative reading (S14): slug-taken refusals reuse
`E-TERM-SLUG` (the only slug code; it is what `validate` would report for a
duplicate identity), unknown/ambiguous slugs use the refusal-only
`E-TERM-UNKNOWN` (mirroring S12's `E-ID-UNKNOWN`, never emitted by `validate`),
and blank names/aliases are argument-shape errors raising `ValueError` (like
`link refresh`'s selector errors). Confirm the official codes or add §14 rows
for them.

SPEC-QUESTION: What does "non-alphanumerics → `-`" mean for non-ASCII
characters in the §10.2 slug derivation? Keeping Unicode alphanumerics
(`str.isalnum`) preserves "Übertragung" → "übertragung" but allows non-ASCII
file names; an ASCII-only reading (`[^a-z0-9]`) slugs portably but maps a CJK
term to the empty slug (refused). Most conservative reading (S14): keep
Unicode alphanumerics — the spec says "non-alphanumerics", not "non-ASCII" —
and NFC-normalise the name first so composed characters slug identically on
every platform (macOS stores NFD). Confirm, or pin slugs to `[a-z0-9-]+`.

SPEC-QUESTION: How exactly does §4.4's `repair regenerate-id` tell "inbound
links that reference it *from the same branch's history*" apart from the
ambiguous ones? §4.4 says inbound links "cannot be disambiguated
automatically", yet only "the rest" is listed for manual re-linking; the
GitAdapter has no log/merge-base method to reconstruct which merge parent a
link came from. Most conservative reading (S15): rewrite every `Link` whose
`target` equals the old ID when the source sidecar is part of the current
branch's git history (tracked, or everything when there is no git/commit —
the working tree is then the whole history), and list for manual re-linking:
links in untracked sources, body mentions/markdown links of the old ID and CR
`scope`/`introduces` references. A notice warns that rewritten links may have
meant the twin that keeps the old ID. Confirm the official disambiguation
(e.g. merge-parent trees via `HEAD^1`/`HEAD^2`) or accept this.

SPEC-QUESTION: §12.4 gives `baseline create` two refusal conditions
("uncommitted changes under managed directories", "validate reports errors")
but §14 has no rows for these — nor for "not a git repository", "no commits
to tag" or "tag already exists" — and the baseline manifest's format is
"fixed now so that v0.2 can diff them" without ever being specified. S15
uses refusal-only codes `E-GIT-UNAVAILABLE`, `E-BASELINE-UNCOMMITTED`,
`E-BASELINE-INVALID` and `E-BASELINE-EXISTS`, and a manifest of canonical
JSON (`schema`, `tool_version`, `id_prefix`, `documents: [{id, version,
body_hash, status}]`, documents sorted by id) embedded in the annotated tag
message after the optional `-m` text. Confirm the codes/format or add §14
rows and a §12.4 manifest listing.

SPEC-QUESTION: §13.17 `template bump NAME [--breaking]` says "copy latest
version to next version", but §5.5 defines `breaking` as a property of the
step *to* that version — copying the previous version's flag would mislabel
the new step. S15 sets the new version's `breaking` to exactly the flag
(default `false`). Likewise `template add BUILTIN` on an existing name copies
the built-in's *v1* sections as the repository's next version — confirm a
builtin may introduce new sections into an existing template lineage this
way, or that `add` should refuse when the name exists.

SPEC-QUESTION: §12.6 says "resolve the JSON to any syntactically valid state
(or leave conflict markers), then run `gregraph repair versions` which
recomputes `version` …", but §7.2 defines `version = max(versions seen in
conflict markers) + 1`, which requires the markers. A sidecar already
resolved to valid JSON no longer exposes both versions, so S15's `repair
versions` only touches sidecars that still carry conflict markers (a clean
repo reports "no conflicted sidecars found") and leaves resolved sidecars to
`sync`/the hook. Also note S9's clamp compares `links[].target_version`
against the *repaired source's* version (the only value available to the
pure text function), not against the target document's version — confirm
that is the intended clamp.

SPEC-QUESTION: §13.1 offers `--templates all|minimal` for `init` but never
defines the minimal set. S17 implements `minimal` as "every template the
default configuration references" (each `[types.*] template`, `cr.template`,
and the shipped `term` template) — today that is all 14 built-ins, so `all`
and `minimal` coincide and the flag only gains meaning once more built-ins
ship. Confirm the intended minimal subset (e.g. a starter kit) or bless the
definition.

SPEC-QUESTION: §13.10's `list --outdated` and `list --stale` describe
link-freshness states (§7.4), not document states, and the direction is
ambiguous (source-side vs target-side). S17 implements them as documents with
at least one outbound link that `validate` would report `W-LINK-OUTDATED` /
`W-LINK-STALE` for (so `supersedes` edges onto superseded targets are
excluded, matching §14's reporting choice). Confirm, or define target-side
filters ("documents whose readers are behind").

S17 note (not a spec gap): `tests/core/test_operations.py::
test_stubs_not_implemented` asserted `NotImplementedError` for
`init_repository`/`show_document`/`sync`. S17 implemented the first two
(stubs it owns, per its task) and trimmed the scaffold test to `sync`; S18
must remove `sync` from it when implementing `sync` (deleting the test once
no stubs remain).

SPEC-QUESTION: §7.4's effective-version rule lets `link refresh` store
`target_version = target.version + 1` while the target has unbumped
modifications (so an edit and its refresh travel in one commit), but §14
defines `E-LINK-VERSION-AHEAD` as "target_version > target.version" — so a
just-refreshed link reads as an *error* in `validate` (and in report-mode
`check`) until the hook bumps the target. The hypothesis test of S9 pins the
invariant as `target_version <= effective version`. Confirm that
`E-LINK-VERSION-AHEAD` should compare against the target's *effective*
version; until then `validate` reports it literally (§14) while `check` drops
the findings its own would-be bump would resolve so its exit code matches
`hook pre-commit` (which bumps first, §7.5 step order).

SPEC-QUESTION: §7.5 defines newly outdated links as "those whose target is in
the bumped set and target_version < new version", which includes links that
were *already* outdated before the commit — but §7.1 refinement 2 says links
already outdated before the commit "are reported but never block". S18's
`check` and S19's `hook pre-commit` implement the refinement-2 reading (a
link blocks only when it is outdated after the run and was not outdated
before), so a target that is re-bumped while some link is already behind does
not block. Confirm the refinement-2 reading wins.

SPEC-QUESTION: §7.5 step 1 defines reconcile for "each document" and "each
CR", but the hook scope also covers `glossary/`, and glossary terms carry
`version` and `body_hash` (§10.2/appendix B.3). S18's `sync`/`check` (and the
hook) reconcile terms as body-hash-only items — no H1 title sync (a term's H1
is validated as the term name, `E-TERM-SLUG`), no assets — and `sync`
normalises term bodies with the rest. Confirm, or give terms a §7.5 step.

SPEC-QUESTION: §8's WIP header example is `WIP: yes (3 drafts, 1 modified)`
but WIP has three causes (drafts, unbumped modifications, uncommitted files).
S18 prints `WIP: yes (…)` with the non-zero categories in the order drafts,
modified, uncommitted (`draft` singularises; the spec example form is
reproduced exactly for its counts) and `WIP: no` when all are zero. Confirm
the extended format (or pin a fixed two-count format and say what a
uncommitted-only repository prints).

SPEC-QUESTION: §13 lists `--json` for `check` and `graph` but only §14
defines a shape (validate's `[{code, severity, id|path, message, fix?}]`).
S18 emits `check --json` as `{blocked, block_reasons, would_bump, findings,
newly_outdated: [{source, type, target, target_version, new_version, fix}]}`
and `graph --json` as `{diagram, findings}`. Confirm or specify. Likewise
§13.9's `--only-errors` is implemented as a *display* filter — the exit code
still sees the full report, so `validate --strict --only-errors` exits 1 on
warnings while printing nothing; confirm.

SPEC-QUESTION (impl gap, S9): `versioning.reconcile` recomputes assets as
`AssetRef(path="assets/<ID>/…", hash="")` and `_assets_changed` compares that
shape against the stored convention (path relative to `assets/<ID>/` with a
raw-byte hash, §5.7/§7.3), so every document with stored assets reads as
"changed" on each pass and a bump rewrites the list into the wrong shape.
S18's `sync`/`check` therefore detect content changes per §7.3 directly (the
same rule `hook_pre_commit` uses) instead of calling `reconcile`; `reconcile`
should hash asset bytes (it has `body_path` already) or document that callers
must.

S18 note (not a spec gap): `tests/cli/test_cli_framework.py`'s
`test_unimplemented_command_exits_5`/`test_link_refresh_routes_to_refresh_stub`
asserted exit 5 for `sync`/`link refresh`; S18 rewrote them for the
implemented commands (the exit-5 dispatch fallback now uses a monkeypatched
missing module). `test_stubs_not_implemented` in `tests/core/test_operations.py`
was deleted per the S17 note above.

SPEC-QUESTION (S19): §12.6 says the merge-conflict guidance is "printed by
`gregraph repair --help`", but the `repair` parser (and its `--help`) lives in
S17-owned `gregraph/cli/main.py`, which S19 may not edit. `repair --help`
therefore shows only argparse's subcommand listing; S19 prints the three
`versioning.repair_guidance()` bullets (and the usage line) when `gregraph
repair` is invoked without a subcommand (exit 2). Confirm this is acceptable,
or move the guidance into the parser when main.py next opens for edits (same
question applies to `link --help` and the §6.1 edge guidelines).

SPEC-QUESTION (S19): §7.2 says the version increment "happens in the
pre-commit hook for staged files" and "uncommitted edits do not bump", while
§7.1 refinement 1 says the hook and non-Git `sync` "share one code path"
(which reads working-tree text). S19's hook hashes the *staged* content (the
Git index — `git show :<path>`) so the committed (body, sidecar) pair is
consistent and mixed staged/unstaged edits only bump for the staged part;
`sync`/`check` hash the working tree. The freshness table is computed over
the working tree (as `check` does), so a `link refresh` that is not staged
can slip through the hook's block; "newly outdated" is defined against
`HEAD` (not against the previous hook run) so an aborted commit cannot be
re-run past the block without a refresh. Confirm the staged-content reading
of §7.2 and the HEAD-relative definition of "newly outdated by the commit in
progress" (§7.1 refinement 2).

## Release gate notes (S21)

Process notes and deferrals from closing out v0.1.0 (spec §17, §16.4,
appendix C definition of done minus M6). No behaviour changes were needed.

The workspace had no VCS history during S0–S20, so the implementation lands
as one import commit and the milestone tags `m1`–`m5` (spec §18) all point at
the release commit; each tag message records the milestone's acceptance row.
A history-savvy maintainer may re-tag if a reconstructed milestone history is
ever materialised.

`pipx run gregraph --version` as written in the S21 brief resolves the bare
name from PyPI. gregraph 0.1.0 is not published to an index (spec §16.4
requires `pip install .` / `pipx install .` installability, not an index
release), so the smoke was run as `pipx run --spec . gregraph --version`
against the local checkout, and `pipx install .` + running the installed
console script covers the installed-artifact path. Publishing to PyPI
remains an open release-engineering decision for v0.2.

The CI matrix (Linux/macOS/Windows × 3.12/3.13) is defined in
`.github/workflows/ci.yml`. The full quality gate was verified in this
sandbox on Linux for both 3.12 and 3.13 (ruff check/format, `mypy --strict`,
pytest); the macOS and Windows legs cannot be executed here and are verified
by the first CI run against the `v0.1.0` tag.

## Dogfooding findings (S22 / M6)

Seeding `gregraph-requirements` per design §19 with the released tool (79
documents, 83 links from appendix A, commits through the pre-commit hook,
`validate --strict` clean). The hook's blocking path worked as designed
(BOOT-108 aborted one commit and printed the offending findings). One
blocking spec violation was found and fixed in 0.1.1; the rest is deferred.

FIXED in 0.1.1 — `init` inside an enclosing Git work tree skipped `git init`
and installed a dead hook (spec §13.1, BOOT-100). `GitAdapter.is_repo()`
answers "is inside a work tree", so a nested directory already looked like a
repository; `hooks.install` then fabricated `PATH/.git/hooks/pre-commit`,
which real Git never executes. The first seeding attempt therefore committed
all content into the *tool* repository and never ran the gregraph hook.
`init_repository` now treats PATH as a repository only when it is the Git
toplevel of its own repository and runs `git init` otherwise. Regression
test: `tests/cli/test_init.py::`\
`test_init_in_subdirectory_of_worktree_creates_own_repository`.

SPEC-QUESTION (new; dogfooding): mention detection treats any ID-shaped
token as an ID mention (§4.5 matching is case-insensitive), so hyphenated
prose whose second half happens to be six Crockford characters — e.g.
"multi-target", "baseline-branch" — fires `E-MENTION-UNKNOWN` and the
pre-commit hook blocks the commit. This blocked one M6 seed commit; worked
around by rewording the prose. Should mention scanning require the
configured prefix, an existing ID body, or the canonical uppercase form?
§5.2's "mentions a document ID" is ambiguous for hyphenated prose.

SPEC-QUESTION (confirmation of the §7.4 effective-version question above):
the M6 seeding hit the `E-LINK-VERSION-AHEAD` vs effective-version
contradiction in a pure CLI run — `link`/`new --link` records
`target_version = version + 1` while a target has unbumped modifications,
which `validate` reports as an *error* until the hook bumps the target.
Seeding ordered content commits before link commits to avoid it; no
behaviour change in 0.1.1.

SPEC-QUESTION (new): `GitAdapter.is_repo()` is documented as "Whether the
working directory root is a Git repository" but implements "is inside a
work tree". For a workspace that is a subdirectory of a foreign work tree,
`hooks install` writes the block into the *foreign* repository's hooks dir,
where githooks' toplevel cwd rule means `gregraph hook pre-commit` cannot
discover the workspace and would exit 3 on every foreign commit. v0.1.1
narrows the supported configuration to one gregraph repository per Git
repository root; should `hooks install`/`hook pre-commit` refuse non-root
workspaces, or should the hook script embed `--repo`? Related: should
`hook pre-commit` exit 0 ("nothing to reconcile", as its core function
already reports) instead of the §13 exit-3 "no repository found" when
invoked outside a gregraph repository? Deferred.

Observation (no action): a document created with `new` and then filled in
lands at version 2 in its first hook commit (the stored v1 hash is the
template skeleton's; §7.2's hash-based bump at the first commit is
correct). The v1 skeleton is never committed. A body input on `new` (flag or
stdin) would let version 1 be the real content; v0.2 idea.

## Accepted residual risks (optional web UI, design §21.5)

These are known constraints that are accepted for the first version. They are not
open defects and have no planned fix.

- Writes from outside the `serve` process (another terminal, an editor, Git) are
  not locked. The stale check (`E-BODY-STALE`) is a best-effort guard, not an atomic
  compare-and-swap, so an external race between the check and the write remains
  possible.
- The body file and its sidecar title are written by two separate steps. A crash
  between them can leave the title out of date until the next sync or save. The
  sidecar write itself is not atomic, so a crash during it can leave a truncated
  sidecar (`E-SIDECAR-INVALID`).
