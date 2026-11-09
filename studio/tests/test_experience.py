import sys,tempfile,unittest,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.experience import Experience
from meta5.context import resolve
from meta5.task_brief import safe_development_query

class ExperienceTests(unittest.TestCase):
    def test_followup_edits_same_project_preserving_other_fields(self):
        from meta_studio.agent import Sessions
        root=Path(self.temp.name)
        actions=iter([{'action':'write','args':{'path':'data.json','content':'{"value":1,"keep":true}'}},
                      {'action':'check','args':{'complete':True}},
                      {'action':'read','args':{'path':'data.json'}},
                      {'action':'edit','args':{'path':'data.json','old':'"value":1','new':'"value":2'}},
                      {'action':'check','args':{'complete':True}}])
        sessions=Sessions(root/'projects',root/'sessions',client=lambda messages:json.dumps(next(actions)))
        first=sessions.start({'task':'Создай JSON файл'})
        def wait():
            deadline=time.monotonic()+5
            while sessions.active and time.monotonic()<deadline:time.sleep(.01)
        wait()
        second=sessions.start({'task':'Исправь значение, сохрани остальные поля','project':first['project']})
        wait();state=sessions.get(second['id'])
        self.assertEqual(state['status'],'review')
        sessions.apply(second['id'])
        self.assertEqual(json.loads((Path(state['root'])/'data.json').read_text('utf-8')),{'value':2,'keep':True})

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.exp=Experience(Path(self.temp.name)/'experience.sqlite')
    def test_project_correction_applies_only_when_relevant(self):
        self.exp.capture('Поправка: для экспорта используй формат CSV','exporter','a')
        self.assertTrue(self.exp.select('Добавь экспорт отчёта','exporter','b'))
        self.assertFalse(self.exp.select('Добавь экспорт отчёта','other','b'))
        self.assertFalse(self.exp.select('Измени оформление меню','exporter','b'))
    def test_task_scope_does_not_leak(self):
        self.exp.capture('Запомни: расчёты округляй после суммирования','.','a')
        self.assertTrue(self.exp.select('Измени расчёты','.','a'))
        self.assertFalse(self.exp.select('Измени расчёты','.','b'))
    def test_natural_forget_targets_last_relevant_rule(self):
        self.exp.capture('Поправка: библиотека должна поддерживать фильтрацию','p','a')
        self.exp.select('Добавь фильтрацию','p','a')
        self.exp.command('забудь это правило','p','a')
        self.assertFalse(self.exp.select('Добавь фильтрацию','p','a'))
    def test_verification_matches_project(self):
        from meta_studio.verification import plan
        self.assertIn('dotnet_build_tests',[r['kind'] for r in plan(['Program.cs'])])
        self.assertNotIn('interface_behavior',[r['kind'] for r in plan(['Program.cs'])])
        self.assertIn('cpp_build_tests',[r['kind'] for r in plan(['main.cpp'])])
        self.assertIn('python_tests',[r['kind'] for r in plan(['main.py','test_main.py'])])
    def test_example_not_learned(self):
        self.assertIsNone(self.exp.capture('Поправка: например используй шахматы','p','a'))
    def test_implicit_correction_is_candidate_until_user_confirms(self):
        ident=self.exp.capture('Нет, используй интервалы между встречами','calendar','a')
        self.assertIsNotNone(ident)
        self.assertFalse(self.exp.select('Измени интервалы встреч','calendar','b'))
        self.exp.command('/learn confirm '+str(ident))
        self.assertTrue(self.exp.select('Измени интервалы встреч','calendar','b'))
    def test_model_answer_remains_candidate_even_if_flag_confirmed(self):
        self.exp.add('Используй сортировку записей','p','a',source='model',confirmed=True)
        self.assertFalse(self.exp.select('Измени сортировку','p','a'))
    def test_forget_and_disable(self):
        ident=self.exp.add('Для музыки используй плейлисты','p',confirmed=True)
        self.exp.command('/learn off');self.assertFalse(self.exp.select('музыки плейлисты','p'))
        self.exp.command('/learn on');self.exp.command('/learn forget '+str(ident))
        self.assertFalse(self.exp.select('музыки плейлисты','p'))
    def test_edit_replaces_conflicting_rule(self):
        ident=self.exp.add('Для поездок используй километры','p',confirmed=True)
        self.exp.command('/learn edit '+str(ident)+' Для поездок используй мили')
        rows=self.exp.select('План поездок','p')
        self.assertEqual(len(rows),1);self.assertIn('мили',rows[0]['rule'])
    def test_no_secrets_or_code(self):
        for rule in ('пароль=not-for-storage','```print(1)```','class User { }'):
            with self.assertRaises(ValueError):self.exp.add(rule,'p',confirmed=True)
    def test_development_is_not_search(self):
        for text in ('Сейчас исправь приложение','Добавь поиск в программу','Что значит необычное слово?','А сделай меню удобнее'):
            self.assertFalse(resolve([{'role':'user','content':text}])['web_requested'],text)
        with self.assertRaises(ValueError):safe_development_query('Создай приложение для заметок','Создай приложение для заметок')
        self.assertEqual(safe_development_query('Python pathlib official documentation','Создай инструмент'),'Python pathlib official documentation')

if __name__=='__main__':unittest.main()
