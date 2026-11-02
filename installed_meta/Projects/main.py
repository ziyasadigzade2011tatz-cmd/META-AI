import tasks
import storage

def main():
    while True:
        print("\nМенеджер задач")
        print("1. Добавить задачу")
        print("2. Удалить задачу")
        print("3. Завершить задачу")
        print("4. Выйти")
        
        choice = input("Выберите действие: ")
        
        if choice == '1':
            title = input("Введите название задачи: ")
            tasks.add_task(title)
        elif choice == '2':
            title = input("Введите название задачи для удаления: ")
            tasks.remove_task(title)
        elif choice == '3':
            title = input("Введите название задачи для завершения: ")
            tasks.complete_task(title)
        elif choice == '4':
            storage.save_tasks(tasks.get_tasks())
            print("Задачи сохранены. До свидания!")
            break
        else:
            print("Неверный выбор. Попробуйте снова.")

if __name__ == "__main__":
    main()
