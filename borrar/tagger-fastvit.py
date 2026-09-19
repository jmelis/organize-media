#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "timm",
#     "torch",
#     "pillow",
# ]
# ///
"""
Image tagger using FastViT model.

Usage:
    ./tagger-fastvit.py IMAGE_PATH [IMAGE_PATH2 ...] [--threshold PERCENT] [--top-k N]
"""

import argparse
import json
import sys
from pathlib import Path

import timm
import torch
from PIL import Image
from timm.data import resolve_data_config
from timm.data.transforms_factory import create_transform
from timm.data import ImageNetInfo


def load_model():
    """Load pre-trained FastViT model."""
    model = timm.create_model('fastvit_t8.apple_in1k', pretrained=True)
    model.eval()
    return model


def get_image_tags(image_path: Path, model, transform, threshold: float = 0.5, top_k: int = 5):
    """
    Analyze image and return predicted tags above threshold.

    Args:
        image_path: Path to the image file
        model: FastViT model
        transform: Image preprocessing transform
        threshold: Minimum confidence threshold (0.0-1.0)
        top_k: Number of top predictions to consider

    Returns:
        List of tuples (label, confidence)
    """
    # Load and preprocess image
    img = Image.open(image_path).convert('RGB')
    img_tensor = transform(img).unsqueeze(0)

    # Get predictions
    with torch.no_grad():
        output = model(img_tensor)
        probabilities = torch.nn.functional.softmax(output[0], dim=0)

    # Get top-k predictions
    top_probs, top_indices = torch.topk(probabilities, top_k)

    # Get class labels using ImageNet info
    imagenet_info = ImageNetInfo()

    results = []
    for prob, idx in zip(top_probs, top_indices):
        confidence = prob.item()
        # Only include tags above threshold
        if confidence >= threshold:
            label = imagenet_info.index_to_description(idx.item())
            # Replace spaces with hyphens
            label = label.replace(' ', '-')
            results.append((label, confidence))

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Tag images using FastViT model and save to JSON',
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
        '--threshold',
        type=float,
        default=0.5,
        help='Minimum confidence threshold as decimal (default: 0.5 = 50%%)'
    )
    parser.add_argument(
        '--top-k',
        type=int,
        default=5,
        help='Number of top predictions to consider (default: 5)'
    )

    args = parser.parse_args()

    # Validate threshold
    if not 0.0 <= args.threshold <= 1.0:
        print(f"Error: Threshold must be between 0.0 and 1.0", file=sys.stderr)
        return 1

    # Validate image paths
    invalid_paths = [p for p in args.image_paths if not p.exists()]
    if invalid_paths:
        print(f"Error: Image file(s) not found:", file=sys.stderr)
        for p in invalid_paths:
            print(f"  {p}", file=sys.stderr)
        return 1

    try:
        # Load model and create transform
        print("Loading FastViT model...", file=sys.stderr)
        model = load_model()
        config = resolve_data_config({}, model=model)
        transform = create_transform(**config)

        # Process all images
        results = []
        for image_path in args.image_paths:
            print(f"Analyzing: {image_path.name}", file=sys.stderr)

            tags = get_image_tags(image_path, model, transform, args.threshold, args.top_k)

            print(f"Found {len(tags)} tag(s) above {args.threshold:.0%} threshold", file=sys.stderr)

            # Add to results
            results.append({
                "image": str(image_path),
                "tags": [
                    {"label": label, "confidence": confidence}
                    for label, confidence in tags
                ]
            })

        # Output JSON array to stdout
        print(json.dumps(results, indent=2))

        return 0

    except Exception as e:
        print(f"Error processing image: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
