# coding: utf-8
import copy
import types

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat, Substr
from django.http import Http404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import trans_real
from modeltranslation import settings as mt_settings
from modeltranslation.translator import NotRegistered, translator
from modeltranslation.utils import build_localized_fieldname, get_language
from wagtail.admin.panels import (
    FieldPanel,
    FieldRowPanel,
    InlinePanel,
    MultiFieldPanel,
    ObjectList,
    extract_panel_definitions_from_model_class,
)
from wagtail.contrib.routable_page.models import RoutablePageMixin
from wagtail.coreutils import WAGTAIL_APPEND_SLASH
from wagtail.fields import StreamField, StreamValue
from wagtail.models import Page, Site, SiteRootPath
from wagtail.search.index import SearchField
from wagtail.url_routing import RouteResult

from wagtail_modeltranslation.patch_wagtailadmin_forms import patch_admin_page_form
from wagtail_modeltranslation.settings import (
    CUSTOM_COMPOSED_PANELS,
    CUSTOM_INLINE_PANELS,
    CUSTOM_SIMPLE_PANELS,
    TRANSLATE_SLUGS,
)
from wagtail_modeltranslation.utils import compare_class_tree_depth

try:
    # Wagtail 5.0.2 onwards.
    from wagtail.admin.panels import TitleFieldPanel

    SIMPLE_PANEL_CLASSES = [FieldPanel, TitleFieldPanel]
except ImportError:
    TitleFieldPanel = None
    SIMPLE_PANEL_CLASSES = [FieldPanel]

SIMPLE_PANEL_CLASSES += CUSTOM_SIMPLE_PANELS
COMPOSED_PANEL_CLASSES = [MultiFieldPanel, FieldRowPanel] + CUSTOM_COMPOSED_PANELS
INLINE_PANEL_CLASSES = [InlinePanel] + CUSTOM_INLINE_PANELS


