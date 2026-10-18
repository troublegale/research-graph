"""research_graph — каркас учебного проекта research-graph."""

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION_NAME = "research-graph"


def get_version() -> str:
    """Возвращает версию установленного дистрибутива."""
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:  # pragma: no cover - пакет не установлен
        return "0.0.0+unknown"


__version__ = get_version()

__all__ = ["DISTRIBUTION_NAME", "__version__", "get_version"]
