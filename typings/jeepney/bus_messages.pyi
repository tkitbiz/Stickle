from jeepney import Message

class MatchRule:
    def __init__(
        self,
        *,
        type: str | None = None,
        sender: str | None = None,
        interface: str | None = None,
        member: str | None = None,
        path: str | None = None,
        path_namespace: str | None = None,
        destination: str | None = None,
        eavesdrop: bool = False,
    ) -> None: ...

class DBus:
    def AddMatch(self, rule: MatchRule | str) -> Message: ...  # noqa: N802

message_bus: DBus
