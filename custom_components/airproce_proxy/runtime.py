"""Local state subscriptions, independent of cloud availability."""

from collections.abc import Callable

from .proxy import ProxyConfig, PurifierProxy


class Runtime:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.listeners: set[Callable[[], None]] = set()
        self.proxy = PurifierProxy(
            ProxyConfig(
                listen_host=data["listen_host"],
                listen_port=data["listen_port"],
                allowed_peer=data["allowed_peer"],
            ),
            self.changed,
        )

    def changed(self) -> None:
        for listener in tuple(self.listeners):
            listener()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)
