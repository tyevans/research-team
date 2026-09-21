"""Dialogue application layer: services, registries, and component projections."""

from research_team.dialogue.application.ask import (
    AskAnswer,
    AskConversationOpened,
    AskExecutor,
    AskInFlight,
    AskMessage,
    AskNote,
    AskReadModel,
    AskService,
    Citation,
    Conversation,
    ConversationRegistry,
    Role,
)
from research_team.dialogue.application.ask_components import (
    ASK_COMPONENT_TYPES,
    answer_document,
    extract_component_ids,
    extract_component_types,
)
from research_team.dialogue.application.ask_components import (
    extract_components as extract_ask_components,
)
from research_team.dialogue.application.ask_components import (
    extract_prose as extract_ask_prose,
)
from research_team.dialogue.application.ask_components import (
    has_components as has_ask_components,
)
from research_team.dialogue.application.ask_components import (
    has_gradeable_components as has_ask_gradeable_components,
)
from research_team.dialogue.application.ask_components import (
    validate_components as validate_ask_components,
)
from research_team.dialogue.application.component_projections import (
    extract_component_ids_from_doc,
    extract_component_types_from_doc,
    extract_components_from_doc,
    extract_prose_from_doc,
    has_components_in_doc,
    has_gradeable_components_in_doc,
    parse_and_project,
    validate_components_in_doc,
)
from research_team.dialogue.application.socratic import (
    DialogueConcluded,
    DialogueInFlight,
    DialogueMessage,
    DialogueReadModel,
    DialogueRegistry,
    LiveDialogue,
    SocraticDialogueOpened,
    SocraticDialogueService,
    SocraticExecutor,
    SocraticFraming,
    SocraticNote,
    SocraticObservation,
    SocraticPrompt,
    UnknownDialogue,
)
from research_team.dialogue.application.socratic_components import (
    SOCRATIC_COMPONENT_TYPES,
    dialogue_document,
)
from research_team.dialogue.application.socratic_components import (
    extract_component_ids as extract_socratic_component_ids,
)
from research_team.dialogue.application.socratic_components import (
    extract_component_types as extract_socratic_component_types,
)
from research_team.dialogue.application.socratic_components import (
    extract_components as extract_socratic_components,
)
from research_team.dialogue.application.socratic_components import (
    extract_prose as extract_socratic_prose,
)
from research_team.dialogue.application.socratic_components import (
    has_components as has_socratic_components,
)
from research_team.dialogue.application.socratic_components import (
    has_gradeable_components as has_socratic_gradeable_components,
)
from research_team.dialogue.application.socratic_components import (
    validate_components as validate_socratic_components,
)

__all__ = [
    "ASK_COMPONENT_TYPES",
    "SOCRATIC_COMPONENT_TYPES",
    "AskAnswer",
    "AskConversationOpened",
    "AskExecutor",
    "AskInFlight",
    "AskMessage",
    "AskNote",
    "AskReadModel",
    "AskService",
    "Citation",
    "Conversation",
    "ConversationRegistry",
    "DialogueConcluded",
    "DialogueInFlight",
    "DialogueMessage",
    "DialogueReadModel",
    "DialogueRegistry",
    "LiveDialogue",
    "Role",
    "SocraticDialogueOpened",
    "SocraticDialogueService",
    "SocraticExecutor",
    "SocraticFraming",
    "SocraticNote",
    "SocraticObservation",
    "SocraticPrompt",
    "UnknownDialogue",
    "answer_document",
    "dialogue_document",
    "extract_ask_components",
    "extract_ask_prose",
    "extract_component_ids",
    "extract_component_ids_from_doc",
    "extract_component_types",
    "extract_component_types_from_doc",
    "extract_components_from_doc",
    "extract_prose_from_doc",
    "extract_socratic_component_ids",
    "extract_socratic_component_types",
    "extract_socratic_components",
    "extract_socratic_prose",
    "has_ask_components",
    "has_ask_gradeable_components",
    "has_components_in_doc",
    "has_gradeable_components_in_doc",
    "has_socratic_components",
    "has_socratic_gradeable_components",
    "parse_and_project",
    "validate_ask_components",
    "validate_components_in_doc",
    "validate_socratic_components",
]
