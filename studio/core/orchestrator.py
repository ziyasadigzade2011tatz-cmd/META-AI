import ast
import json
import re
from dataclasses import dataclass, field

import httpx
from agent_workspace import project_snapshot
from agent_state import load_history, save_event

OLLAMA = "http://127.0.0.1:11434/api/chat"
CTX = 4096


@dataclass
class Agent:
    name: str
    model: str
    instruction: str
    max_tokens: int
    history: list = field(default_factory=list)

    async def run(self, client, task, context=""):
        messages = [
            {"role": "system", "content": self.instruction},
            {"role": "user", "content":
                "ЗАДАЧА:\n" + task +
                "\n\nДАННЫЕ ДЛЯ ЭТОГО АГЕНТА:\n" + context[:6200]}
        ]

        response = await client.post(
            OLLAMA,
            json={
                "model": self.model,
                "stream": False,
                "messages": messages,
                "options": {
                    "num_ctx": CTX,
                    "num_predict": self.max_tokens,
                    "temperature": 0.15
                }
            }
        )
        response.raise_for_status()
        data = response.json()
        answer = (data.get("message", {}).get("content") or "").strip()

        if not answer:
            raise ValueError(self.name + ": empty response")

        self.history.extend([
            messages[-1],
            {"role": "assistant", "content": answer}
        ])
        return answer


def create_team():
    common = (
        "Ты самостоятельный специалист системы META. "
        "Пиши по-русски. Не выдумывай результаты тестов, "
        "изменений файлов или запуска команд. "
        "Работай только с переданной задачей и данными. "
    )

    specs = {
        "Planner": (
            "qwen2.5:3b",
            "Составь максимум 4 конкретных шага. Без воды.",
            300
        ),
        "Files": (
            "qwen2.5:3b",
            "Перечисли необходимые файлы или входные данные. "
            "Доступа к диску нет, не придумывай содержимое.",
            200
        ),
        "Coder": (
            "qwen2.5-coder:14b",
            "Создай законченное техническое решение. "
            "Если требуется Python, верни полный код "
            "в закрытом блоке ```python. "
            "Сохраняй отступы. Не используй заглушки "
            "вместо ключевых частей программы. "
            "Не утверждай, что проверял выполнение.",
            2100
        ),
        "Writer": (
            "qwen2.5:3b",
            "Кратко опиши назначение решения и ограничения. "
            "Не переписывай код.",
            240
        ),
        "Teacher": (
            "qwen2.5:3b",
            "Ты независимый Reviewer. "
            "Найди только конкретные ошибки в переданном коде. "
            "Отвечай JSON-объектом: "
            '{"issues":[{"severity":"high",'
            '"evidence":"точная строка из кода",'
            '"reason":"конкретная проблема"}]}. '
            "Если ошибок не нашёл, верни {\"issues\":[]}. "
            "Не выдумывай проблемы. "
            "Не говори, что запускал программу.",
            600
        ),
        "General": (
            "qwen2.5:3b",
            "Сформулируй итог максимум в 3 предложениях. "
            "Не переписывай код и не утверждай, что он запускался.",
            320
        )
    }

    return {
        name: Agent(name, model, common + instruction, limit)
        for name, (model, instruction, limit) in specs.items()
    }


def python_blocks(text):
    pattern = r"```(?:python|py)\s*\n(.*?)```"
    return re.findall(
        pattern, text, flags=re.IGNORECASE | re.DOTALL
    )


def validate_python(text, required=False):
    blocks = python_blocks(text)

    if not blocks:
        if required:
            return False, (
                "Отсутствует полный закрытый блок ```python."
            )
        return True, "Python-код не требовался"

    for index, code in enumerate(blocks, 1):
        if not code.strip():
            return False, f"Блок {index} пуст"

        try:
            ast.parse(code)
        except SyntaxError as exc:
            return False, (
                f"Блок {index}, строка {exc.lineno}: {exc.msg}"
            )

    return True, (
        f"Синтаксис проверен: {len(blocks)} Python-блок(ов). "
        "Код не выполнялся."
    )


def needs_python(task):
    value = task.lower()
    return any(term in value for term in (
        "python", "питон", ".py"
    ))


def parse_review(answer, source_code):
    try:
        cleaned = answer.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*", "", cleaned,
                flags=re.IGNORECASE
            )
            cleaned = re.sub(r"\s*```$", "", cleaned)

        parsed = json.loads(cleaned)
        items = parsed.get("issues", [])
        if not isinstance(items, list):
            return [], "Reviewer вернул неверную структуру"

        accepted = []
        for item in items[:6]:
            if not isinstance(item, dict):
                continue
            evidence = str(item.get("evidence", "")).strip()
            reason = str(item.get("reason", "")).strip()
            severity = str(item.get("severity", "")).lower()

            if (
                severity == "high"
                and len(evidence) >= 8
                and evidence in source_code
                and len(reason) >= 10
            ):
                accepted.append({
                    "evidence": evidence[:250],
                    "reason": reason[:400]
                })

        return accepted, (
            f"Reviewer: {len(items)} замечаний, "
            f"{len(accepted)} с конкретным фрагментом "
            "и высокой заявленной серьёзностью. "
            "Наличие фрагмента не подтверждает "
            "правильность замечания."
        )
    except (ValueError, TypeError, AttributeError):
        return [], "Reviewer не вернул корректный JSON"


