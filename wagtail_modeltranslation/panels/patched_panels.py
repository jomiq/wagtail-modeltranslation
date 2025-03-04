from wagtail.admin.panels import TitleFieldPanel

class PatchedTitleFieldPanel(TitleFieldPanel):
    """ Just prepends 'wmt-' to the classname so that this can be sensibly styled. """
    def __init__(self, *args, apply_if_live=False, classname="title", placeholder=True, targets=..., **kwargs):
        classname = "wmt-" + classname
        super().__init__(*args, apply_if_live=apply_if_live, classname=classname, placeholder=placeholder, targets=targets, **kwargs)