import base64
import httpx

VISION_MODEL = "qwen2.5vl:3b"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def parse_image(url):
    if not isinstance(url, str):
        raise ValueError("Image URL must be a string")

    if not url.startswith("data:image/"):
        raise ValueError(
            "Only uploaded base64 images are supported"
        )

    header, separator, encoded = url.partition(",")

    if not separator or ";base64" not in header:
        raise ValueError("Invalid image encoding")

    if len(encoded) > MAX_IMAGE_BYTES * 2:
        raise ValueError("Image is too large")

    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError("Invalid base64 image")

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds 10 MB")

    formats={'data:image/png;base64':raw.startswith(b'\x89PNG\r\n\x1a\n'),
             'data:image/jpeg;base64':raw.startswith(b'\xff\xd8\xff'),
             'data:image/webp;base64':raw.startswith(b'RIFF') and raw[8:12]==b'WEBP'}
    if not formats.get(header.casefold(),False):raise ValueError('Нужна настоящая фотография PNG, JPEG или WebP')

    return encoded


def has_images(messages):
    for message in messages:
        content = message.get("content", [])

        if isinstance(content, str):
            if content.startswith("data:image/"):
                return True
            continue

        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "image_url":
                    return True
                if part.get("type") == "image":
                    return True

    return False


def convert_messages(messages):
    converted = []

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        texts = []
        images = []

        if isinstance(content, str):
            if content.startswith("data:image/"):
                images.append(parse_image(content))
            else:
                texts.append(content)

        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue

                kind = part.get("type")

                if kind == "text":
                    texts.append(part.get("text", ""))

                elif kind == "image_url":
                    image_url = part.get("image_url", {})
                    url = (
                        image_url.get("url", "")
                        if isinstance(image_url, dict)
                        else image_url
                    )
                    images.append(parse_image(url))

                elif kind == "image":
                    images.append(parse_image(part.get("data", "")))

        message_out = {
            "role": role,
            "content": "\n".join(texts)
        }

        if images:
            message_out["images"] = images
            if not message_out["content"]:
                message_out["content"] = "Опиши изображение."

        converted.append(message_out)

    return converted


async def vision_reply(messages):
    converted = convert_messages(messages)

    converted.insert(0, {
        "role": "system",
        "content": (
            "Ты META, персональный ИИ-помощник. "
            "Анализируй приложенные изображения. "
            "Отвечай на языке пользователя. "
            "Если вопрос на русском, отвечай по-русски. "
            "Не выдумывай невидимые детали."
        )
    })

    async with httpx.AsyncClient(trust_env=False, timeout=300) as client:
        response = await client.post(
            OLLAMA_URL,
            json={
                "model": VISION_MODEL,
                "messages": converted,
                "stream": False,
                "options": {
                    "num_ctx": 4096,
                    "num_predict": 512,
                    "temperature": 0.2
                }
            }
        )

        response.raise_for_status()
        data = response.json()

    return data["message"].get("content", "")
