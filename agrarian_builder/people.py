"""Public project information, kept separate from the course semantic model.

Missing affiliations, portraits and profile links remain absent until verified.
Anonymous entries reserve space without assigning identities or academic status.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Person:
    """A directory entry; portrait paths are relative to the static directory."""

    name: str | None = None
    role: str | None = None
    affiliation: str | None = None
    contribution: str | None = None
    portrait: str | None = None
    profile_url: str | None = None
    placeholder: bool = False

    @property
    def initials(self) -> str:
        """Derive decorative initials only when a public name exists."""
        return "".join(word[0] for word in self.name.split()) if self.name else ""


COORDINATORS = (
    Person(name="Deise Prina Dutra", role="Coordinator"),
    Person(name="Gustavo Leal Teixeira", role="Coordinator"),
    Person(name="Danilo Duarte Costa", role="Coordinator"),
)

RESEARCH_TEAM = tuple(Person(placeholder=True) for _ in range(6))

DATA_PLATFORM = Person(
    name="Jhonatan H. Lopes",
    role="Data curation and web development",
    contribution=(
        "Jhonatan cleans and organises research and corpus data, prepares and "
        "maintains structured project data, develops the website and maintains "
        "its public repository."
    ),
)
