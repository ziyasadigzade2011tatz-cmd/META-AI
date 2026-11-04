def choose_performance(text, coding=False):
    text = text.lower()

    deep_keywords = [
        "подробно проанализируй",
        "глубокий анализ",
        "сравни все варианты",
        "разработай архитектуру",
        "создай полноценный проект",
        "сложная задача",
        "пошаговое исследование",
        "deep analysis",
        "complex project"
    ]

    medium_keywords = [
        "объясни подробно",
        "напиши программу",
        "реши задачу",
        "составь план",
        "проанализируй",
        "разработай",
        "напиши код",
        "исправь код",
        "write code"
    ]

    if any(word in text for word in deep_keywords):
        mode = "thinking"
    elif coding or any(word in text for word in medium_keywords):
        mode = "medium"
    else:
        mode = "fast"

    if coding:
        model = "qwen2.5-coder:7b"
    else:
        model = "qwen2.5:3b"

    settings = {
        "fast": {
            "num_ctx": 4096,
            "num_predict": 256,
            "temperature": 0.2
        },
        "medium": {
            "num_ctx": 4096,
            "num_predict": 1024,
            "temperature": 0.3
        },
        "thinking": {
            "num_ctx": 8192,
            "num_predict": 2048,
            "temperature": 0.3
        }
    }

    return {
        "mode": mode,
        "model": model,
        "options": settings[mode]
    }
