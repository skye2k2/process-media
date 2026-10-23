#!/usr/bin/env python3
"""
Analyze blur scores for original/-edited photo pairs to determine if editing
typically improves or degrades image sharpness.
"""
# eslint-disable no-console -- node scripts use the console

from pathlib import Path
import re
from analyze_photo_quality import calculate_blur_score


def find_edited_pairs(base_dir):
    """Find all original/-edited file pairs in a directory."""
    image_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.tiff', '.tif', '.bmp', '.gif'}
    all_photos = list(base_dir.rglob('*'))
    photos = [p for p in all_photos if p.suffix.lower() in image_extensions and p.is_file()]

    edited_pattern = re.compile(r'^(.+)-edited(\.[^.]+)$', re.IGNORECASE)
    pairs = []

    for photo in photos:
        match = edited_pattern.match(photo.name)
        if match:
            base_name = match.group(1)
            ext = match.group(2)
            # Look for original (exact name or common variations)
            original_candidates = [
                photo.parent / f'{base_name}{ext}',
                photo.parent / f'{base_name}{ext.upper()}',
                photo.parent / f'{base_name}{ext.lower()}',
            ]
            for orig in original_candidates:
                if orig.exists() and orig != photo:
                    pairs.append((orig, photo))
                    break

    return pairs


def analyze_pairs(pairs):
    """Calculate blur scores for each pair and determine improvement."""
    results = []
    for i, (orig, edited) in enumerate(pairs):
        if i % 10 == 0:
            print(f"  Analyzing pair {i + 1}/{len(pairs)}...", end='\r')
        try:
            orig_blur = calculate_blur_score(orig)
            edited_blur = calculate_blur_score(edited)
            if orig_blur is not None and edited_blur is not None:
                results.append({
                    'original': orig,
                    'edited': edited,
                    'orig_blur': orig_blur,
                    'edited_blur': edited_blur,
                    'diff': edited_blur - orig_blur,
                    'improved': edited_blur > orig_blur
                })
        except Exception:
            pass
    print()  # Clear the progress line
    return results


def summarize_category(category, name):
    """Print summary statistics for a category of pairs."""
    if not category:
        print(f'{name}: No pairs found')
        return

    improved = sum(1 for r in category if r['improved'])
    avg_diff = sum(r['diff'] for r in category) / len(category)
    print(f'{name} ({len(category)} pairs):')
    print(f'  Improved: {improved}/{len(category)} ({100 * improved / len(category):.0f}%)')
    print(f'  Avg blur change: {avg_diff:+.1f} (positive = sharper edited)')

    # Show distribution
    big_improve = sum(1 for r in category if r['diff'] > 10)
    small_improve = sum(1 for r in category if 0 < r['diff'] <= 10)
    no_change = sum(1 for r in category if abs(r['diff']) <= 2)
    small_worse = sum(1 for r in category if -10 <= r['diff'] < 0)
    big_worse = sum(1 for r in category if r['diff'] < -10)
    print(f'  Distribution: +10+ ({big_improve}), +1-10 ({small_improve}), ~same ({no_change}), -1-10 ({small_worse}), -10+ worse ({big_worse})')
    print()


def main():
    base_dir = Path('Organized_Photos')
    print(f'Scanning {base_dir} for -edited pairs...')

    pairs = find_edited_pairs(base_dir)
    print(f'Found {len(pairs)} original/-edited pairs')
    print()

    print('Analyzing blur scores...')
    results = analyze_pairs(pairs)
    print(f'Successfully analyzed {len(results)} pairs')
    print()

    # Categorize by original sharpness
    very_blurry = [r for r in results if r['orig_blur'] < 30]
    blurry = [r for r in results if 30 <= r['orig_blur'] < 60]
    soft = [r for r in results if 60 <= r['orig_blur'] < 100]
    sharp = [r for r in results if r['orig_blur'] >= 100]

    summarize_category(very_blurry, 'Very Blurry (blur < 30)')
    summarize_category(blurry, 'Blurry (30-60)')
    summarize_category(soft, 'Slightly Soft (60-100)')
    summarize_category(sharp, 'Sharp (100+)')

    # Overall stats
    print('=' * 50)
    if results:
        improved_total = sum(1 for r in results if r['improved'])
        avg_diff_total = sum(r['diff'] for r in results) / len(results)
        print(f'OVERALL ({len(results)} pairs):')
        print(f'  Edited improved sharpness: {improved_total}/{len(results)} ({100 * improved_total / len(results):.0f}%)')
        print(f'  Avg blur change: {avg_diff_total:+.1f}')
        print()

        # Show examples where edited is worse
        print('=' * 50)
        print('Examples where edited is WORSE (blur decreased):')
        worse = sorted([r for r in results if r['diff'] < -5], key=lambda x: x['diff'])[:5]
        for r in worse:
            print(f'  {r["original"].name}')
            print(f'    Original: {r["orig_blur"]:.1f} -> Edited: {r["edited_blur"]:.1f} (diff: {r["diff"]:+.1f})')

        print()
        print('Examples where edited is BETTER (blur increased):')
        better = sorted([r for r in results if r['diff'] > 5], key=lambda x: -x['diff'])[:5]
        for r in better:
            print(f'  {r["original"].name}')
            print(f'    Original: {r["orig_blur"]:.1f} -> Edited: {r["edited_blur"]:.1f} (diff: {r["diff"]:+.1f})')


if __name__ == '__main__':
    main()
