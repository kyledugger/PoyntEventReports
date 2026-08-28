import logging
import os


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s %(levelname)s "
            "%(name)s: %(message)s"
        ),
        force=True,
    )

    logging.getLogger(__name__).info(
        "Application logging configured at %s level.",
        level_name,
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)    