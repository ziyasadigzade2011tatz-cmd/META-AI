import httpx

OLLAMA = "http://127.0.0.1:11434/api/chat"


async def ask_model(client, model, system, prompt, max_tokens):
    response = await client.post(
        OLLAMA,
        json={
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "options": {
                "num_ctx": 4096,
                "num_predict": max_tokens,
                "temperature": 0.2
            }
        }
    )
    response.raise_for_status()

    text = response.json()["message"].get("content", "").strip()

    if not text:
        raise RuntimeError(
            "Agent returned an empty response"
        )

    return text


async def run_team(task):
    task = task.strip()

    if not task or len(task) > 2000:
        return "Задача пуста или слишком длинная."

    print("META TEAM: Starting Planner", flush=True)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(300, connect=15)
    ) as client:

        plan = await ask_model(
            client,
            "qwen2.5:3b",
            (
                "Ты Planning Agent системы META. "
                "Составь конкретный технический план "
                "для задачи пользователя. "
                "Максимум 5 коротких шагов. "
                "Пиши по-русски. "
                "Не утверждай, что действия уже выполнены."
            ),
            task,
            350
        )

        print("META TEAM: Planner finished", flush=True)
        print("META TEAM: Starting Builder", flush=True)

        result = await ask_model(
            client,
            "qwen2.5-coder:7b",
            (
                "Ты Builder Agent системы META. "
                "Тебе передан план другого агента. "
                "Подготовь практическое решение задачи, "
                "включая код, если он необходим. "
                "Пиши объяснения по-русски. "
                "Не утверждай, что код был запущен. "
                "Не выполняй никаких операций с файлами."
            ),
            (
                "Исходная задача:\n"
                + task
                + "\n\nПлан Planning Agent:\n"
                + plan
                + "\n\nПодготовь результат по этому плану."
            ),
            1200
        )

        print("META TEAM: Builder finished", flush=True)

    return (
        "## План от Planning Agent\n\n"
        + plan
        + "\n\n## Результат от Builder Agent\n\n"
        + result
    )
