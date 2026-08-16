"""Proposals to acquire media, kept separate from what the corpus already holds.

A proposal has no bytes: it is a claim that a page found by search might be
worth downloading, made before anyone has looked at it. `CorpusState`'s guards
are all preconditions about *stored* sources -- kind flips, derivedness,
transcript repointing, digest supersession -- and a proposal satisfies none of
them, so folding it into `Corpus` would mean qualifying every existing guard
with "unless this one is a proposal": eight places to get right and one place
to get wrong. This aggregate is keyed per project instead, and `Corpus` stays
the aggregate that holds what exists. See "The proposal aggregate" in
docs/superpowers/specs/2026-08-16-media-acquisition-design.md.

**Rejecting is not blacklisting.** `MediaProposalRejected` closes one record --
`decide` still refuses accepting it afterwards, because a closed decision is
closed -- but it does not touch `ignored_assets` or `ignored_hosts`. A fresh
`MediaProposed` for the same asset is a new record with a new id, and `decide`
allows it. Rejection is usually a judgement about a moment ("not for this
need", "not the best of these three"), and a permanent refusal derived from a
momentary judgement is the kind of state nobody remembers setting. Ignoring is
the separate, explicit way to say never again, at either the asset grain or
the host grain, and both are reversible: a blacklist with no way back is a
trap a single misclick sets permanently. See "Rejecting is not blacklisting"
in the design doc for the full reasoning;
`test_a_previously_rejected_asset_may_be_proposed_again` in the test module
pins the behaviour so a later "helpful" guard against re-proposing a rejected
asset cannot creep back in.

Ignore keys are `normalize_url(asset_url)` for assets and lowercased
`urlsplit(url).hostname` for hosts -- no new normalization, and specifically
no suffix matching: `example.com` does not cover `cdn.example.com`, for the
reason `FetchGrant` gives for the same decision
(`research_team/application/grants.py`) -- getting suffix matching right needs
public-suffix knowledge this project does not have, and a person ignoring two
hosts can name two hosts.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

from research_team.domain.urls import normalize_url


@register_event
class MediaNeedsIdentified(DomainEvent):
    """Stage 1's output: what a topic could use media for, not yet searched.

    `needs` is a JSON list of `{need_id, medium, description, why}` objects
    rather than a structured field, mirroring `CorpusDerivedTextStored.locator_map`
    in `corpus.py`: the shape of a "need" belongs to the stage-1 prompt and
    will be iterated on there, and a structured field here would make every
    change to it a schema change in this repository for no reader-visible
    gain -- the list is read whole by stage 2, not queried by field.
    """

    aggregate_type: str = "MediaProposals"
    project_id: str
    topic_id: str
    needs: str
    model_version: str


@register_event
class MediaProposed(DomainEvent):
    """One surviving candidate, after search and stage 3's judgement.

    `query` is carried because a proposal nobody can trace back to the search
    that found it is unauditable -- the design doc's phrase for exactly this
    field.
    """

    aggregate_type: str = "MediaProposals"
    project_id: str
    proposal_id: str
    need_id: str
    topic_id: str
    page_url: str
    asset_url: str
    thumbnail_url: str | None
    kind: str
    title: str
    reason: str
    query: str


@register_event
class MediaProposalAccepted(DomainEvent):
    aggregate_type: str = "MediaProposals"
    proposal_id: str


@register_event
class MediaProposalRejected(DomainEvent):
    """A proposal turned down. `note` is optional free text.

    Optional rather than required: a required reason is a click on every
    rejection, and most rejections are obvious. When someone does type one it
    is the only signal there will ever be for tuning stage 3's prompt.
    """

    aggregate_type: str = "MediaProposals"
    proposal_id: str
    note: str = ""


@register_event
class MediaProposalStored(DomainEvent):
    """An accepted proposal's bytes landed in the corpus, under this id."""

    aggregate_type: str = "MediaProposals"
    proposal_id: str
    source_id: str


@register_event
class MediaProposalFailed(DomainEvent):
    aggregate_type: str = "MediaProposals"
    proposal_id: str
    error: str


@register_event
class MediaAssetIgnored(DomainEvent):
    aggregate_type: str = "MediaProposals"
    project_id: str
    asset_key: str


@register_event
class MediaAssetUnignored(DomainEvent):
    aggregate_type: str = "MediaProposals"
    project_id: str
    asset_key: str


@register_event
class MediaHostIgnored(DomainEvent):
    aggregate_type: str = "MediaProposals"
    project_id: str
    host: str


@register_event
class MediaHostUnignored(DomainEvent):
    aggregate_type: str = "MediaProposals"
    project_id: str
    host: str


@dataclass(frozen=True)
class IdentifyMediaNeeds:
    project_id: str
    topic_id: str
    needs: str
    model_version: str


@dataclass(frozen=True)
class ProposeMedia:
    project_id: str
    proposal_id: str
    need_id: str
    topic_id: str
    page_url: str
    asset_url: str
    thumbnail_url: str | None
    kind: str
    title: str
    reason: str
    query: str


