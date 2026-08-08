"""Reading topics back, in this application's own terms.

`TopicPort` is four tools -- `list_topics`, `open_topic`, `record_finding`,
`link_source` -- and its meaning is "what the model may do". A page that wants
to show a project's topics is not a model deciding anything; wiring it through
`TopicPort` would mean either adding read shapes to a port whose whole
vocabulary is agent actions, or routing a browser request through the tool
layer to get there. This is the second port instead, the way `CorpusReadPort`
sits beside `KnowledgePort`: same reasoning, restated here because it is easy
to forget once the domain object in question is an aggregate with mutating
commands, not a bag of documents.

Same shape as `CorpusReadPort` in the ways that matter. The project is not a
parameter on either call, because an instance belongs to one project and
supplies it -- a caller that could pass a different project id is a caller
that could read another project's topics. And absence reads as `None`, not an
exception: a hand-edited URL naming an id that does not exist, or exists in
someone else's project, is the ordinary case for a browser, not a failure.

Unlike the corpus, a topic's need for attention is not a side fact a caller
might want -- it is the reason the page exists. `TopicView` carries the
`TopicSummary` and the `TopicAttention` computed for it together, so a caller
listing topics never has to make a second call per row to learn why one was
flagged. `TopicDetail` widens that to what a single topic's page needs:
the sub-questions with their answers, what has been linked and found, and
whether anything is still contested -- none of which the queue projection
carries, because none of it is needed to rank a queue.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from research_team.application.topic_attention import TopicAttention
from research_team.application.topics import TopicSummary


@dataclass(frozen=True)
class TopicView:
    """One topic as a list sees it, with why it wants attention.

    `attention` travels with `summary` rather than being a separate lookup,
    for the reason the module docstring gives: the list is ranked on
    attention, so the thing that ranks it has to be in the row.
    """

    summary: TopicSummary
    attention: TopicAttention

    @property
    def needs_attention(self) -> bool:
        return self.attention.needs_attention


@dataclass(frozen=True)
class SubQuestionView:
    """One sub-question, answered or not."""

    key: str
    question: str
    answer: str | None

    @property
    def resolved(self) -> bool:
        return self.answer is not None


@dataclass(frozen=True)
class TopicDetail:
    """One topic's own page: everything a summary row leaves out.

    `findings` and `source_ids` are what was learned and where it came from;
    `contested` is whether any of it is still in dispute. `view` carries the
    summary and attention a list row would show, so a detail page can render
    its own header from the same shape the list uses, rather than a second one
    that has to be kept in step with it.
    """

    view: TopicView
    rationale: str
    scope: str
    sub_questions: tuple[SubQuestionView, ...]
    source_ids: tuple[str, ...]
    findings: tuple[str, ...]
    contested: bool


class TopicReadPort(Protocol):
    """A project's topics, listed and read. Bound to one project at construction.

    Two methods, mirroring `CorpusReadPort`: a list for the queue view, one
    read for the page behind a single row. Both answer in application types
    computed on read -- attention is never stored, so what this returns is
    always current with the corpus and the log as of the call, not as of
    whenever some background job last looked.
    """

    async def list_topics(self) -> list[TopicView]:
        """Every topic this project tracks, live and closed alike.

        Closed topics are not filtered out: the page this backs shows the
        whole history of what the project has asked, not just what is still
        open.
        """
        ...

    async def read_topic(self, topic_id: UUID) -> TopicDetail | None:
        """One topic's detail, or `None` if this project has no such topic.

        `None` covers both an id nobody ever opened and an id that belongs to
        a different project -- a caller does not get to tell those apart,
        because telling them apart is exactly the information a project
        boundary exists to withhold.
        """
        ...
