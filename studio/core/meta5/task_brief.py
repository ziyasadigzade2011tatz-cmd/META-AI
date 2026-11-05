"""Separate deliverable, reference and tool directives without inventing branding."""
import re

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
            'product_name':title[1] if title else None,'web_requested':explicit_web,'web_forbidden':blocked,
            'website':website,'ambiguous_reference':ambiguous,
            'acceptance':['Соответствие задаче, а не перенос имени референса','Служебные команды не являются текстом интерфейса','Связанные локальные файлы и честный отчёт о проверках']}

def reference_query(brief):
    target=' '.join(brief['reference_targets'])
    if target:return (target+' interface layout documentation' if brief['website'] else target+' official documentation')[:280]
    return brief['goal'][:280]