@dataclass(frozen=True)
class AcceptMediaProposal:
    project_id: str
    proposal_id: str


@dataclass(frozen=True)
class RejectMediaProposal:
    project_id: str
    proposal_id: str
    note: str = ""


@dataclass(frozen=True)
class StoreMediaProposal:
    project_id: str
    proposal_id: str
    source_id: str


@dataclass(frozen=True)
class FailMediaProposal:
    project_id: str
    proposal_id: str
    error: str


@dataclass(frozen=True)
class IgnoreMediaAsset:
    project_id: str
    asset_key: str


@dataclass(frozen=True)
class UnignoreMediaAsset:
    project_id: str
    asset_key: str


@dataclass(frozen=True)
class IgnoreMediaHost:
    project_id: str
    host: str


@dataclass(frozen=True)
class UnignoreMediaHost:
    project_id: str
    host: str


MediaProposalsCommand = (
    IdentifyMediaNeeds
    | ProposeMedia
    | AcceptMediaProposal
    | RejectMediaProposal
    | StoreMediaProposal
    | FailMediaProposal
    | IgnoreMediaAsset
    | UnignoreMediaAsset
    | IgnoreMediaHost
    | UnignoreMediaHost
)


class ProposalRecord(BaseModel):
    """One proposal's current status, folded from its events.

    `status` is the only thing `decide` reads to guard the lifecycle
    (`proposed -> accepted -> stored | failed`, or `proposed -> rejected`);
    the rest is carried for `MediaAssetIgnored`'s key derivation and for
    readers.
    """

    proposal_id: str
    asset_url: str
    status: str = "proposed"


class MediaProposalState(BaseModel):
    """Everything derivable from one project's proposal stream."""

    proposals: dict[str, ProposalRecord] = Field(default_factory=dict)
    ignored_assets: frozenset[str] = frozenset()
    ignored_hosts: frozenset[str] = frozenset()


def initial_state() -> MediaProposalState:
    return MediaProposalState()


def _host_of(url: str) -> str:
    """The comparison key for `ignored_hosts`: lowercased, nothing else.

    No suffix matching -- see this module's docstring. `urlsplit` never
    raises on text a model wrote (unlike `.port`, `.hostname` does not parse
    a number), so this is total without `normalize_url`'s try/except.
    """
    return (urlsplit(url).hostname or "").lower()


