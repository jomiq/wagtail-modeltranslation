#!/usr/bin/env python
import os
import argparse 
import django
from django.core.management import call_command

os.environ['DJANGO_SETTINGS_MODULE'] = 'wagtail_modeltranslation.settings'


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
        "--clean",
        action="store_true",
        help="Do not include obsolete messages",
    )

    parser.add_argument(
        "--compile",
        action="store_true",
        help="Compile translation files",
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
    
    django.setup()
    if args.make:
        extra_args = {"verbosity": 2}
        if args.clean:
            extra_args["no_obsolete"] = True
        call_command("makemessages", locale=args.locale, **extra_args )
    
    if args.compile:
        call_command("compilemessages", locale=args.locale)
