import re
from urllib.parse import unquote

from django import template
from django.urls import resolve
from django.template import Context
from django.urls.exceptions import Resolver404
from django.utils.translation import activate, get_language, get_language_info
from django.utils.safestring import SafeString
from modeltranslation import settings as mt_settings
from modeltranslation.settings import DEFAULT_LANGUAGE
from modeltranslation.utils import fallbacks
from modeltranslation.manager import get_translatable_fields_for_model
from six import iteritems
from wagtail.models import Page
from wagtail.templatetags.wagtailcore_tags import pageurl

from ..contextlib import use_language

register = template.Library()


# TODO: check templatetag usage

# CHANGE LANGUAGE
@register.simple_tag(takes_context=True)
def change_lang(context, lang=None, page=None, *args, **kwargs):
    current_language = get_language()

    if 'request' in context and lang and current_language and page:
        request = context['request']
        try:
            match = resolve(unquote(request.path, errors='strict'))
        except Resolver404:
            # could be that we are on a non-existent path
            return ''
        non_prefixed_path = re.sub(current_language + '/', '', request.path, count=1)

        # means that is an wagtail page object
        if match.url_name == 'wagtail_serve':
            activate(lang)
            translated_url = page.get_url()
            activate(current_language)

            return translated_url
        elif match.url_name == 'wagtailsearch_search':
            path_components = [component for component in non_prefixed_path.split('/') if component]

            translated_url = '/' + lang + '/' + path_components[0] + '/'
            if request.GET:
                translated_url += '?'
                for count, (key, value) in enumerate(iteritems(request.GET)):
                    if count != 0:
                        translated_url += "&"
                    translated_url += key + '=' + value
            return translated_url

    return ''


class GetAvailableLanguagesNode(template.Node):
    """Get available languages."""

    def __init__(self, variable):
        self.variable = variable

    def render(self, context):
        """Rendering."""
        context[self.variable] = mt_settings.AVAILABLE_LANGUAGES
        return ''


# Alternative to slugurl which uses chosen or default language for language
@register.simple_tag(takes_context=True)
def slugurl_trans(context, slug, language=None):
    """
    Examples:
        {% slugurl_trans 'default_lang_slug' %}
        {% slugurl_trans 'de_lang_slug' 'de' %}

    Returns the URL for the page that has the given slug.
    """
    language = language or DEFAULT_LANGUAGE

    with use_language(language):
        page = Page.objects.filter(slug=slug).first()

    if page:
        # call pageurl() instead of page.relative_url() here so we get the ``accepts_kwarg`` logic
        return pageurl(context, page)


@register.tag('get_available_languages_wmt')
def do_get_available_languages(unused_parser, token):
    """
    Store a list of available languages in the context.

    Usage::

        {% get_available_languages_wmt as languages %}
        {% for language in languages %}
        ...
        {% endfor %}

    This will just pull the MODELTRANSLATION_LANGUAGES (or LANGUAGES) setting
    from your setting file (or the default settings) and
    put it into the named variable.
    """
    args = token.contents.split()
    if len(args) != 3 or args[1] != 'as':
        raise template.TemplateSyntaxError(
            "'get_available_languages_wmt' requires 'as variable' "
            "(got %r)" % args)
    return GetAvailableLanguagesNode(args[2])

@register.simple_tag(takes_context=True)
def lang_toggle_editor(context: Context):
    """ Inserts language toggles in the page editor """
    is_editor = "/edit.html" in context.template_name or "/create.html" in context.template_name
    if is_editor:    
        res = "<div class='locale-picker'> <ul>"
        for lang in mt_settings.AVAILABLE_LANGUAGES:
            info = get_language_info(lang)
            res += "<li><label class='button'>"
            res += f"<input class='locale-picker-checkbox' type='checkbox' name='sw' id='{lang}_checkbox' checked='true' />"
            res += f"{info.get('name_local', lang)}"
            res += f"</label></li>"
        res += "</ul></div>"

        return SafeString(res)

@register.simple_tag(takes_context=True)
def is_fallback(context: Context, field_name: str) -> bool:
    """ Check if item is translated or if a fallback value is used.
        Useful for displaying 'translation is missing!' type messages 
        Use: 
            {% if is_fallback "title" %} The title is a lie ...   
    """  
    with fallbacks(False):
        return not bool(getattr(context.get("page"), field_name))
    

@register.simple_tag(takes_context=True)
def is_fully_translated(context: Context, ignore_fields=["seo_title", "search_description"], skip_empty=True) -> bool:
    """ Check if all translated fields are populated for the current language.
        Defaults:
            Ignore the non-user-facing fields: seo_title, search_description
            Do not check fields that are not populated
    """
    
    if get_language() != mt_settings.DEFAULT_LANGUAGE:
        fields = [f for f in get_translatable_fields_for_model(context.get("page").__class__) 
                if f not in ignore_fields]
        if skip_empty:
            fields = [f for f in fields if bool(getattr(context.get("page"), f))]

        with fallbacks(False):
            for field in fields:
                if not bool(getattr(context.get("page"), field)):
                    return False
    
    return True
