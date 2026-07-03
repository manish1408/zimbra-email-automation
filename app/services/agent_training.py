from __future__ import annotations

from app.db.email_repository import EmailRepository

TRAINING_HEADER = "\n\n--- Organization training (apply globally) ---\n"


def augment_system_prompt(base: str, training: str | None) -> str:
    text = (training or "").strip()
    if not text:
        return base
    return f"{base}{TRAINING_HEADER}{text}"


async def load_training(repository: EmailRepository) -> str:
    row = await repository.get_agent_training()
    return (row.get("content") or "").strip()
