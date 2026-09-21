"""Application services, ports, and coordinators for the research bounded context."""

from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.corpus_read import (
    CorpusReadPort,
    SourceListing,
    StoredDocument,
)
from research_team.research.application.corpus_spans import Span
from research_team.research.application.document_extraction import DocumentExtractor
from research_team.research.application.findings import Finding, FindingSeverity
from research_team.research.application.media_acquisition import (
    MediaAcceptReconciler,
    MediaAcceptWorker,
)
from research_team.research.application.media_curation import (
    MediaCurationService,
    SearchResult,
)
from research_team.research.application.perception import (
    MediaPerceiver,
    PerceptionCapabilities,
)
from research_team.research.application.research_round import TopicRoundRunner
from research_team.research.application.research_run import (
    ResearchRunDriver,
    RoundOutcome,
    RunReport,
)
from research_team.research.application.research_supervisor import ResearchSupervisor
from research_team.research.application.topic_attention import (
    CorpusFacts,
    TopicAttention,
    attention_for,
)
from research_team.research.application.topic_dispatch import (
    DispatchAction,
    TopicDispatcher,
)
from research_team.research.application.topic_read import (
    SubQuestionView,
    TopicDetail,
    TopicReadPort,
    TopicView,
)
from research_team.research.application.topic_seeding import TopicSeeder
from research_team.research.application.topics import (
    TopicError,
    TopicPort,
    TopicService,
    TopicSummary,
)

__all__ = [
    "CorpusEditor",
    "CorpusFacts",
    "CorpusReadPort",
    "DispatchAction",
    "DocumentExtractor",
    "Finding",
    "FindingSeverity",
    "MediaAcceptReconciler",
    "MediaAcceptWorker",
    "MediaCurationService",
    "MediaPerceiver",
    "PerceptionCapabilities",
    "ResearchRunDriver",
    "ResearchSupervisor",
    "RoundOutcome",
    "RunReport",
    "SearchResult",
    "SourceListing",
    "Span",
    "StoredDocument",
    "SubQuestionView",
    "TopicAttention",
    "TopicDetail",
    "TopicDispatcher",
    "TopicError",
    "TopicPort",
    "TopicReadPort",
    "TopicRoundRunner",
    "TopicSeeder",
    "TopicService",
    "TopicSummary",
    "TopicView",
    "attention_for",
]