class WagtailTranslator(object):
    _patched_models = []

    def __init__(self, model):
        # Check if this class was already patched
        if model in WagtailTranslator._patched_models:
            return

        self.patched_model = model

        if issubclass(model, Page):
            self._patch_page_models(model)
        else:
            self._patch_other_models(model)

        WagtailTranslator._patched_models.append(model)

    def _patch_fields(self, model):
        translation_registered_fields = translator.get_options_for_model(model).all_fields

        model_fields = model._meta.get_fields()
        for field in model_fields:
            if (
                isinstance(field, StreamField)
                and field.name in translation_registered_fields
            ):
                descriptor = getattr(model, field.name)
                _patch_stream_field_meaningful_value(descriptor)

    def _patch_page_models(self, model):
        # PANEL PATCHING

        # Check if the model has a custom edit handler
        if hasattr(model, "edit_handler"):
            tabs = model.edit_handler.children

            for tab in tabs:
                tab.children = self._patch_panels(tab.children)

        else:
            # If the page doesn't have an edit_handler we patch the panels that
            # wagtail uses by default

            if hasattr(model, "content_panels"):
                model.content_panels = self._patch_panels(model.content_panels)
            if hasattr(model, "promote_panels"):
                model.promote_panels = self._patch_panels(model.promote_panels)
            if hasattr(model, "settings_panels"):
                model.settings_panels = self._patch_panels(model.settings_panels)

        # Clear the edit handler cached value, if it exists, so wagtail reconstructs
        # the edit_handler based on the patched panels
        model.get_edit_handler.cache_clear()

        # SEARCH FIELDS PATCHING

        translation_registered_fields = translator.get_options_for_model(model).all_fields

        for field in model.search_fields:
            # Check if the field is a SearchField and if it is one of the fields registered for translation
            if (
                isinstance(field, SearchField)
                and field.field_name in translation_registered_fields
            ):
                # If it is we create a clone of the original SearchField to keep all the defined options
                # and replace its name by the translated one
                for language in mt_settings.AVAILABLE_LANGUAGES:
                    translated_field = copy.deepcopy(field)
                    translated_field.field_name = build_localized_fieldname(
                        field.field_name, language
                    )
                    model.search_fields = list(model.search_fields) + [translated_field]

        # PATCH FIELDS
        self._patch_fields(model)

        # OVERRIDE CLEAN METHOD
        model.base_form_class = patch_admin_page_form(model.base_form_class)

        # OVERRIDE PAGE METHODS
        if TRANSLATE_SLUGS:
            model.set_url_path = _new_set_url_path
            model.route = _new_route
            model._update_descendant_url_paths = _new_update_descendant_url_paths
            if not hasattr(model, "_get_site_root_paths"):
                model.get_url_parts = _new_get_url_parts  # Wagtail<1.11
            model._get_site_root_paths = _new_get_site_root_paths
            _patch_clean(model)

            if not model.save.__name__.startswith("localized"):
                setattr(model, "save", LocalizedSaveDescriptor(model.save))

    def _patch_other_models(self, model):
        # PATCH FIELDS
        self._patch_fields(model)
        if hasattr(model, "edit_handler"):
            edit_handler = model.edit_handler
            for tab in edit_handler.children:
                tab.children = self._patch_panels(tab.children)
        elif hasattr(model, "panels"):
            model.panels = self._patch_panels(model.panels)
        elif hasattr(model, "snippet_viewset"):
            edit_handler = model.snippet_viewset.get_edit_handler()
            if isinstance(edit_handler, ObjectList):
                edit_handler.children = self._patch_ObjectList(edit_handler.children, model)
                model.edit_handler = edit_handler.children.bind_to_model(model=model)
            else:
                for tab in edit_handler.children:
                    tab.children = self._patch_panels(tab.children)
                model.snippet_viewset.edit_handler = edit_handler.bind_to_model(model)
        else:
            panels = extract_panel_definitions_from_model_class(model)
            edit_handler = self._patch_ObjectList(panels, model)
            model.edit_handler = edit_handler.bind_to_model(model=model)

    def _patch_ObjectList(self, obj_list, model):
        translation_registered_fields = translator.get_options_for_model(
            model
        ).all_fields
        panels = list(
            filter(
                lambda field: field.field_name not in translation_registered_fields,
                obj_list,
            )
        )
        return ObjectList(panels)

    def _patch_panels(self, panels_list, related_model=None):
        """
        Patching of the admin panels. If we're patching an InlinePanel panels we must provide
         the related model for that class, otherwise its used the model passed on init.
        """
        patched_panels = []
        current_patching_model = related_model or self.patched_model

        for panel in panels_list:
            if panel.__class__ in SIMPLE_PANEL_CLASSES:
                patched_panels += self._patch_simple_panel(
                    current_patching_model, panel
                )
            elif panel.__class__ in COMPOSED_PANEL_CLASSES:
                patched_panels.append(self._patch_composed_panel(panel, related_model))
            elif panel.__class__ in INLINE_PANEL_CLASSES:
                patched_panels.append(
                    self._patch_inline_panel(current_patching_model, panel)
                )
            else:
                patched_panels.append(panel)

        return patched_panels

    def _patch_simple_panel(self, model, original_panel):
        panel_class = original_panel.__class__
        translated_panels = []
        translation_registered_fields = translator.get_options_for_model(model).all_fields

        # If the panel field is not registered for translation
        # the original one is returned
        if original_panel.field_name not in translation_registered_fields:
            return [original_panel]

        original_field = model._meta.get_field(original_panel.field_name)
        for language in mt_settings.AVAILABLE_LANGUAGES:
            localized_field_name = build_localized_fieldname(
                original_panel.field_name, language
            )

            # if the original field is required and the current language is the default one
            # this field's blank property is set to False
            if not original_field.blank and language == mt_settings.DEFAULT_LANGUAGE:
                localized_field = model._meta.get_field(localized_field_name)
                localized_field.blank = False
            elif isinstance(original_field, StreamField):
                # otherwise the field is optional and
                # if it's a StreamField the stream_block need to be changed to non required
                localized_field = model._meta.get_field(localized_field_name)
                new_stream_block = copy.copy(localized_field.stream_block)
                new_stream_block.meta = copy.copy(localized_field.stream_block.meta)
                new_stream_block.meta.required = False
                localized_field.stream_block = new_stream_block

            if panel_class == TitleFieldPanel:
                if TRANSLATE_SLUGS:
                    # When a title field is changed its corresponding localized slug may need to
                    # be updated.
                    localized_panel = panel_class(
                        localized_field_name,
                        targets=[
                            build_localized_fieldname(target, language)
                            for target in original_panel.targets
                        ],
                        apply_if_live=original_panel.apply_if_live,
                    )
                elif language == mt_settings.DEFAULT_LANGUAGE:
                    # Slugs are not translated, so when a title field in the default language is
                    # updated we must update the slug it is linked to.
                    localized_panel = panel_class(
                        localized_field_name,
                        targets=original_panel.targets,
                        apply_if_live=original_panel.apply_if_live,
                    )
                else:
                    # Slugs are not translated and this title field is in a non-default language.
                    # There is no slug to link the title to, so the TitleFieldPanel becomes a
                    # plain FieldPanel.
                    localized_panel = FieldPanel(
                        localized_field_name, classname="title"
                    )
            else:
                localized_panel = panel_class(localized_field_name)

            # Pass the original panel extra attributes to the localized
            if hasattr(original_panel, "classname"):
                localized_panel.classname = original_panel.classname
            if hasattr(original_panel, "widget"):
                localized_panel.widget = original_panel.widget

            translated_panels.append(localized_panel)

        return translated_panels

    def _patch_composed_panel(self, original_panel, related_model=None):
        panel_class = original_panel.__class__
        patched_children_panels = self._patch_panels(
            original_panel.children, related_model
        )

        localized_panel = panel_class(patched_children_panels)

        # Pass the original panel extra attributes to the localized
        if hasattr(original_panel, "classname"):
            localized_panel.classname = original_panel.classname
        if hasattr(original_panel, "heading"):
            localized_panel.heading = original_panel.heading

        return localized_panel

    def _patch_inline_panel(self, model, panel):
        # get the model relation through the panel relation_name which is the
        # inline model related_name
        relation = getattr(model, panel.relation_name)

        related_model = relation.rel.related_model

        # If the related model is not registered for translation there is nothing
        # for us to do
        try:
            translator.get_options_for_model(related_model)
        except NotRegistered:
            pass
        else:
            if not hasattr(related_model, "panels"):
                panels = extract_panel_definitions_from_model_class(related_model)
                translation_registered_fields = translator.get_options_for_model(
                    related_model
                ).all_fields
                panels = list(
                    filter(
                        lambda field: field.field_name
                        not in translation_registered_fields,
                        panels,
                    )
                )
                related_model.panels = panels
            related_model.panels = self._patch_panels(
                getattr(related_model, "panels", []), related_model
            )

        # The original panel is returned as only the related_model panels need to be
        # patched, leaving the original untouched
        return panel


