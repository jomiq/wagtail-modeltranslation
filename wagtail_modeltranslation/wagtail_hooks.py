import json

from django.conf import settings
from django.urls import re_path
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, QueryDict
from django.shortcuts import redirect, render

from django.templatetags.static import static
from django.template import Context
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from six import iteritems

from modeltranslation.utils import get_language_info
from modeltranslation import settings as mt_settings
from wagtail_modeltranslation import settings as wmt_settings

from .patch_wagtailadmin_forms import PatchedCopyForm

from wagtail import hooks, VERSION as _WAGTAIL_VERSION
from wagtail.models import Page
from wagtail.rich_text.pages import PageLinkHandler
from wagtail.admin import messages

from wagtail.admin.views.pages.utils import get_valid_next_url_from_request

if _WAGTAIL_VERSION >= (5, 1):
    # https://docs.wagtail.org/en/stable/releases/5.1.html#insert-editor-css-hook-is-deprecated
    _HOOK_INSERT_CSS = "insert_global_admin_css"
else:
    _HOOK_INSERT_CSS = "insert_editor_css"


###############################################################################
# Copy StreamFields content
###############################################################################
@csrf_exempt
def return_translation_target_field_rendered_html(request, page_id):
    """
    Ajax view that allows to duplicate content
    between translated streamfields
    """

    page = Page.objects.get(pk=page_id)

    if request.is_ajax():
        origin_field_name = request.POST.get("origin_field_name")
        target_field_name = request.POST.get("target_field_name")
        origin_field_serialized = json.loads(request.POST.get("serializedOriginField"))

        # Patch field prefixes from origin field to target field
        target_field_patched = []
        for item in origin_field_serialized:
            patched_item = {"name": None, "value": None}
            for att in iteritems(item):
                target_value = att[1]
                if att[0] == "name":
                    target_value = att[1].replace(origin_field_name, target_field_name)
                    patched_item["name"] = target_value
                else:
                    patched_item["value"] = att[1]

            target_field_patched.append(patched_item)

        # convert to QueryDict
        q_data = QueryDict("", mutable=True)
        for item in target_field_patched:
            q_data.update({item["name"]: item["value"]})

        # get render html

        target_field = page.specific._meta.get_field(target_field_name)
        value_data = target_field.stream_block.value_from_datadict(
            q_data, {}, target_field_name
        )
        target_field_content_html = target_field.formfield().widget.render(
            target_field_name, value_data
        )

    # return html json
    return HttpResponse(
        json.dumps(target_field_content_html), content_type="application/json"
    )


@hooks.register("register_admin_urls")
def copy_streamfields_content():
    return [
        re_path(
            r"pages/(?P<page_id>\d+)/edit/copy_translation_content/$",
            return_translation_target_field_rendered_html,
            name="",
        ),
    ]


@hooks.register(_HOOK_INSERT_CSS)
def modeltranslation_page_editor_css():
    includes = [
        static(f)
        for f in [
            "wagtail_modeltranslation/css/admin_patch.css",
            "wagtail_modeltranslation/css/language_toggles.css",
            "wagtail_modeltranslation/css/fancy_icons.css",
        ]
    ]
    lang_infos = [get_language_info(lang) for lang in mt_settings.AVAILABLE_LANGUAGES]
    if wmt_settings.PALETTE:
        c = wmt_settings.PALETTE
        for i, lang in enumerate(lang_infos):
            if isinstance(wmt_settings.PALETTE, list):
                c = wmt_settings.PALETTE[i % len(wmt_settings.PALETTE)]
            lang["background_color"] = f"hsl({c[0]} {c[1]} {c[2]})"
            lang["border_color"] = f"hsl({c[0]} {c[1]} {0.5*c[2]})"
            

    return render_to_string(
        "modeltranslation_editor_inline.html",
        context={
            "includes": includes,
            "lang_infos": lang_infos,
        },
    )


@hooks.register("register_rich_text_link_handler")
def register_localized_page_link_handler():
    class LocalizedPageLinkHandler(PageLinkHandler):
        @staticmethod
        def expand_db_attributes(attrs, for_editor):
            # This method is a copy of the original one
            # the only difference is the .specific on the escape method
            try:
                page = Page.objects.get(id=attrs["id"])

                if for_editor:
                    editor_attrs = 'data-linktype="page" data-id="%d" ' % page.id
                    parent_page = page.get_parent()
                    if parent_page:
                        editor_attrs += 'data-parent-id="%d" ' % parent_page.id
                else:
                    editor_attrs = ""

                return '<a %shref="%s">' % (editor_attrs, escape(page.specific.url))
            except Page.DoesNotExist:
                return "<a>"

    return ("page", LocalizedPageLinkHandler)


@hooks.register("before_copy_page")
def before_copy_page(request, page):
    parent_page = page.get_parent()
    can_publish = parent_page.permissions_for_user(request.user).can_publish_subpage()
    form = PatchedCopyForm(
        request.POST or None, user=request.user, page=page, can_publish=can_publish
    )
    next_url = get_valid_next_url_from_request(request)

    if request.method == "POST":
        # Prefill parent_page in case the form is invalid (as prepopulated value for the form field,
        # because ModelChoiceField seems to not fall back to the user given value)
        parent_page = Page.objects.get(id=request.POST["new_parent_page"])

        if form.is_valid():
            # Receive the parent page (this should never be empty)
            if form.cleaned_data["new_parent_page"]:
                parent_page = form.cleaned_data["new_parent_page"]

            if not page.permissions_for_user(request.user).can_copy_to(
                parent_page, form.cleaned_data.get("copy_subpages")
            ):
                raise PermissionDenied

            # Re-check if the user has permission to publish subpages on the new parent
            can_publish = parent_page.permissions_for_user(
                request.user
            ).can_publish_subpage()

            update_attrs = {}
            for code, name in settings.LANGUAGES:
                if wmt_settings.TRANSLATE_SLUGS:
                    slug = build_localized_fieldname("slug", code)
                else:
                    slug = "slug"
                title = build_localized_fieldname("title", code)
                update_attrs[slug] = form.cleaned_data["new_{}".format(slug)]
                update_attrs[title] = form.cleaned_data["new_{}".format(title)]

            # Copy the page
            new_page = page.copy(
                recursive=form.cleaned_data.get("copy_subpages"),
                to=parent_page,
                update_attrs=update_attrs,
                keep_live=(can_publish and form.cleaned_data.get("publish_copies")),
                user=request.user,
            )

            # Give a success message back to the user
            if form.cleaned_data.get("copy_subpages"):
                messages.success(
                    request,
                    _("Page '{0}' and {1} subpages copied.").format(
                        page.get_admin_display_title(),
                        new_page.get_descendants().count(),
                    ),
                )
            else:
                messages.success(
                    request,
                    _("Page '{0}' copied.").format(page.get_admin_display_title()),
                )

            for fn in hooks.get_hooks("after_copy_page"):
                result = fn(request, page, new_page)
                if hasattr(result, "status_code"):
                    return result

            # Redirect to explore of parent page
            if next_url:
                return redirect(next_url)
            return redirect("wagtailadmin_explore", parent_page.id)

    return render(
        request,
        "modeltranslation_copy.html",
        {"page": page, "form": form, "next": next_url},
    )
