import ast
import re

from agent_pending import stage


def maybe_stage(task, team_response):
    """
    Create a pending proposal only after an explicit request.
    Never write the project file automatically.
    """

    intent = re.search(
        r"(?:создай|подготовь)\s+файл\s+"
        r"([A-Za-z0-9_./\\-]+\.py)\b",
        task,
        flags=re.IGNORECASE,
    )

    if not intent:
        return ""

    filename = intent.group(1)

    # Take code only from the Coder section.
    section = re.search(
        r"### Результат Coder\s*\n(.*?)"
        r"(?=\n### Проверка|\Z)",
        team_response,
        flags=re.DOTALL,
    )

    if not section:
        return (
            "\n\n### Файловая заявка\n"
            "Не создана: ответ Coder не найден."
        )

    blocks = re.findall(
        r"```(?:python|py)\s*\n(.*?)```",
        section.group(1),
        flags=re.DOTALL | re.IGNORECASE,
    )

    if len(blocks) != 1:
        return (
            "\n\n### Файловая заявка\n"
            "Не создана: нужен один полный блок Python."
        )

    code = blocks[0].strip() + "\n"

    try:
        ast.parse(code)
    except SyntaxError as error:
        return (
            "\n\n### Файловая заявка\n"
            f"Не создана: ошибка Python в строке "
            f"{error.lineno}: {error.msg}"
        )

    try:
        proposal = stage(filename, code)
    except (OSError, ValueError, UnicodeError) as error:
        return (
            "\n\n### Файловая заявка\n"
            f"Не создана: {type(error).__name__}: {error}"
        )

    return (
        "\n\n### Файловая заявка\n"
        f"**Файл:** `{filename}`\n\n"
        f"**ID заявки:** `{proposal['id']}`\n\n"
        "**Статус:** ожидает подтверждения.\n\n"
        "Код прошёл синтаксическую проверку, "
        "но ещё не выполнялся. "
        "Файл проекта не изменён."
    )


# META_PROJECT_ENGINE_37
# Preserve original behavior for one-file requests.
_meta36_maybe_stage = maybe_stage

def maybe_stage(task, team_response):
    from agent_project37 import maybe_stage_project
    return maybe_stage_project(task, team_response, _meta36_maybe_stage)


# META_ENGINE_38: audit -> bounded local repair -> approval proposal.
_meta37_maybe_stage = maybe_stage

def maybe_stage(task, team_response):
    from meta_engine38 import process
    return process(task, team_response, _meta37_maybe_stage)
