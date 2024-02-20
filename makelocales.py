#!/usr/bin/env python
import os
import sys
import argparse 

import django
from django.core.management import execute_from_command_line
from django.core.management import call_command

os.environ['DJANGO_SETTINGS_MODULE'] = 'wagtail_modeltranslation.settings'


def migrate():
    django.setup()
    call_command('makemigrations', 'tests', verbosity=2, interactive=False)


def run(argv):
    argv = [sys.argv[0], 'test', 'wagtail_modeltranslation']
    execute_from_command_line(argv)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
                    prog='makelocales',
                    description='Helper to create/compile translation messages',
                    epilog='Text at the bottom of help')
    
    parser.add_argument(
        "--make", 
        action="store_true",
        help="Create translation messages",
    )

    parser.add_argument(
        "--compile",
        action="store_true",
        help="Compile translation messages",
    )
    
    parser.add_argument(
        "-l",
        "--locale",
        nargs="+",
        default=[]
    )

    args = parser.parse_args()
    if not (args.make or args.compile):
        parser.print_help()
        exit()
    
    if args.make:
        call_command("makemessages", locale=args.locale)
    
    if args.compile:
        call_command("compilemessages", locale=args.locale)
