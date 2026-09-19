#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "ollama",
#     "pillow",
# ]
# ///
"""
Image tagger using LLaVA vision model via Ollama.

Usage:
    ./tagger-llava.py IMAGE_PATH [IMAGE_PATH2 ...]
    ./tagger-llava.py IMAGE_PATH --num-tags N
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import ollama
from PIL import Image


def tag_image(image_path: Path, num_tags: int = 10) -> str:
    """
    Generate descriptive tags for an image using LLaVA.

    Args:
        image_path: Path to the image file
        num_tags: Number of tags to generate

    Returns:
        Comma-separated list of tags
    """
    # Resize image to 672x672 for optimal processing
    image = Image.open(image_path).convert('RGB')
    image = image.resize((672, 672))

    # Save to temporary file
    with NamedTemporaryFile(mode='wb', suffix='.jpg', delete=False) as temp_file:
        temp_path = temp_file.name
        image.save(temp_file, format='JPEG')

    try:
        # Encode image to base64
        with open(temp_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        # Call LLaVA via Ollama
        response = ollama.chat(
            model="llava",
            messages=[
                {
                    "role": "user",
                    "content": f"Generate {num_tags} tags for this image as a comma-separated list. Be specific but concise.",
                    "images": [image_data],
                }
            ],
        )

        return response['message']['content']
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    parser = argparse.ArgumentParser(
        description='Tag images using LLaVA vision model and save to JSON',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        'image_paths',
        type=Path,
        nargs='+',
        help='Path(s) to image file(s)'
    )
    parser.add_argument(
        '--num-tags',
        type=int,
        default=10,
        help='Number of tags to generate per image (default: 10)'
    )

    args = parser.parse_args()

    # Validate image paths
    invalid_paths = [p for p in args.image_paths if not p.exists()]
    if invalid_paths:
        print(f"Error: Image file(s) not found:", file=sys.stderr)
        for p in invalid_paths:
            print(f"  {p}", file=sys.stderr)
        return 1

    try:
        # Process all images
        results = []
        for image_path in args.image_paths:
            print(f"Analyzing: {image_path.name}", file=sys.stderr)
            tags_str = tag_image(image_path, args.num_tags)

            # Parse comma-separated tags into a list and replace spaces with hyphens
            tags_list = [tag.strip().replace(' ', '-') for tag in tags_str.split(',')]

            print(f"Found {len(tags_list)} tag(s)", file=sys.stderr)

            # Add to results
            results.append({
                "image": str(image_path),
                "tags": tags_list
            })

        # Output JSON array to stdout
        print(json.dumps(results, indent=2))

        return 0

    except Exception as e:
        print(f"Error processing image: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
