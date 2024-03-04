import inspect


def compare_class_tree_depth(model_class):
    """
     Function to sort a list of class objects, where subclasses
    have lower indices than their superclasses
    """

    return -len(inspect.getmro(model_class))


def import_from_string(name):
    """
    Returns a module from a string path
    """
    components = name.split(".")
    mod = __import__(components[0])
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod


default_palette = [
    "#ea7286",
    "#eab281",
    "#e3e19f",
    "#a9c484",
    "#5d937b",
    "#58525a",
    "#a07ca7",
    "#f4a4bf",
    "#f5d1b6",
    "#eeede3",
    "#d6cec2",
    "#a2a6a9",
    "#777f8f",
    "#a3b2d2",
    "#bfded8",
    "#bf796d",
]

default_palette_hsl = [
    (350.0000, 68.2353, 74.0741),
    (28.0000, 71.1765, 71.4286),
    (85.3125, 64.3137, 35.1648),
    (153.3333, 47.0588, 22.5000),
    (285.0000, 33.7255, 4.6512),
    (290.2326, 57.0588, 19.6347),
    (339.7500, 80.0000, 78.4314),
    (25.7143, 83.7255, 75.9036),
    (58.2353, 75.6863, 54.8387),
    (54.5455, 91.1765, 24.4444),
    (36.0000, 80.0000, 19.6078),
    (205.7143, 64.9020, 3.9106),
    (220.0000, 51.3725, 9.6774),
    (220.8511, 73.1373, 34.3066),
    (168.3871, 80.9804, 31.9588),
    (8.7805, 58.8235, 39.0476),
]