# Overridden Page methods adapted to the translated fields


def _localized_set_url_path(page, parent, language):
    """
    Updates a localized url_path for a given language
    """
    localized_slug_field = build_localized_fieldname("slug", language)
    default_localized_slug_field = build_localized_fieldname(
        "slug", mt_settings.DEFAULT_LANGUAGE
    )
    localized_url_path_field = build_localized_fieldname("url_path", language)
    default_localized_url_path_field = build_localized_fieldname(
        "url_path", mt_settings.DEFAULT_LANGUAGE
    )
    if parent:
        # Emulate the default behavior of django-modeltranslation to get the slug and url path
        # for the current language. If the value for the current language is invalid we get the one
        # for the default fallback language
        slug = (
            getattr(page, localized_slug_field, None)
            or getattr(page, default_localized_slug_field, None)
            or page.slug
        )
        parent_url_path = (
            getattr(parent, localized_url_path_field, None)
            or getattr(parent, default_localized_url_path_field, None)
            or parent.url_path
        )

        setattr(page, localized_url_path_field, parent_url_path + slug + "/")

    else:
        # a page without a parent is the tree root,
        # which always has a url_path of '/'
        setattr(page, localized_url_path_field, "/")


def _new_set_url_path(self, parent):
    """
    This method override populates url_path for each specified language.
    This way we can get different urls for each language, defined
    by page slug.
    """
    for language in mt_settings.AVAILABLE_LANGUAGES:
        _localized_set_url_path(self, parent, language)

    return self.url_path


def _new_route(self, request, path_components):
    """
    Rewrite route method in order to handle languages fallbacks
    """
    # copied from wagtail/contrib/wagtailroutablepage/models.py mixin ##
    # Override route when Page is also RoutablePage
    if isinstance(self, RoutablePageMixin):
        if self.live:
            try:
                path = "/"
                if path_components:
                    path += "/".join(path_components) + "/"

                view, args, kwargs = self.resolve_subpage(path)
                return RouteResult(self, args=(view, args, kwargs))
            except Http404:
                pass

    if path_components:
        # request is for a child of this page
        child_slug = path_components[0]
        remaining_components = path_components[1:]

        subpages = self.get_children()
        for page in subpages:
            if page.slug == child_slug:
                return page.specific.route(request, remaining_components)
        raise Http404

    else:
        # request is for this very page
        if self.live:
            return RouteResult(self)
        else:
            raise Http404


