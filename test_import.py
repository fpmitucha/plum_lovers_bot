#!/usr/bin/env python3
"""Проверка импорта модулей без ошибок"""
import sys
sys.path.insert(0, 'src')

try:
    from bot.handlers import admin
    print('✓ admin.py импортируется без ошибок')
except Exception as e:
    print(f'✗ Ошибка при импорте admin.py: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    from bot.handlers import help
    print('✓ help.py импортируется без ошибок')
except Exception as e:
    print(f'✗ Ошибка при импорте help.py: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    from bot.main import main
    print('✓ main.py импортируется без ошибок')
except Exception as e:
    print(f'✗ Ошибка при импорте main.py: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)

print('\n✓ Все модули импортируются успешно!')

