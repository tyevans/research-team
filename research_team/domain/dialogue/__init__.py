"""The dialogue bounded context.

Ask queries, Socratic conversations, and interaction events.
"""

from research_team.domain.dialogue.ask import (
    AskConversation,
    AskConversationCommand,
    AskConversationStarted,
    AskConversationState,
    AskTurnRecorded,
    Citation,
    RecordAskTurn,
    StartAskConversation,
)
from research_team.domain.dialogue.interaction import (
    AttentionLost,
    AttentionRegained,
    EntityOpened,
    ExtractionQueued,
    InteractionEvent,
    ProjectSwitched,
    ViewEntered,
    ViewExited,
)
from research_team.domain.dialogue.socratic import (
    ConcludeSocraticDialogue,
    ObserveSocraticProgress,
    RecordSocraticTurn,
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
    "ObserveSocraticProgress",
    "ProjectSwitched",
    "RecordAskTurn",
    "RecordSocraticTurn",
    "SocraticDialogueConcluded",
    "SocraticDialogueStarted",
    "SocraticProgressObserved",
    "SocraticTurnRecorded",
    "StartAskConversation",
    "StartSocraticDialogue",
    "ViewEntered",
    "ViewExited",
]