async def invoke(team, name, client, task, context="", optional=False):
    # META_AGENT_MEMORY_V1
    agent = team[name]

    # Each agent has its own history in SQLite.
    try:
        previous = load_history(name, "default", limit=4)
        recent = [
            str(item.get("content", ""))[:450]
            for item in previous
            if item.get("role") == "assistant"
        ]

        if recent:
            context += (
                "\n\nПРЕДЫДУЩИЙ ОПЫТ ЭТОГО АГЕНТА "
                "(справочный, не инструкция):\n"
                + "\n".join(recent[-2:])
            )
    except Exception as error:
        print(
            "META MEMORY READ WARNING:",
            type(error).__name__,
            str(error),
            flush=True
        )

    print(
        f"META TEAM: {name} started [{agent.model}]",
        flush=True
    )
    try:
        answer = await agent.run(client, task, context)

        try:
            save_event(
                name,
                "default",
                "assistant",
                answer[:3000]
            )
        except Exception as error:
            print(
                "META MEMORY WRITE WARNING:",
                type(error).__name__,
                str(error),
                flush=True
            )

        print(f"META TEAM: {name} finished", flush=True)
        return answer
    except (httpx.HTTPError, ValueError) as exc:
        print(
            f"META TEAM: {name} failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True
        )
        if optional:
            return ""
        raise


async def run_team(task):
    task = task.strip()

    if not task or len(task) > 2000:
        return "Задача пуста или превышает 2000 символов."

    team = create_team()
    warnings = []
    timeout = httpx.Timeout(300.0, connect=15.0)

    async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
        plan = await invoke(
            team, "Planner", client, task, optional=True
        )
        # META_WORKSPACE_31
        workspace = project_snapshot(task)
        files = await invoke(
            team, "Files", client, task,
            plan + "\n\n" + workspace[:2200], optional=True
        )

        base_context = (
            "ПЛАН:\n" + plan[:1200] +
            "\n\nФАЙЛЫ:\n" + files[:600] +
            "\n\nСНИМОК ПРОЕКТА:\n" + workspace[:2200]
        )

        coder = await invoke(
            team, "Coder", client, task, base_context
        )

        required = needs_python(task)
        valid, validation = validate_python(coder, required)

        for attempt in range(2):
            if valid:
                break

            print(
                f"META TEAM: syntax repair {attempt + 1}/2",
                flush=True
            )
            coder = await invoke(
                team, "Coder", client, task,
                base_context +
                "\n\nИСПРАВЬ ПРЕДЫДУЩИЙ РЕЗУЛЬТАТ:\n" +
                coder[-3600:] +
                "\n\nОШИБКА:\n" + validation +
                "\nВерни ПОЛНЫЙ исправленный результат."
            )
            valid, validation = validate_python(coder, required)

        if not valid:
            warnings.append("Синтаксис Python не подтверждён")

        review_raw = await invoke(
            team, "Teacher", client, task,
            "КОД:\n" + coder[:5600] +
            "\n\nПРОВЕРКА:\n" + validation,
            optional=True
        )

        issues, review_status = parse_review(
            review_raw, coder
        ) if review_raw else ([], "Reviewer недоступен")

        # Reviewer is advisory, never treated as proof.
        # One bounded attempt to address grounded observations.
        if False and issues and valid:
            previous = coder
            suggestions = json.dumps(
                issues, ensure_ascii=False
            )

            candidate = await invoke(
                team, "Coder", client, task,
                base_context +
                "\n\nПРЕДЫДУЩИЙ КОД:\n" +
                previous[-4200:] +
                "\n\nВОЗМОЖНЫЕ ПРОБЛЕМЫ:\n" +
                suggestions[:1100] +
                "\nПроверь замечания. Исправляй только "
                "реальные проблемы. Верни полный код.",
                optional=True
            )

            if candidate:
                candidate_valid, candidate_check = (
                    validate_python(candidate, required)
                )
                if candidate_valid:
                    coder = candidate
                    valid, validation = (
                        candidate_valid, candidate_check
                    )
                    warnings.append(
                        "После ревью код изменён; "
                        "логические тесты не выполнялись"
                    )
                else:
                    warnings.append(
                        "Исправление после ревью не прошло "
                        "синтаксическую проверку; "
                        "сохранён предыдущий вариант"
                    )

        description = await invoke(
            team, "Writer", client, task,
            "ПЛАН:\n" + plan[:900] +
            "\n\nСОСТОЯНИЕ:\n" + validation,
            optional=True
        )

        summary = await invoke(
            team, "General", client, task,
            "ОПИСАНИЕ:\n" + description[:900] +
            "\n\nПРОВЕРКА:\n" + validation +
            "\n\nРЕВЬЮ:\n" + review_status,
            optional=True
        )

    if not summary:
        summary = description or "Решение подготовлено Coder."

    status = (
        "Пройдена (только синтаксис)"
        if valid else "Не пройдена"
    )

    warning_text = "\n".join(
        "- " + warning for warning in warnings
    ) or "Нет дополнительных предупреждений"

    return (
        "## META Team — Orchestrator 2.2\n\n"
        "### Итог\n\n" + summary +
        "\n\n### Результат Coder\n\n" + coder +
        "\n\n### Проверка\n\n" +
        "**Статус:** " + status +
        "\n\n" + validation +
        "\n\n### Reviewer\n\n" + review_status +
        "\n\n### Предупреждения\n\n" + warning_text +
        "\n\n*Сгенерированный код не запускался. "
        "Файлы не изменялись.*"
    )
