# AGENTS.md

Guidance for AI coding assistants (GitHub Copilot, Anthropic Claude Code, etc.) working in this repository.

For project architecture, definitions, scope, and associated commands, see [README.md](README.md).

---

## Functional Coding Standards

- Follow prominent established engineering best practices: the Single Responsibility Principle, the Liskov Substitution Principle, Don't Repeat Yourself, Keep it Simple, Stupid, and the Principle of Least Knowledge.
- Pay heed to static analysis linting warnings, especially those related to potential undefined values, type mismatches, and unreachable code, and additionally, complexity. When following the Single Responsibility Principle, complexity is often reduced naturally.
- In general, avoid using ternary statements. Using them for simple variable declaration is fine, but as soon as significant logic would be added, we prefer if, then, else assignments, with comments.
- Optimize code for clarity and re-use, avoiding overly cute single-line solutions, niche understanding of a language's implementation, and unnecessary cognitive overhead.
- Pay attention to significant performance implications of code, especially in loops or frequently called functions or common flows, but do not micro-optimize.

---

## Development Workflow (to minimize regressions):

- Check `requirements.txt` and package imports before making changes
- **Always invoke scripts as `.venv/bin/python script.py`, never bare `python3`.** Dependencies are pinned in a project-local `.venv/` (see README "Setup"). Bare `python3` resolves to the Homebrew interpreter, which has no OpenCV — and `photo_triage.py` exits immediately when OpenCV is missing, so the whole review workflow appears "broken" for an environment reason rather than a code reason. If you see `WARNING: OpenCV not installed`, you used the wrong interpreter.
- **Read existing code thoroughly** - Before modifying any code, read through ALL functions and code paths that will be affected by the change. Trace the full execution flow to understand side effects. Static analysis linting warnings and errors are often very insightful as to what may have been missed, so check them first, especially applying auto-fixes.
- **Test-Driven Development preference** - When starting new projects or major features or beginning rewrites, suggest writing/updating tests first. For existing code without tests, offer to create test coverage before making risky changes. Tests really do prevent many kinds of avoidable regressions.
- **Ask clarifying questions up front** - When requirements are ambiguous or incomplete, ask specific questions before implementing. Don't guess and hope we will correct you after seeing the broken result.
- **Make incremental changes** - Limit each change to ONE logical modification. If adding a feature requires touching multiple functions, explain the plan first and consider breaking it into smaller steps. Don't bundle multiple features into one implementation.
- **Maintain a mental requirements checklist** - When adding new functionality, explicitly verify that existing requirements still hold. For complex systems, list out the key constraints before making changes.
- **Review code before submitting** - Check for simple errors (undefined variables, wrong parameter names, type mismatches) before presenting code. These should be caught before submission, not after execution.
- **Acknowledge complexity honestly** - If a change touches a complex multi-pass system or has many edge cases, say so and recommend extra caution or testing rather than assuming it'll work.

---

## Code Style

- Use modern Python features (Python 3.11+)
- Follow PEP 8 style guidelines
- Use f-strings for string formatting
- Prefer functional programming patterns where appropriate
- Maintain consistent naming: PascalCase for classes, snake_case for functions/variables
- Reuse existing utilities from `media_utils.py` and shared modules
- Keep curly braces for single-line blocks (not Python-specific, but applies to any embedded shell scripts)
- Add docstrings for all functions with descriptions justifying existence

---

### Naming Conventions

- Attempt to be reasonably self-documenting with variable names, with a max character length of about 20 characters. Avoid single-character variables, with the sole exception of throwaway iterable indices.
- Use PascalCase for class names.
- Use snake_case for functions, variables, and methods.
- Use ALL_CAPS (screaming snake case) for constants.

---

## Terminal Command Safety (VS Code crash prevention)

- **VS Code can crash from terminal output flooding.** Certain patterns overwhelm the integrated terminal and cause editor instability or crashes
- **Always limit output when testing unfamiliar scripts** - Redirect to a file (`> .TMP_output.log 2>&1`) when running scripts that might produce substantial output
- **Avoid rapid progress indicators** - Progress bars using carriage returns (`\r`) or ANSI escape codes can create extremely long logical "lines" that destabilize the terminal. Prefer simple periodic line-based progress (e.g., "Processed 100/500 files...")
- **Test with small subsets first** - Before running a script on hundreds of files, test on 5-10 files to verify output behavior

