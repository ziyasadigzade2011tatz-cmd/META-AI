tasks = []

def add_task(title):
    tasks.append({'title': title, 'completed': False})
    print(f"Задача '{title}' добавлена.")

def remove_task(title):
    global tasks
    tasks = [task for task in tasks if task['title'] != title]
    print(f"Задача '{title}' удалена.")

def complete_task(title):
    global tasks
    for task in tasks:
        if task['title'] == title:
            task['completed'] = True
            print(f"Задача '{title}' завершена.")
            return
    print(f"Задача '{title}' не найдена.")

def get_tasks():
    return tasks
