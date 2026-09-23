# Minimal type stub: only the parts of pefile that scripts/check_bundle.py uses.

DIRECTORY_ENTRY: dict[str, int]

class ImportDescData:
    dll: bytes

class PE:
    DIRECTORY_ENTRY_IMPORT: list[ImportDescData]
    def __init__(self, name: str | None = None, fast_load: bool | None = None) -> None: ...
    def parse_data_directories(self, directories: list[int] | None = None) -> None: ...
    def close(self) -> None: ...
