#!/usr/bin/env python3
"""
Standalone CLI for rendering GLB screenshots via Blender.

Usage:
  python scripts/render_screenshots.py /path/to/model.glb [--output-dir ./out] [--resolution 1024]

Or via Blender directly (for testing the render script in isolation):
  blender -b --python scripts/render_screenshots.py -- /path/to/model.glb
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.renderer import render_screenshots


async def main() -> None:
    parser = argparse.ArgumentParser(description="Render multi-angle GLB screenshots")
    parser.add_argument("glb_path", help="Path to GLB file")
    parser.add_argument("--output-dir", default=str(SERVICE_ROOT / "data" / "renders"),
                        help="Output directory for renders")
    parser.add_argument("--resolution", type=int, default=1024, help="Render resolution")
    parser.add_argument("--blender", default=None, help="Path to Blender executable")
    args = parser.parse_args()

    glb = Path(args.glb_path).resolve()
    if not glb.is_file():
        print(f"Error: GLB file not found: {glb}", file=sys.stderr)
        sys.exit(1)

    blender_exec = args.blender
    if not blender_exec:
        from app.config import settings
        blender_exec = str(settings.blender_executable)

    def _progress(stage: str, pct: int) -> None:
        print(f"  [{pct:3d}%] {stage}")

    print(f"Rendering screenshots for: {glb}")
    print(f"  Resolution: {args.resolution}")
    print(f"  Blender: {blender_exec}")

    result = await render_screenshots(
        glb_path=str(glb),
        render_dir=Path(args.output_dir),
        blender_executable=blender_exec,
        resolution=args.resolution,
        progress_callback=_progress,
    )

    if result.success:
        print(f"\nSuccess: {result.num_angles} screenshots rendered in {result.render_elapsed:.1f}s")
        for img in result.screenshots:
            print(f"  {img.name}: {len(img.data_uri)} chars")
    else:
        print(f"\nFailed after {result.render_elapsed:.1f}s")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
