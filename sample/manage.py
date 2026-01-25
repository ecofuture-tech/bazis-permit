#!/usr/bin/env python
import os
import sys


def main():
    """
    Sets the default Django settings module and attempts to execute the Django
    command line utility. If Django is not installed, raises an ImportError with a
    descriptive message.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sample.settings')

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