def _validate_slugs(page):
    """
    Determine whether the given slug is available for use on a child page of
    parent_page.
    """
    parent_page = page.get_parent()

    if parent_page is None:
        # the root page's slug can be whatever it likes...
        return {}

    # Save the current active language
    current_language = get_language()

    siblings = page.get_siblings(inclusive=False)

    errors = {}

    for language in mt_settings.AVAILABLE_LANGUAGES:
        # Temporarily activate every language because even though there might
        # be no repeated value for slug_pt the fallback of an empty slug could
        # already be in use

        trans_real.activate(language)

        siblings_slugs = [sibling.slug for sibling in siblings]

        if page.slug in siblings_slugs:
            errors[build_localized_fieldname("slug", language)] = _(
                "This slug is already in use"
            )

    # Re-enable the original language
    trans_real.activate(current_language)

    return errors


def _patch_clean(model):
    old_clean = model.clean

    def clean(self):
        errors = _validate_slugs(self)

        if errors:
            raise ValidationError(errors)

        # Call the original clean method to avoid losing validations
        old_clean(self)

    model.clean = clean


def _new_update_descendant_url_paths(self, old_url_path, new_url_path):
    return _localized_update_descendant_url_paths(self, old_url_path, new_url_path)


def _localized_update_descendant_url_paths(
    page, old_url_path, new_url_path, language=None
):
    localized_url_path = "url_path"
    if language:
        localized_url_path = build_localized_fieldname("url_path", language)
    old_url_path_len = len(old_url_path)
    descendants = Page.objects.rewrite(False).filter(path__startswith=page.path).exclude(
        **{localized_url_path: None}).exclude(pk=page.pk)
    update_descendants = []
    for descendant in descendants:
        old_descendant_url_path = getattr(descendant, localized_url_path)
        if old_descendant_url_path.startswith(old_url_path):
            new_descendant_url_path = new_url_path + old_descendant_url_path[old_url_path_len:]
            setattr(descendant, localized_url_path, new_descendant_url_path)
            update_descendants.append(descendant)

    # Update all descendants in a single query
    Page.objects.bulk_update(update_descendants, [localized_url_path])


def _localized_site_get_site_root_paths():
    """
    Localized version of ``Site.get_site_root_paths()``
    """
    current_language = get_language()
    cache_key = "wagtail_site_root_paths_{}".format(current_language)
    result = cache.get(cache_key)

    if result is None:
        sites = Site.objects.select_related("root_page", "root_page__locale")
        result = [
            (
                site.id,
                site.root_page.url_path,
                site.root_url,
                site.root_page.locale.language_code,
            )
            for site in sites.order_by("-root_page__url_path")
        ]
        cache.set(cache_key, result, 3600)

    return [SiteRootPath(*srp) for srp in result]


def _new_get_site_root_paths(self, request=None):
    """
    Return localized site_root_paths, using the cached copy on the
    request object if available and if language is the same.
    """
    # if we have a request, use that to cache site_root_paths; otherwise, use self
    current_language = get_language()
    cache_object = request if request else self
    if (
        not hasattr(cache_object, "_wagtail_cached_site_root_paths_language")
        or cache_object._wagtail_cached_site_root_paths_language != current_language
    ):
        cache_object._wagtail_cached_site_root_paths_language = current_language
        cache_object._wagtail_cached_site_root_paths = (
            _localized_site_get_site_root_paths()
        )

    return cache_object._wagtail_cached_site_root_paths


def _new_get_url_parts(self, request=None):
    """
    For Wagtail<1.11 ``Page.get_url_parts()`` is patched so it uses ``self._get_site_root_paths(request)``
    """
    for site_id, root_path, root_url in self._get_site_root_paths(request):
        if self.url_path.startswith(root_path):
            page_path = reverse(
                "wagtail_serve", args=(self.url_path[len(root_path) :],)
            )

            # Remove the trailing slash from the URL reverse generates if
            # WAGTAIL_APPEND_SLASH is False and we're not trying to serve
            # the root path
            if not WAGTAIL_APPEND_SLASH and page_path != "/":
                page_path = page_path.rstrip("/")

            return (site_id, root_url, page_path)


