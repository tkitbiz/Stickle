# Types for the part of linkify-it-py (no type hints of its own) Stickle uses.
from typing import Any

class LinkifyIt:
    def __init__(
        self, schemas: dict[str, Any] | None = None, options: dict[str, bool] | None = None
    ) -> None: ...
