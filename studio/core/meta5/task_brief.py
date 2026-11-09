"""Separate deliverable, reference and tool directives without inventing branding."""
import re

def development_request(text):
    return bool(re.search(r'\b(?:создай|сделай|напиши|измени|исправь|добавь|доработай|переделай|create|build|implement|fix|refactor)\b',text,re.I))

WEB=re.compile(r'\bweb[\s_-]*(?:search(?:ing)?|research)\b|веб[ -]?(?:поиск|с[её]рфинг)|(?:поищи|посмотри|найди).{0,35}(?:интернет|сети)|(?:search|browse)\s+(?:the\s+)?(?:web|internet)',re.I)
NEGATIVE_WEB=re.compile(r'без\s+(?:интернета|(?:веб[ -]?|web[ -]?)?(?:поиск\w*|с[её]рфинг\w*))|не\s+(?:ищи|используй\s+(?:интернет|веб[ -]?поиск\w*))|no\s+web|offline',re.I)
REFERENCE=re.compile(r'(?:по подобию|по образцу|в стиле|похож\w* на|как у|inspired by|similar to)\s+[«"“]?([^\n,;()»"”]{2,90})',re.I)
TITLE=re.compile(r'(?:назови(?:\s+(?:сайт|проект|его))?|название(?:\s+(?:сайта|проекта))?\s*[:—-]?|named|call it)\s*[«"“]([^\n»"”]{1,70})[»"”]',re.I)

POLICY='''Разделяй цель, референс, название продукта и команды инструментов.
Референс означает изучить подходящие свойства (структура, поведение, типографика,
отступы, палитра), а не автоматически копировать бренд или текст на страницу.
Команды веб-поиска и служебные пометки НЕ являются содержимым продукта.
Название не задано явно — используй нейтральное рабочее название, не имя референса.
Сначала изучи доступные источники, затем составь план под цель и подготовь связанный код.
Текстовые источники не доказывают визуальное сходство: не утверждай, что видел скриншот,
если его не получал. При недостаточном референсе уточни один конкретный вопрос.
Сверь результат с целью и перечисли фактически выполненные проверки.'''

def build(task):
    feature_web=bool(re.search(r'\bс\s+(?:(?:функцией|поддержкой)\s+)?(?:веб[ -]?поиск|web[ -]?search)',task,re.I))
    marker_web=any(WEB.search(m[1]) for m in re.finditer(r'\(([^()]*)\)',task))
    clean=re.sub(r'\(([^()]*)\)',lambda m:'' if WEB.search(m[1]) and len(m[1])<80 else m[0],task)
    if not feature_web:clean=WEB.sub('',clean)
    clean=re.sub(r'\s+',' ',clean).strip(' ,;')
    references=[]
    for match in REFERENCE.finditer(clean):
        name=re.split(r'\s+(?:но|только|назови|название|with|but)\b',match[1],maxsplit=1,flags=re.I)[0].strip(' .:—-')
        if name and name not in references:references.append(name)
    title=TITLE.search(clean)
    blocked=bool(NEGATIVE_WEB.search(task));explicit_web=(marker_web or bool(WEB.search(task)) and not feature_web) and not blocked
    website=bool(re.search(r'сайт|лендинг|страниц|website|landing|webpage',clean,re.I))
    ambiguous=any(r.casefold() in ('этого','него','неё','нее','это','такого','того','that','this') for r in references)
    return {'goal':clean,'original_task':task,'reference_targets':references[:3],
            'kind':'correction' if re.search(r'\b(?:нет[, ]|вместо|не так|я имел в виду|исправь)',clean,re.I) else 'development' if development_request(clean) else 'question',
            'constraints':[s.strip() for s in re.split(r'[\n;]',clean) if re.search(r'\b(?:не |без |только |нельзя|must|without)',s,re.I)][:8],
            'examples_are_not_rules':bool(re.search(r'например|как пример|for example',clean,re.I)),
            'product_name':title[1] if title else None,'web_requested':explicit_web,'web_forbidden':blocked,
            'website':website,'ambiguous_reference':ambiguous,
            'acceptance':[s.strip(' -*')[:300] for s in clean.splitlines() if re.search(r'должен|должна|обязательно|must|required',s,re.I)][:8]+['Соответствие задаче, а не перенос имени референса','Служебные команды не являются текстом интерфейса','Связанные локальные файлы и честный отчёт о проверках']}

def reference_query(brief):
    target=' '.join(brief['reference_targets'])
    if target:return (target+' interface layout documentation' if brief['website'] else target+' official documentation')[:280]
    urls=re.findall(r'https?://[^\s<>"()]+',brief.get('original_task',''))
    if urls:return urls[0][:280]
    # A development specification is not a public-web query. No inferred brand.
    if brief.get('website'):return 'HTML CSS JavaScript responsive layout official documentation MDN'
    return ''

def safe_development_query(query,task):
    """Reject copied specs and private payloads before any network access."""
    from .privacy import sensitive
    query=str(query).strip()
    if sensitive(query):raise ValueError('Личные данные не отправляются в поиск')
    if len(query)>280 or '\n' in query or re.search(r'<(?:html|script)|```|[{};]',query,re.I):
        raise ValueError('Для поиска нужен короткий запрос по документации, не код или задание')
    if re.match(r'^(?:создай|сделай|напиши|измени|исправь|добавь|create|build|implement|fix|refactor)\b',query,re.I) or (len(task)>60 and query.casefold()==task.strip().casefold()):
        raise ValueError('Задание разработки не отправляется целиком в поиск; укажи технологию, версию или ошибку')
    return query
