import argparse
import sys

from exiftool import ExifToolHelper


TAGS = [
    # "EXIF:Make",
    # "EXIF:Model",
    # "EXIF:ExposureTime",
    # "EXIF:FNumber",
    # "EXIF:ISO",
    "MakerNotes:FilmMode",
    #"MakerNotes:DynamicRangeSetting",
    #"MakerNotes:DevelopmentDynamicRange",
    "MakerNotes:HighlightTone",
    "MakerNotes:ShadowTone",
    "MakerNotes:Saturation", # color
    #"MakerNotes:NoiseReduction",
    #"MakerNotes:Sharpness",
    # clarity
    #"MakerNotes:GrainEffectSize",
    #"MakerNotes:GrainEffectRoughness",
    "MakerNotes:ColorChromeEffect",
    "MakerNotes:ColorChromeFXBlue",
    "MakerNotes:WhiteBalanceFineTune",
    # ?
    # "MakerNotes:Contrast",
]

RECIPES = """
1536|16|16|256|64|32|40 -80,Reggie's Portra
1536|0|0|256|64|32|40 -100,Kodachrome 64
1536|-32|-16|224|64|64|20 -20,Muted
2048|32|-48|224|64|64|20 -60,Pacific Blues
0|-32|-16|256|64|0|40 -80,Nurture Nature
NONE|-16|-48|1280|0|0|0 0,Acros Journey
1536|0|0|256|64|0|-20 80,McCurry Kodachrome
"""

def serialize(tags):
    return "|".join([str(tags.get(t,"NONE")) for t in TAGS])

def get_tags(file, human=False):
    if human:
        common_args = ["-G"]
    else:
        common_args = ["-G","-n"]

    with ExifToolHelper(common_args=common_args) as et:
        tags = et.get_tags(file,tags=TAGS)[0]

    return tags

if __name__ == "__main__":
    # argparser for files (nargs)
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    recipes_dict = {}
    for recipe_recipename  in RECIPES.strip().split("\n"):
        recipe, recipename = recipe_recipename.split(",",1)
        recipes_dict[recipe] = recipename

    for file in args.files:
        print(file)

        tags = get_tags(file)
        recipe_id = serialize(tags)

        if recipe_id in recipes_dict:
            recipe = recipes_dict[recipe_id]
            print(f"  Recipe: {recipe}")
        else:
            tags = get_tags(file, human=True)

            if 'SourceFile' in tags:
                del tags['SourceFile']

            for tag, value in tags.items():
                print(f"  {tag}: {value}")
            print(f"  RecipeId: {recipe_id}")

        print()

        sys.stdout.flush()


