"""Extract plain text from project-generated inline HTML fragments.

Renderer controls and structural fingerprints need plain text where the model
stores inline HTML from ``markdown-it``. This module strips generated tags and
decodes HTML entities; it does not parse arbitrary HTML, sanitise untrusted
input or interpret Markdown syntax.
"""

import html
import re


def plain_text(value: str) -> str:
    """Extract label text from project-generated HTML fragments.

    Parameters
    ----------
    value
        Inline HTML fragment produced by the parser from authored Markdown.

    Returns
    -------
    str
        Plain text with tags removed and HTML entities decoded.

    Notes
    -----
    Semantic option and prompt text can contain inline HTML, whereas native
    select options, accessible labels and structural fingerprints need plain
    text. Tag removal followed by entity decoding is sufficient for those
    generated fragments; this is not a general-purpose HTML parser or a
    sanitiser for arbitrary input.
    """
    return html.unescape(re.sub(r"<[^>]*>", "", value))
