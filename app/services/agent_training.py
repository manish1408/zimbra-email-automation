from __future__ import annotations

from app.db.email_repository import EmailRepository

GENERAL_TRAINING_HEADER = "\n\n--- General rules ---\n"
DRAFT_REPLY_TRAINING_HEADER = "\n\n--- Draft reply rules ---\n"


def augment_system_prompt(base: str, training: str | None, *, header: str = GENERAL_TRAINING_HEADER) -> str:
    text = (training or "").strip()
    if not text:
        return base
    return f"{base}{header}{text}"


async def load_general_rules(repository: EmailRepository) -> str:
    row = await repository.get_agent_training()
    return (row.get("general_rules") or "").strip()


async def load_draft_reply_rules(repository: EmailRepository) -> str:
    row = await repository.get_agent_training()
    return (row.get("draft_reply_rules") or "").strip()


async def load_training_texts(repository: EmailRepository) -> tuple[str, str]:
    row = await repository.get_agent_training()
    return (
        (row.get("general_rules") or "").strip(),
        (row.get("draft_reply_rules") or "").strip(),
    )
