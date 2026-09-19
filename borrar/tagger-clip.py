#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "transformers",
#     "torch",
#     "torchvision",
#     "pillow",
#     "tqdm",
# ]
# ///
"""
Semantic image search using CLIP.

Usage:
    # Index images (generate embeddings)
    ./tagger-clip.py --index IMAGE1.jpg IMAGE2.jpg ...

    # Search with text query
    ./tagger-clip.py --search "sunset over mountains" --top-k 10

    # Search within specific directory
    ./tagger-clip.py --search "person with dog" --scan ~/Pictures/2025 --top-k 5
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from tqdm import tqdm


# Database location
DB_PATH = Path.home() / ".cache" / "organize-media" / "embeddings.db"


def init_db(conn: sqlite3.Connection):
    """Initialize the embeddings database."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            file_path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            embedding BLOB NOT NULL
        )
    """)
    conn.commit()


def load_clip_model():
    """Load CLIP model and processor."""
    print("Loading CLIP model...", file=sys.stderr)
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32", use_fast=True)
    model.eval()
    return model, processor


def get_image_embedding(image_path: Path, model, processor) -> np.ndarray:
    """Generate CLIP embedding for an image."""
    image = Image.open(image_path).convert('RGB')
    inputs = processor(images=image, return_tensors="pt")

    with torch.no_grad():
        image_features = model.get_image_features(**inputs)
        # Normalize embedding
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)

    return image_features.cpu().numpy()[0]


def get_text_embedding(text: str, model, processor) -> np.ndarray:
    """Generate CLIP embedding for text."""
    inputs = processor(text=[text], return_tensors="pt", padding=True)

    with torch.no_grad():
        text_features = model.get_text_features(**inputs)
        # Normalize embedding
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    return text_features.cpu().numpy()[0]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two normalized vectors."""
    return float(np.dot(a, b))


def index_images(image_paths: List[Path], conn: sqlite3.Connection, model, processor):
    """Index images by generating and storing their embeddings."""
    indexed = 0
    skipped = 0
    errors = []

    for image_path in tqdm(image_paths, desc="Indexing images"):
        try:
            # Get file modification time
            mtime = image_path.stat().st_mtime
            abs_path = str(image_path.absolute())

            # Check if already indexed with same mtime
            cursor = conn.execute(
                "SELECT mtime FROM embeddings WHERE file_path = ?",
                (abs_path,)
            )
            row = cursor.fetchone()

            if row and row[0] == mtime:
                skipped += 1
                continue

            # Generate embedding
            embedding = get_image_embedding(image_path, model, processor)
            embedding_blob = embedding.tobytes()

            # Store in database
            conn.execute(
                """
                INSERT OR REPLACE INTO embeddings (file_path, mtime, embedding)
                VALUES (?, ?, ?)
                """,
                (abs_path, mtime, embedding_blob)
            )
            indexed += 1

        except Exception as e:
            errors.append((image_path, str(e)))

    conn.commit()

    print(f"\nIndexed: {indexed} images", file=sys.stderr)
    print(f"Skipped: {skipped} (already up-to-date)", file=sys.stderr)

    if errors:
        print(f"\nErrors: {len(errors)}", file=sys.stderr)
        for path, error in errors:
            print(f"  {path}: {error}", file=sys.stderr)
        return 1

    return 0


def search_images(
    query: str,
    conn: sqlite3.Connection,
    model,
    processor,
    top_k: int = 10,
    scan_dir: Path = None
) -> List[Tuple[str, float]]:
    """
    Search for images matching the text query.

    Args:
        query: Text query to search for
        conn: Database connection
        model: CLIP model
        processor: CLIP processor
        top_k: Number of top results to return
        scan_dir: Optional directory to limit search to

    Returns:
        List of (file_path, similarity_score) tuples
    """
    # Generate text embedding
    print(f"Searching for: '{query}'", file=sys.stderr)
    text_embedding = get_text_embedding(query, model, processor)

    # Fetch all embeddings from database
    if scan_dir:
        scan_dir_abs = str(scan_dir.absolute())
        cursor = conn.execute(
            "SELECT file_path, embedding FROM embeddings WHERE file_path LIKE ?",
            (f"{scan_dir_abs}%",)
        )
    else:
        cursor = conn.execute("SELECT file_path, embedding FROM embeddings")

    results = []
    for file_path, embedding_blob in cursor:
        # Convert blob back to numpy array
        image_embedding = np.frombuffer(embedding_blob, dtype=np.float32)

        # Calculate similarity
        similarity = cosine_similarity(text_embedding, image_embedding)
        results.append((file_path, similarity))

    # Sort by similarity (highest first)
    results.sort(key=lambda x: x[1], reverse=True)

    return results[:top_k]


def discover_images(directory: Path) -> List[Path]:
    """Recursively find all image files in directory."""
    extensions = {'.jpg', '.jpeg', '.png'}
    images = []

    for ext in extensions:
        images.extend(directory.rglob(f'*{ext}'))
        images.extend(directory.rglob(f'*{ext.upper()}'))

    return images


def main():
    parser = argparse.ArgumentParser(
        description='Semantic image search using CLIP',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        '--index',
        action='store_true',
        help='Index images (generate and store embeddings)'
    )
    mode_group.add_argument(
        '--search',
        type=str,
        metavar='QUERY',
        help='Search for images matching text query'
    )

    # Image paths for indexing
    parser.add_argument(
        'image_paths',
        type=Path,
        nargs='*',
        help='Path(s) to image file(s) for indexing'
    )

    # Search options
    parser.add_argument(
        '--top-k',
        type=int,
        default=10,
        help='Number of top results to return (default: 10)'
    )
    parser.add_argument(
        '--scan',
        type=Path,
        metavar='DIR',
        help='Limit search to images in this directory'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )

    args = parser.parse_args()

    # Validate arguments
    if args.index:
        if not args.image_paths:
            parser.error("--index requires image paths")
        invalid_paths = [p for p in args.image_paths if not p.exists()]
        if invalid_paths:
            print(f"Error: Image file(s) not found:", file=sys.stderr)
            for p in invalid_paths:
                print(f"  {p}", file=sys.stderr)
            return 1

    if args.search and args.scan and not args.scan.exists():
        parser.error(f"Scan directory not found: {args.scan}")

    try:
        # Ensure database directory exists
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Connect to database
        conn = sqlite3.connect(DB_PATH)
        init_db(conn)

        # Load CLIP model
        model, processor = load_clip_model()

        if args.index:
            # Index mode
            return index_images(args.image_paths, conn, model, processor)

        else:
            # Search mode
            results = search_images(
                args.search,
                conn,
                model,
                processor,
                top_k=args.top_k,
                scan_dir=args.scan
            )

            if not results:
                print("No images found in database", file=sys.stderr)
                if args.scan:
                    print(f"Hint: Try indexing images in {args.scan} first", file=sys.stderr)
                else:
                    print("Hint: Index some images first with --index", file=sys.stderr)
                return 1

            # Output results
            if args.json:
                output = [
                    {"path": path, "similarity": float(score)}
                    for path, score in results
                ]
                print(json.dumps(output, indent=2))
            else:
                print(f"\nTop {len(results)} results:\n", file=sys.stderr)
                for i, (path, score) in enumerate(results, 1):
                    print(f"{i}. [{score:.3f}] {path}")

            return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == '__main__':
    sys.exit(main())
