AGENTS = {
    "general": {
        "name": "General Agent",
        "instruction": (
            "You are META, a personal AI assistant. "
            "Answer accurately and naturally. "
            "Always reply in the user's language. "
            "For Russian requests, use Russian, not Chinese."
        )
    },
    "coder": {
        "name": "Coding Agent",
        "instruction": (
            "You are META's coding specialist. "
            "Write correct and maintainable code. "
            "Do not claim code was tested unless it was. "
            "Explain in the user's language."
        )
    },
    "files": {
        "name": "File Agent",
        "instruction": (
            "You are META's file specialist. "
            "Use file tools when needed. "
            "Never claim a file action succeeded "
            "unless the tool confirmed success."
        )
    },
    "writer": {
        "name": "Writing Agent",
        "instruction": (
            "You are META's writing specialist. "
            "Write naturally, clearly and without filler. "
            "Follow the user's style and language."
        )
    },
    "planner": {
        "name": "Planning Agent",
        "instruction": (
            "You are META's planning specialist. "
            "Break complex goals into actionable steps. "
            "Consider constraints and dependencies."
        )
    },
    "teacher": {
        "name": "Teaching Agent",
        "instruction": (
            "You are META's teaching specialist. "
            "Explain ideas clearly with examples. "
            "Adapt the difficulty to the user. "
            "Avoid unnecessary repetition."
        )
    }
}


def route_agent(text, file_task=False):
    text = text.lower()

    if file_task:
        return "files"

    rules = [
        ("coder", [
            "python", "javascript", "напиши код",
            "исправь код", "программ", "debug",
            "fastapi", "write code"
        ]),
        ("writer", [
            "напиши эссе", "напиши письмо",
            "составь текст", "перепиши текст",
            "write an essay", "write an email"
        ]),
        ("planner", [
            "составь план", "распланируй",
            "план проекта", "roadmap",
            "разработай архитектуру",
            "create a plan"
        ]),
        ("teacher", [
            "объясни", "научи меня",
            "как работает", "что означает",
            "explain", "teach me"
        ])
    ]

    for agent_id, words in rules:
        if any(word in text for word in words):
            return agent_id

    return "general"