def _update_translation_descendant_url_paths(old_record, page):
    # update children paths, must be done for all languages to ensure fallbacks are applied
    languages_changed = []
    default_localized_url_path = build_localized_fieldname(
        "url_path", mt_settings.DEFAULT_LANGUAGE
    )
    for language in mt_settings.AVAILABLE_LANGUAGES:
        localized_url_path = build_localized_fieldname("url_path", language)
        old_url_path = (
            getattr(old_record, localized_url_path)
            or getattr(old_record, default_localized_url_path)
            or ""
        )
        new_url_path = getattr(page, localized_url_path) or getattr(
            page, default_localized_url_path
        )

        if old_url_path == new_url_path:
            # nothing to do
            continue

        languages_changed.append(language)
        _localized_update_descendant_url_paths(
            page, old_url_path, new_url_path, language
        )

    _update_untranslated_descendants_url_paths(page, languages_changed)


def _update_untranslated_descendants_url_paths(page, languages_changed):
    """
    Updates localized URL Paths for child pages that don't have their localized URL Paths set yet
    """
    if not languages_changed:
        return

    condition = Q()
    update_fields = []
    for language in languages_changed:
        localized_url_path = build_localized_fieldname("url_path", language)
        condition |= Q(**{localized_url_path: None})
        update_fields.append(localized_url_path)

    # let's restrict the query to children who don't have localized_url_path set yet
    children = page.get_children().filter(condition)
    for child in children:
        for language in languages_changed:
            _localized_set_url_path(child, page, language)
        child.save(
            update_fields=update_fields
        )  # this will trigger any required saves downstream


class LocalizedSaveDescriptor(object):
    def __init__(self, f):
        self.func = f
        self.__name__ = "localized_{}".format(f.__name__)

    @transaction.atomic  # only commit when all descendants are properly updated
    def __call__(self, instance, *args, **kwargs):
        # when updating, save doesn't check if slug_xx has changed so it can only detect changes in slug
        # from current language. We need to ensure that if a given localized slug changes we call set_url_path
        if (
            not instance.id
        ):  # creating a record, wagtail will call set_url_path, nothing to do.
            return self.func(instance, *args, **kwargs)

        old_record = None
        change_url_path = change_descendant_url_path = False
        for language in mt_settings.AVAILABLE_LANGUAGES:
            localized_slug = build_localized_fieldname("slug", language)
            # similar logic used in save
            if not (
                "update_fields" in kwargs
                and localized_slug not in kwargs["update_fields"]
            ):
                old_record = old_record or Page.objects.get(id=instance.id)
                if getattr(old_record, localized_slug) != getattr(
                    instance, localized_slug
                ):
                    change_descendant_url_path = True
                    if language != get_language():
                        change_url_path = True
                        break

            # Pages may have have their url_path_xx changed upstream when a parent has its url_path changed.
            # If that's the case let's propagate the change to children
            if not change_descendant_url_path:
                localized_url_path = build_localized_fieldname("url_path", language)
                if not (
                    "update_fields" in kwargs
                    and localized_url_path not in kwargs["update_fields"]
                ):
                    old_record = old_record or Page.objects.get(id=instance.id)
                    if getattr(old_record, localized_url_path) != getattr(
                        instance, localized_url_path
                    ):
                        change_descendant_url_path = True

        # if any language other than current language had it slug changed set_url_path will be executed
        if change_url_path:
            instance.set_url_path(instance.get_parent())

        result = self.func(instance, *args, **kwargs)

        # update children localized paths if any language had it slug changed
        if change_descendant_url_path:
            _update_translation_descendant_url_paths(old_record, instance)

        # Check if this is a root page of any sites and clear the 'wagtail_site_root_paths_XX' key if so
        if Site.objects.filter(root_page=instance).exists():
            for language in mt_settings.AVAILABLE_LANGUAGES:
                cache.delete("wagtail_site_root_paths_{}".format(language))

        return result

    def __get__(self, instance, owner=None):
        return types.MethodType(self, instance) if instance else self


def _patch_stream_field_meaningful_value(field):
    old_meaningful_value = field.meaningful_value

    def meaningful_value(self, val, undefined):
        """
        Check if val is considered non-empty.
        """
        if isinstance(val, StreamValue):
            return len(val) != 0
        return old_meaningful_value(self, val, undefined)

    field.meaningful_value = meaningful_value.__get__(field)


def patch_wagtail_models():
    # After all models being registered the Page or BaseSiteSetting subclasses and snippets are patched
    registered_models = translator.get_registered_models()

    # We need to sort the models to ensure that subclasses of a model are registered first,
    # or else if the panels are inherited all the changes on the subclass would be
    # reflected in the superclass
    registered_models.sort(key=compare_class_tree_depth)

    for model_class in registered_models:
        WagtailTranslator(model_class)