---

## Performance and Long-Running Processes

- **Assume large data sets** - This project processes thousands of media files. Design for scale from the start.
- **Identify single-threaded bottlenecks upfront** - Use multiprocessing/threading for file operations, external tool calls (exiftool, ffmpeg, ffprobe)
- **Prefer batching over iteration** - exiftool supports batch operations. Use them.
- **Parallelize CPU-bound work** - Use ProcessPoolExecutor/ThreadPoolExecutor with max workers ≤10
- **Built-in progress logging is mandatory** - Any long-running operation must log progress at regular intervals
- **Cache expensive computations** - The project uses `.duration_cache.json` and `.analysis_cache.json`. Respect these patterns.

---

## Debugging

- When debugging troublesome code, provide summaries of the paths being proven or disproven
- Provide more verbose (but concise) logging by default, so that if something goes wrong it is much more obvious, instead of needing to add and then remove logging throughout the entire process

---

## Documentation

- When making functional code changes, attempt to keep any README documentation, especially about usage or execution order, up to date.
- Add docstrings for functions with descriptions justifying existence
- Include inline comments for confusing or error-prone code segments

---

## Python Scripts

When generating Python scripts, follow the module pattern:

```python
#!/usr/bin/env python3
"""
Script description here.
"""

import sys
# other imports...

def main():
    """Main entry point."""
    pass

if __name__ == "__main__":
    main()
```

---

## Repository-Specific Notes

### Media Processing Workflows

This project handles four distinct workflows:
1. **Google Takeout Processing** (`workflow_takeout.py`) - Organizes exported photos/videos with JSON metadata
2. **Archive Processing** (`workflow_archive.py`) - Organizes raw media from NAS/phone backups
3. **Video Conversion** (`workflow_camcorder.py`) - Converts legacy codecs (H.264, MPEG-2) to H.265
4. **Reprocessing** (`workflow_reprocess.py`) - Menu-driven maintenance for already-organized media

### Key Architecture Patterns

- **Unified input directory**: All workflows use `TO_PROCESS/` for input
- **Shared output directories**: `Organized_Photos/` and `Organized_Videos/`
- **Performance optimizations**:
  - In-memory file indexing (`build_file_index.py`) for O(1) duplicate detection
  - Duration caching (`.duration_cache.json`) for video files
  - Analysis caching (`.analysis_cache.json`) for photo quality metrics
- **Metadata handling**: Project prefers writing EXIF data into files and removing JSON sidecars
- **Naming convention**: Organized files use `YYYYMMDD_HHMMSS` format; camcorder files add `_CAM` suffix

### Critical Dependencies

- **exiftool**: Required for all metadata operations (install: `brew install exiftool`)
- **ffmpeg/ffprobe**: Required for video operations (install: `brew install ffmpeg`)
- **opencv**: Required for photo quality analysis (install: `brew install opencv`, optional)

### Testing Approach

- Always test with small subsets (5-10 files) before processing thousands
- Use `--dry-run` flags where available
- Redirect output for scripts that process many files: `python3 script.py > .TMP_output.log 2>&1`

### Known Quirks

- **Pixel Motion Photos**: Dual-stream MP4 files that QuickLook can't play. Use `motion_photo_extract.py` to fix.
- **Google Takeout fragmentation**: JSON metadata in project folders, media files in dated folders. Use `fix_fragmented_metadata.py` to reunite.
- **Bloated re-encodes**: Google Takeout sometimes creates larger versions. Archive workflow detects and replaces.
- **Extension mismatches**: Files may have wrong extensions (WebP saved as .jpg). Organizers auto-detect via magic bytes.

### Common Tasks

- **Before making changes**: Run on a test subset in a separate `TO_PROCESS/test/` directory
- **After significant changes**: Verify with `check_nas_archive.py` to ensure no files were lost
- **When adding features**: Consider impact on all four workflows, not just one

---
