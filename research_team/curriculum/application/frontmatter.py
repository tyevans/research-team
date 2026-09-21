"""The leading YAML block of a markdown file, separated from its prose.

Re-exports markdown frontmatter parsing and title extraction from the
shared platform layer.
"""

from research_team.platform.shared.frontmatter import (
    FRONTMATTER_FENCE as FRONTMATTER_FENCE,
)
from research_team.platform.shared.frontmatter import (
    extract_title as extract_title,
)
from research_team.platform.shared.frontmatter import (
    parse_frontmatter as parse_frontmatter,
)

__all__ = [
    "FRONTMATTER_FENCE",
    "extract_title",
    "parse_frontmatter",
]
