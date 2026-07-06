from .sqlite import Store

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


class _StoreProxy:
    def __getattr__(self, name):
        return getattr(get_store(), name)


store = _StoreProxy()