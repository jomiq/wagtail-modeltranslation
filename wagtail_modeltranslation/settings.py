import os
from django.conf import settings

from wagtail_modeltranslation.utils import import_from_string



# TODO: Consider making panel validation using class name to avoid the import_from_string method

# Load allowed CUSTOM_PANELS from Django settings
CUSTOM_SIMPLE_PANELS = [import_from_string(panel_class) for panel_class in
                        getattr(settings, 'WAGTAILMODELTRANSLATION_CUSTOM_SIMPLE_PANELS', [])]
CUSTOM_COMPOSED_PANELS = [import_from_string(panel_class) for panel_class in
                          getattr(settings, 'WAGTAILMODELTRANSLATION_CUSTOM_COMPOSED_PANELS', [])]
CUSTOM_INLINE_PANELS = [import_from_string(panel_class) for panel_class in
                        getattr(settings, 'WAGTAILMODELTRANSLATION_CUSTOM_INLINE_PANELS', [])]
TRANSLATE_SLUGS = getattr(settings, 'WAGTAILMODELTRANSLATION_TRANSLATE_SLUGS', True)
LOCALE_PICKER = getattr(settings, 'WAGTAILMODELTRANSLATION_LOCALE_PICKER', True)
LOCALE_PICKER_DEFAULT = getattr(settings, 'WAGTAILMODELTRANSLATION_LOCALE_PICKER_DEFAULT', None)
LOCALE_PICKER_RESTORE = getattr(settings, 'WAGTAILMODELTRANSLATION_LOCALE_PICKER_RESTORE', False)
PALETTE = getattr(settings, "WAGTAILMODELTRANSLATION_PALETTE", None)
if PALETTE == True:
    from wagtail_modeltranslation.utils import default_palette_hsl as PALETTE





LOCALE_PATHS = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locale")]
print(f"locale: {LOCALE_PATHS}")