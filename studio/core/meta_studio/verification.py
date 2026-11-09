"""Project-appropriate verification inventory; never executes commands."""
import shutil

def plan(files):
    names={str(p).lower() for p in files};result=[]
    def add(kind,tool,reason):
        result.append({'kind':kind,'status':'not_run' if shutil.which(tool) else 'requires_tool',
                       'tool':tool,'reason':reason,'execution_requires_permission':True})
    if any(p.endswith('.py') for p in names):
        result.append({'kind':'python_tests','status':'not_run' if any('test' in p for p in names) else 'tests_not_found',
                       'tool':'Python unittest','reason':'Запуск тестов отдельно от синтаксиса','execution_requires_permission':True})
    if any(p.endswith(('.js','.mjs','.cjs','.ts','.tsx')) for p in names):
        add('javascript_tests','node','Существующие тесты проекта; установка зависимостей не выполнялась')
    if any(p.endswith(('.ts','.tsx')) for p in names):add('typescript','tsc','Проверка типов, не только JavaScript-синтаксиса')
    if any(p.endswith(('.cs','.csproj')) for p in names):add('dotnet_build_tests','dotnet','Сборка и тесты C# требуют .NET SDK и разрешения')
    if any(p.endswith(('.cpp','.cc','.c','.h','.hpp')) for p in names):add('cpp_build_tests','cmake','Сборка и тесты требуют подходящего toolchain проекта')
    if any(p.endswith('.html') for p in names):
        result.append({'kind':'interface_behavior','status':'not_run','tool':'browser','reason':'Визуальное поведение и кнопки не проверены синтаксисом','execution_requires_permission':True})
    if not result:result.append({'kind':'project_behavior','status':'not_run','reason':'Нужна проверка поведения по требованиям задачи'})
    return result
