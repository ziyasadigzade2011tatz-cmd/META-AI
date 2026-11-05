"""Conservative local storage/network filter; explanations of a keyword are allowed."""
import re

PATTERN=re.compile(r'github_pat_[\w]+|gh[pousr]_[\w]+|sk-[\w-]{12,}|AIza[\w-]{20,}|\beyJ[\w-]+\.[\w-]+\.[\w-]+\b|(?:password|пароль|api[ _-]?key|токен|token)\s*[:=]\s*\S+|\b(?:мой пароль|моя карта|номер карты|cvv|паспорт|снилс)\b|[\w.+-]+@[\w.-]+\.[a-zа-я]{2,}|[A-Za-z]:[\\/]|\b(?:улица|ул\.|проспект|переулок|квартира|адрес проживания)\s+\S+|\b(?:\d[ -]?){10,19}\b',re.I)

def sensitive(text):
    value=str(text)
    if PATTERN.search(value):return True
    return bool(re.search(r'\b(?:пароль|password|секретный ключ)\s+\S+',value,re.I))
def redact(text):return '***' if sensitive(text) else str(text)
