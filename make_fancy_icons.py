#! /usr/bin/env python
import os
import wagtail
from django.template.engine import Engine
from django.template import Template, Context
from django.utils.safestring import mark_safe
# render icons into inline css. do this offline please.

ICON_DIR = os.path.join(
    os.path.dirname(wagtail.__file__), 
    "admin/templates/wagtailadmin/icons",
)

TEMPLATE_FILE = os.path.join(
    os.path.dirname(__file__),
    "wagtail_modeltranslation/templates/fancy_icons.css",
    )

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), 
    "wagtail_modeltranslation/static/wagtail_modeltranslation/css/fancy_icons.css",
    )


def get_svg(filename: str):
    with open(filename) as f:
        return mark_safe(f.read()
                         .rstrip()
                         .replace('"', "'")
                         .replace("<svg id=", "<svg height='16' width='16' fill='white' id="))
    

def main():
    ctx = {
        "no_view": get_svg(os.path.join(ICON_DIR, "no-view.svg")),
        "view": get_svg(os.path.join(ICON_DIR, "view.svg"))
    }

    engine = Engine()
    template = Template(open(TEMPLATE_FILE).read(), engine=engine)
    res = template.render(Context(ctx))
 
    print(res)
    with open(OUTPUT_FILE, "w") as f:
        f.write(res)

if __name__ == "__main__":
    main()