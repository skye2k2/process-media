#!/usr/bin/env python3
"""
Verify that remaining files in TAKEOUT_DATA are duplicates of organized files.
Checks by filename and optionally by file size to confirm they're truly duplicates.
"""

from collections import defaultdict
from pathlib import Path

from media_utils import MEDIA_EXTENSIONS

SCRIPT_DIR = Path(__file__).parent
TAKEOUT_DIR = SCRIPT_DIR / "TAKEOUT_DATA"
ORGANIZED_PHOTOS = SCRIPT_DIR / "Organized_Photos"
ORGANIZED_VIDEOS = SCRIPT_DIR / "Organized_Videos"


def build_organized_index():
    """
    Build an index of all organized files by filename.
    Returns dict: {filename: [(path, size), ...]}
    """
    print("Building index of organized files...")
    index = defaultdict(list)

    for base_dir in [ORGANIZED_PHOTOS, ORGANIZED_VIDEOS]:
        if not base_dir.exists():
            continue

        for ext in MEDIA_EXTENSIONS:
            for file_path in base_dir.rglob(f"*{ext}"):
                if file_path.is_file():
                    filename = file_path.name
                    file_size = file_path.stat().st_size
                    index[filename].append((file_path, file_size))

    print(f"  Indexed {sum(len(v) for v in index.values())} organized files with {len(index)} unique names\n")
    return index


def main():
    print("Verifying remaining files in TAKEOUT_DATA...")
    print("=" * 80)

    # Build index of organized files first (much faster than repeated rglob)
    organized_index = build_organized_index()

    # Find all remaining media files
    remaining_files = []
    for ext in MEDIA_EXTENSIONS:
        remaining_files.extend(TAKEOUT_DIR.rglob(f"*{ext}"))

    print(f"Found {len(remaining_files)} remaining media files in TAKEOUT_DATA\n")

    if not remaining_files:
        print("✅ No files remaining - all processed successfully!")
        return

    # Categorize files
    duplicates = []  # Files found in organized dirs with matching size
    name_match_size_diff = []  # Same name but different size
    not_found = []  # Not found in organized dirs at all

    print("Checking each file...\n")
    for i, file_path in enumerate(remaining_files, 1):
        if i % 50 == 0:
            print(f"  Checked {i}/{len(remaining_files)} files...")

        filename = file_path.name
        file_size = file_path.stat().st_size

        # Look up in index
        organized_versions = organized_index.get(filename, [])

        # Check for exact size match
        size_matches = [path for path, size in organized_versions if size == file_size]

        if size_matches:
            duplicates.append({
                'source': file_path,
                'size': file_size,
                'matches': size_matches
            })
        elif organized_versions:
            # Name matches but different size
            name_match_size_diff.append({
                'source': file_path,
                'size': file_size,
                'matches': [path for path, _ in organized_versions]
            })
        else:
            not_found.append({
                'source': file_path,
                'size': file_size
            })

    # Print summary
    print("\n" + "=" * 80)
    print("VERIFICATION RESULTS")
    print("=" * 80)
    print(f"\nTotal remaining files: {len(remaining_files)}")
    print(f"✅ Confirmed duplicates (same name & size): {len(duplicates)}")
    print(f"⚠️  Same name, different size: {len(name_match_size_diff)}")
    print(f"❌ Not found in organized directories: {len(not_found)}")

    # Show details for non-duplicates
    if name_match_size_diff:
        print("\n" + "=" * 80)
        print("⚠️  FILES WITH SAME NAME BUT DIFFERENT SIZE")
        print("=" * 80)
        print("These might be different versions or need investigation:")
        for item in name_match_size_diff[:10]:  # Show first 10
            print(f"\n  Source: {item['source'].name}")
            print(f"    Path: {item['source']}")
            print(f"    Size: {item['size']:,} bytes")
            print(f"    Organized versions:")
            for match in item['matches']:
                match_size = match.stat().st_size
                print(f"      - {match.relative_to(SCRIPT_DIR)} ({match_size:,} bytes)")
        if len(name_match_size_diff) > 10:
            print(f"\n  ... and {len(name_match_size_diff) - 10} more")

    if not_found:
        print("\n" + "=" * 80)
        print("❌ FILES NOT FOUND IN ORGANIZED DIRECTORIES")
        print("=" * 80)
        print("These files were NOT processed and may need attention:")
        for item in not_found[:20]:  # Show first 20
            print(f"\n  {item['source'].name}")
            print(f"    Path: {item['source']}")
            print(f"    Size: {item['size']:,} bytes")
        if len(not_found) > 20:
            print(f"\n  ... and {len(not_found) - 20} more")

    # Overall conclusion
    print("\n" + "=" * 80)
    print("CONCLUSION")
    print("=" * 80)

    if len(duplicates) == len(remaining_files):
        print("\n✅ ALL remaining files are confirmed duplicates!")
        print("   It is safe to delete everything in TAKEOUT_DATA/")
    elif not_found:
        print(f"\n⚠️  WARNING: {len(not_found)} files were not processed!")
        print("   DO NOT delete TAKEOUT_DATA until these are investigated.")
        print("   These files may have been skipped due to errors.")
    elif name_match_size_diff:
        print(f"\n⚠️  CAUTION: {len(name_match_size_diff)} files have different sizes than organized versions.")
        print("   Review these before deleting TAKEOUT_DATA.")
    else:
        print("\n✅ Most files are duplicates, but review any warnings above.")

    print()


if __name__ == "__main__":
    main()
