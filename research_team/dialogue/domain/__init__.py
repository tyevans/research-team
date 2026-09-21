"""The dialogue bounded context.

Ask queries, Socratic conversations, and interaction events.
"""

from research_team.dialogue.domain.ask import (
    AskConversation,
    AskConversationCommand,
    AskConversationStarted,
    AskConversationState,
    AskTurnRecorded,
    Citation,
    RecordAskTurn,
    StartAskConversation,
)
from research_team.dialogue.domain.interaction import (
    AttentionLost,
    AttentionRegained,
    EntityOpened,
    ExtractionQueued,
    InteractionEvent,
    InteractionSummary,
    ProjectSwitched,
    ViewEntered,
    ViewExited,
    filter_by_project,
    filter_by_view,
    find_friction_signals,
    summarize_interactions,
)
from research_team.dialogue.domain.socratic import (
    ConcludeSocraticDialogue,
    ObserveSocraticProgress,
    RecordSocraticTurn,
    SocraticDialogue,
    SocraticDialogueConcluded,
    SocraticDialogueStarted,
    SocraticProgressObserved,
    SocraticTurnRecorded,
    StartSocraticDialogue,
)

__all__ = [
    "AskConversation",
    "AskConversationCommand",
    "AskConversationStarted",
    "AskConversationState",
    "AskTurnRecorded",
    "AttentionLost",
    "AttentionRegained",
    "Citation",
    "ConcludeSocraticDialogue",
    "EntityOpened",
    "ExtractionQueued",
    "InteractionEvent",
    "InteractionSummary",
    "ObserveSocraticProgress",
    "ProjectSwitched",
    "RecordAskTurn",
    "RecordSocraticTurn",
    "SocraticDialogue",
    "SocraticDialogueConcluded",
    "SocraticDialogueStarted",
    "SocraticProgressObserved",
    "SocraticTurnRecorded",
    "StartAskConversation",
    "StartSocraticDialogue",
    "ViewEntered",
    "ViewExited",
    "filter_by_project",
    "filter_by_view",
    "find_friction_signals",
    "summarize_interactions",
]
