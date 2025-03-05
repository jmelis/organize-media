import argparse
import sys

from exiftool import ExifToolHelper


TAGS = [
    "MakerNotes:FilmMode",
    "MakerNotes:HighlightTone",
    "MakerNotes:ShadowTone",
    "MakerNotes:Saturation",  # color
    "MakerNotes:ColorChromeEffect",
    "MakerNotes:ColorChromeFXBlue",
    "MakerNotes:WhiteBalanceFineTune",
]

RECIPE_INFO_TAG = "XMP:ExtDescrAccessibility"

RECIPES = """
    1536|16|16|256|64|32|40 -80,Reggie's Portra
    1536|0|0|256|64|32|40 -100,Kodachrome 64
    1536|-32|-16|224|64|64|20 -20,Muted
    2048|32|-48|224|64|64|20 -60,Pacific Blues
    0|-32|-16|256|64|0|40 -80,Nurture Nature
    NONE|-16|-48|1280|0|0|0 0,Acros Journey
    1536|0|0|256|64|0|-20 80,McCurry Kodachrome
    2048|32|-16|224|64|64|-20 -60,Classic Cuban Neg
"""


def serialize(tags):
    return "|".join([str(tags.get(t, "NONE")) for t in TAGS])


def get_tags(file, human=False):
    if human:
        common_args = ["-G"]
    else:
        common_args = ["-G", "-n"]

    with ExifToolHelper(common_args=common_args) as et:
        tags = et.get_tags(file, tags=(TAGS + [RECIPE_INFO_TAG]))[0]

    return tags


def write_recipe_info(file, recipe_info_data):
    with ExifToolHelper() as et:
        et.set_tags(
            file,
            tags={RECIPE_INFO_TAG: recipe_info_data},
            params=["-overwrite_original"],
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", action="store_true")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    recipes_dict = dict([r.strip().split(",", 2) for r in RECIPES.strip().split("\n")])

    for file in args.files:
        msg = file

        tags = get_tags(file)
        recipe_id = serialize(tags)

        recipe = recipes_dict.get(recipe_id, None)
        if recipe is not None:
            msg += f" -- Recipe: {recipe}"
            if args.tag and tags.get(RECIPE_INFO_TAG) != recipe:
                write_recipe_info(file, recipe)
                msg += " [successfully tagged]"
            print(msg)
        else:
            tags = get_tags(file, human=True)

            try:
                del tags["SourceFile"]
                del tags[RECIPE_INFO_TAG]
            except KeyError:
                pass

            print(msg)

            for tag, value in tags.items():
                print(f"  {tag}: {value}")
            print(f"  RecipeId: {recipe_id}")

        sys.stdout.flush()