def decide(command: MediaProposalsCommand, state: MediaProposalState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `corpus.decide` does.
    """
    match command, state:
        case ProposeMedia(asset_url=asset_url), _ if (
            normalize_url(asset_url) in state.ignored_assets
        ):
            raise CommandRejectedError(f"asset {asset_url!r} is ignored")

        case ProposeMedia(asset_url=asset_url), _ if (
            _host_of(asset_url) in state.ignored_hosts
        ):
            raise CommandRejectedError(f"host of {asset_url!r} is ignored")

        case ProposeMedia(), _:
            return [
                MediaProposed(
                    aggregate_id=UUID(command.project_id),
                    project_id=command.project_id,
                    proposal_id=command.proposal_id,
                    need_id=command.need_id,
                    topic_id=command.topic_id,
                    page_url=command.page_url,
                    asset_url=command.asset_url,
                    thumbnail_url=command.thumbnail_url,
                    kind=command.kind,
                    title=command.title,
                    reason=command.reason,
                    query=command.query,
                )
            ]

        case IdentifyMediaNeeds(), _:
            return [
                MediaNeedsIdentified(
                    aggregate_id=UUID(command.project_id),
                    project_id=command.project_id,
                    topic_id=command.topic_id,
                    needs=command.needs,
                    model_version=command.model_version,
                )
            ]

        case IgnoreMediaAsset(asset_key=asset_key), _:
            return [
                MediaAssetIgnored(
                    aggregate_id=UUID(command.project_id),
                    project_id=command.project_id,
                    asset_key=normalize_url(asset_key),
                )
            ]

        case UnignoreMediaAsset(asset_key=asset_key), _:
            return [
                MediaAssetUnignored(
                    aggregate_id=UUID(command.project_id),
                    project_id=command.project_id,
                    asset_key=normalize_url(asset_key),
                )
            ]

        case IgnoreMediaHost(host=host), _:
            return [
                MediaHostIgnored(
                    aggregate_id=UUID(command.project_id),
                    project_id=command.project_id,
                    host=host.lower(),
                )
            ]

        case UnignoreMediaHost(host=host), _:
            return [
                MediaHostUnignored(
                    aggregate_id=UUID(command.project_id),
                    project_id=command.project_id,
                    host=host.lower(),
                )
            ]

        # Every command below names a proposal by id, so the unknown-id guard
        # comes first and the lifecycle guards after it can assume the record
        # exists.
        case (
            (
                AcceptMediaProposal(proposal_id=proposal_id)
                | RejectMediaProposal(proposal_id=proposal_id)
                | StoreMediaProposal(proposal_id=proposal_id)
                | FailMediaProposal(proposal_id=proposal_id)
            ),
            _,
        ) if proposal_id not in state.proposals:
            raise CommandRejectedError(f"unknown proposal {proposal_id!r}")

        case AcceptMediaProposal(proposal_id=proposal_id), _ if (
            state.proposals[proposal_id].status != "proposed"
        ):
            raise CommandRejectedError(
                f"proposal {proposal_id!r} is {state.proposals[proposal_id].status!r}, "
                "not proposed; a closed decision is closed"
            )

        case AcceptMediaProposal(), _:
            return [
                MediaProposalAccepted(
                    aggregate_id=UUID(command.project_id), proposal_id=command.proposal_id
                )
            ]

        case RejectMediaProposal(proposal_id=proposal_id), _ if (
            state.proposals[proposal_id].status != "proposed"
        ):
            raise CommandRejectedError(
                f"proposal {proposal_id!r} is {state.proposals[proposal_id].status!r}, "
                "not proposed; a closed decision is closed"
            )

        case RejectMediaProposal(), _:
            return [
                MediaProposalRejected(
                    aggregate_id=UUID(command.project_id),
                    proposal_id=command.proposal_id,
                    note=command.note,
                )
            ]

        case StoreMediaProposal(proposal_id=proposal_id), _ if (
            state.proposals[proposal_id].status != "accepted"
        ):
            raise CommandRejectedError(
                f"proposal {proposal_id!r} is {state.proposals[proposal_id].status!r}, "
                "not accepted; storing answers acceptance, not a proposal"
            )

        case StoreMediaProposal(), _:
            return [
                MediaProposalStored(
                    aggregate_id=UUID(command.project_id),
                    proposal_id=command.proposal_id,
                    source_id=command.source_id,
                )
            ]

        case FailMediaProposal(proposal_id=proposal_id), _ if (
            state.proposals[proposal_id].status != "accepted"
        ):
            raise CommandRejectedError(
                f"proposal {proposal_id!r} is {state.proposals[proposal_id].status!r}, "
                "not accepted; failing answers acceptance, not a proposal"
            )

        case FailMediaProposal(), _:
            return [
                MediaProposalFailed(
                    aggregate_id=UUID(command.project_id),
                    proposal_id=command.proposal_id,
                    error=command.error,
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: MediaProposalState, event: DomainEvent) -> MediaProposalState:
    """What each fact does to the state.

    Total on purpose, matching `corpus.evolve`: an unknown event leaves the
    state alone rather than raising, so a stream carrying an event this build
    does not know about still replays instead of failing halfway through.
    """
    match event:
        case MediaProposed():
            record = ProposalRecord(proposal_id=event.proposal_id, asset_url=event.asset_url)
            return state.model_copy(
                update={"proposals": {**state.proposals, event.proposal_id: record}}
            )

        case MediaProposalAccepted():
            record = state.proposals.get(event.proposal_id)
            if record is None:
                return state
            return state.model_copy(
                update={
                    "proposals": {
                        **state.proposals,
                        event.proposal_id: record.model_copy(update={"status": "accepted"}),
                    }
                }
            )

        case MediaProposalRejected():
            record = state.proposals.get(event.proposal_id)
            if record is None:
                return state
            return state.model_copy(
                update={
                    "proposals": {
                        **state.proposals,
                        event.proposal_id: record.model_copy(update={"status": "rejected"}),
                    }
                }
            )

        case MediaProposalStored():
            record = state.proposals.get(event.proposal_id)
            if record is None:
                return state
            return state.model_copy(
                update={
                    "proposals": {
                        **state.proposals,
                        event.proposal_id: record.model_copy(update={"status": "stored"}),
                    }
                }
            )

        case MediaProposalFailed():
            record = state.proposals.get(event.proposal_id)
            if record is None:
                return state
            return state.model_copy(
                update={
                    "proposals": {
                        **state.proposals,
                        event.proposal_id: record.model_copy(update={"status": "failed"}),
                    }
                }
            )

        case MediaAssetIgnored():
            return state.model_copy(
                update={"ignored_assets": state.ignored_assets | {event.asset_key}}
            )

        case MediaAssetUnignored():
            return state.model_copy(
                update={"ignored_assets": state.ignored_assets - {event.asset_key}}
            )

        case MediaHostIgnored():
            return state.model_copy(
                update={"ignored_hosts": state.ignored_hosts | {event.host}}
            )

        case MediaHostUnignored():
            return state.model_copy(
                update={"ignored_hosts": state.ignored_hosts - {event.host}}
            )

        case _:
            return state


class MediaProposals(DeciderAggregate[MediaProposalState, MediaProposalsCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Corpus`'s shape exactly: the class attributes bind directly to
    the module-level functions rather than wrapping them in new method bodies,
    so there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "MediaProposals"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
