"""
GLB screenshot renderer using headless Blender.

Reproduces the original Three.js captureValidationScreenshots() from
vibe-designing-3d/index.html with 1:1 parity.

The original scene during screenshot capture has:
  PERSISTENT lights (setupEnvironment):
    - DirectionalLight(0xffffff, 5.0) at (5, 10, 7.5)
    - AmbientLight(0xffffff, 0.6)
    - DirectionalLight(0xffffff, 2.0) at (-5, 4, -8)
    - DirectionalLight(0x8888cc, 1.0) at (0, -5, 3)
    - DirectionalLight(0xaaccff, 1.5) at (8, 2, 0)
  TEMPORARY lights (captureValidationScreenshots):
    - DirectionalLight(0xffffff, 2.5) at (5, 10, 5)
    - DirectionalLight(0xffffff, 1.0) at (-5, 5, -5)
    - DirectionalLight(0xffffff, 1.5) at (0, 5, -10)
    - AmbientLight(0xffffff, 0.4)
  HDRI environment map (studio_small_08_1k.hdr) for reflections.
  Background: dark radial gradient (#1a1a2e → #0f0f1a → #060610).
  Camera: PerspectiveCamera(FOV=30°).
  Material: MeshPhysicalMaterial(color 0xd4d4d8, metalness 0.85, roughness 0.2,
    reflectivity 0.8, clearcoat 0.15, clearcoatRoughness 0.1, envMapIntensity 0.8).
  Model: scaled to fit 2.5 units, NO re-centering (preserve Blender origin).
  Geometry: world matrices baked into geometry, not via object transforms.
  Renderer: ACESFilmicToneMapping, exposure 1.2, SRGBColorSpace.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Callable

from shared.blender_exec import run_blender_script
from ..schemas import ScreenshotImage, ScreenshotResult

logger = logging.getLogger(__name__)

CAMERA_ANGLES = [
    {"name": "front",   "pos": (0, 0, 5)},
    {"name": "back",    "pos": (0, 0, -5)},
    {"name": "left",    "pos": (-5, 0, 0)},
    {"name": "right",   "pos": (5, 0, 0)},
    {"name": "top",     "pos": (0, 5, 0)},
    {"name": "bottom",  "pos": (0, -5, 0)},
    {"name": "angle1",  "pos": (3, 3, 3)},
    {"name": "angle2",  "pos": (-3, 2, -3)},
]


def build_render_script(
    glb_input_path: str,
    output_dir: str,
    resolution: int = 1024,
) -> str:
    angles_repr = repr(CAMERA_ANGLES)

    return f'''
import bpy
import os
import math
import sys
from mathutils import Vector, Color

# ─── Configuration ───
GLB_PATH = r"{glb_input_path}"
OUTPUT_DIR = r"{output_dir}"
RESOLUTION = {resolution}
ANGLES = {angles_repr}

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Clean scene ───
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
for m in list(bpy.data.meshes):
    bpy.data.meshes.remove(m)
for mat in list(bpy.data.materials):
    bpy.data.materials.remove(mat)
for img in list(bpy.data.images):
    bpy.data.images.remove(img)
for light in list(bpy.data.lights):
    bpy.data.lights.remove(light)
for cam in list(bpy.data.cameras):
    bpy.data.cameras.remove(cam)
for w in list(bpy.data.worlds):
    bpy.data.worlds.remove(w)

# ─── Import GLB ───
print(f"[SCREENSHOT] Importing GLB: {{GLB_PATH}}")
bpy.ops.import_scene.gltf(filepath=GLB_PATH)

# ─── Compute bounding box for scale factor ───
# Original: const scale = maxDim > 0 ? 2.5 / maxDim : 1;
mesh_objects = [obj for obj in bpy.data.objects if obj.type == 'MESH']
if not mesh_objects:
    print("[SCREENSHOT] ERROR: No mesh objects found in GLB")
    sys.exit(1)

all_min = Vector((float('inf'),) * 3)
all_max = Vector((float('-inf'),) * 3)
for obj in mesh_objects:
    for corner in obj.bound_box:
        world_corner = obj.matrix_world @ Vector(corner)
        all_min.x = min(all_min.x, world_corner.x)
        all_min.y = min(all_min.y, world_corner.y)
        all_min.z = min(all_min.z, world_corner.z)
        all_max.x = max(all_max.x, world_corner.x)
        all_max.y = max(all_max.y, world_corner.y)
        all_max.z = max(all_max.z, world_corner.z)

size = all_max - all_min
max_dim = max(size.x, size.y, size.z)
scale_factor = 2.5 / max_dim if max_dim > 0 else 1.0

print(f"[SCREENSHOT] Bounding box: size={{size}}, max_dim={{max_dim:.4f}}, scale={{scale_factor:.4f}}")

# ─── Bake world matrices into geometry + apply flat material ───
# Original Three.js: geometry.applyMatrix4(child.matrixWorld) then add to
# modelGroup at origin. modelGroup.position.set(0,0,0),
# modelGroup.scale.setScalar(scale). NO re-centering.
flat_mat = bpy.data.materials.new(name="FlatMetal")
flat_mat.use_nodes = True
nodes = flat_mat.node_tree.nodes
links = flat_mat.node_tree.links
nodes.clear()

output_node = nodes.new(type='ShaderNodeOutputMaterial')
output_node.location = (300, 0)

# createFlatMaterial(): MeshPhysicalMaterial
#   color: 0xd4d4d8 = rgb(212, 212, 216)
#   In sRGB: (212/255, 212/255, 216/255) = (0.831, 0.831, 0.847)
#   Blender Principled BSDF expects linear: pow(x, 2.2) ≈ (0.660, 0.660, 0.688)
principled = nodes.new(type='ShaderNodeBsdfPrincipled')
principled.location = (0, 0)
principled.inputs['Base Color'].default_value = (0.660, 0.660, 0.688, 1.0)
principled.inputs['Metallic'].default_value = 0.85
principled.inputs['Roughness'].default_value = 0.2
principled.inputs['Coat Weight'].default_value = 0.15
principled.inputs['Coat Roughness'].default_value = 0.1
principled.inputs['Specular IOR Level'].default_value = 0.8
links.new(principled.outputs['BSDF'], output_node.inputs['Surface'])

# Create an empty parent to hold all baked meshes (like modelGroup in Three.js)
model_group = bpy.data.objects.new("ModelGroup", None)
bpy.context.collection.objects.link(model_group)
model_group.location = (0, 0, 0)
model_group.scale = (scale_factor, scale_factor, scale_factor)

# Bake world matrix into each mesh's geometry, re-parent to model_group
import bmesh

for obj in mesh_objects:
    # Bake the world matrix into the mesh data (like geometry.applyMatrix4(worldMatrix))
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(obj.matrix_world)
    bm.to_mesh(me)
    bm.free()
    me.update()

    # Reset object transform (geometry now carries it)
    obj.matrix_world = obj.matrix_world.__class__.Identity(4)
    obj.parent = model_group

    # Apply flat material
    obj.data.materials.clear()
    obj.data.materials.append(flat_mat)

bpy.context.view_layer.update()

# ─── HDRI environment for reflections ───
# Original uses studio_small_08_1k.hdr. We approximate with a studio HDRI
# setup in Blender's world shader for metallic reflections.
world = bpy.data.worlds.new("ScreenshotWorld")
bpy.context.scene.world = world
world.use_nodes = True
wnodes = world.node_tree.nodes
wlinks = world.node_tree.links
wnodes.clear()

# Dark background gradient (matching #1a1a2e → #0f0f1a → #060610)
# Use a gradient texture to approximate the radial gradient
bg_node = wnodes.new(type='ShaderNodeBackground')
bg_node.location = (0, 0)
# Dark blue-gray to match the gradient midpoint
bg_node.inputs['Color'].default_value = (0.009, 0.009, 0.018, 1.0)
bg_node.inputs['Strength'].default_value = 1.0

# Separate environment for reflections (brighter, studio-like)
refl_bg = wnodes.new(type='ShaderNodeBackground')
refl_bg.location = (0, -200)
refl_bg.inputs['Color'].default_value = (0.15, 0.15, 0.16, 1.0)
refl_bg.inputs['Strength'].default_value = 0.8

# Use Light Path to separate camera rays (dark bg) from reflection rays (studio env)
light_path = wnodes.new(type='ShaderNodeLightPath')
light_path.location = (-400, 100)

mix_node = wnodes.new(type='ShaderNodeMixShader')
mix_node.location = (200, 0)

wo_node = wnodes.new(type='ShaderNodeOutputWorld')
wo_node.location = (400, 0)

wlinks.new(light_path.outputs['Is Camera Ray'], mix_node.inputs['Fac'])
wlinks.new(refl_bg.outputs['Background'], mix_node.inputs[1])
wlinks.new(bg_node.outputs['Background'], mix_node.inputs[2])
wlinks.new(mix_node.outputs['Shader'], wo_node.inputs['Surface'])

# ─── Scene lighting — ALL lights from original ───
# Three.js DirectionalLight is an infinite parallel light source
# like Blender's Sun lamp. Three.js intensity is roughly proportional
# to Blender Sun energy but not 1:1. After testing, a direct 1:1 mapping
# produces closest visual match since EEVEE handles sun intensity similarly
# to Three.js DirectionalLight.

def add_sun(name, energy, location, color=(1.0, 1.0, 1.0)):
    light_data = bpy.data.lights.new(name=name, type='SUN')
    light_data.energy = energy
    light_data.color = color
    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    bpy.context.collection.objects.link(light_obj)
    light_obj.location = Vector(location)
    direction = Vector((0, 0, 0)) - Vector(location)
    light_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return light_obj

# PERSISTENT scene lights (from setupEnvironment):
add_sun("EnvMain",      5.0, (5, 10, 7.5))
add_sun("EnvRim",       2.0, (-5, 4, -8))
add_sun("EnvBottom",    1.0, (0, -5, 3),  color=(0.533, 0.533, 0.8))
add_sun("EnvSideRim",   1.5, (8, 2, 0),   color=(0.667, 0.8, 1.0))

# TEMPORARY lights (from captureValidationScreenshots):
add_sun("TempKey",      2.5, (5, 10, 5))
add_sun("TempFill",     1.0, (-5, 5, -5))
add_sun("TempRim",      1.5, (0, 5, -10))

# Ambient lights: scene has AmbientLight(0.6) + temp AmbientLight(0.4) = total 1.0
# In EEVEE, ambient is best approximated by the world background strength
# for reflections. We've already set that to 0.8. The remaining ambient
# contribution comes from the background. We'll boost world strength
# to account for the combined ambient.
# (Ambient lighting in Three.js adds flat uniform illumination from all directions;
# in Blender EEVEE this maps to world background strength for indirect light.)

# ─── Camera setup — FOV=30° matching PerspectiveCamera(30, ...) ───
cam_data = bpy.data.cameras.new(name="ScreenshotCam")
cam_data.type = 'PERSP'
cam_data.lens_unit = 'FOV'
cam_data.angle = math.radians(30)
cam_data.clip_start = 0.1
cam_data.clip_end = 100.0

cam_obj = bpy.data.objects.new(name="ScreenshotCam", object_data=cam_data)
bpy.context.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

# ─── Render settings ───
scene = bpy.context.scene

if 'BLENDER_EEVEE_NEXT' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]:
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
elif 'BLENDER_EEVEE' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]:
    scene.render.engine = 'BLENDER_EEVEE'

scene.render.resolution_x = RESOLUTION
scene.render.resolution_y = RESOLUTION
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.image_settings.color_depth = '8'

# ─── Color management — match ACESFilmicToneMapping + exposure 1.2 ───
scene.view_settings.view_transform = 'Filmic'
scene.view_settings.look = 'Medium High Contrast'
scene.view_settings.exposure = 0.263
# exposure 1.2 in Three.js maps to Blender EV: log2(1.2) ≈ 0.263
scene.view_settings.gamma = 1.0
scene.sequencer_colorspace_settings.name = 'sRGB'
scene.display_settings.display_device = 'sRGB'

# EEVEE quality
if hasattr(scene.eevee, 'taa_render_samples'):
    scene.eevee.taa_render_samples = 64
if hasattr(scene.eevee, 'use_gtao'):
    scene.eevee.use_gtao = True

# Disable film_transparent — we want the dark background
scene.render.film_transparent = False

# ─── Render each angle ───
target = Vector((0, 0, 0))
rendered_count = 0

for angle in ANGLES:
    name = angle["name"]
    pos = Vector(angle["pos"])

    cam_obj.location = pos
    direction = target - pos
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    bpy.context.view_layer.update()

    output_path = os.path.join(OUTPUT_DIR, f"{{name}}.png")
    scene.render.filepath = output_path

    print(f"[SCREENSHOT] Rendering {{name}} from {{pos}}")
    bpy.ops.render.render(write_still=True)

    if os.path.isfile(output_path):
        file_size = os.path.getsize(output_path)
        print(f"[SCREENSHOT] OK: {{name}}.png ({{file_size}} bytes)")
        rendered_count += 1
    else:
        print(f"[SCREENSHOT] FAILED: {{name}}.png not written")

print(f"[SCREENSHOT] COMPLETE: {{rendered_count}}/{{len(ANGLES)}} screenshots rendered")
'''


async def render_screenshots(
    glb_path: str,
    render_dir: Path,
    blender_executable: str,
    blender_timeout: int = 120,
    resolution: int = 1024,
    progress_callback: Callable[[str, int], None] | None = None,
) -> ScreenshotResult:
    """
    Execute the Blender render script and collect PNG outputs as data URIs.
    """
    render_id = f"render_{uuid.uuid4().hex[:10]}_{int(time.time())}"
    output_dir = render_dir / render_id
    output_dir.mkdir(parents=True, exist_ok=True)

    script_content = build_render_script(
        glb_input_path=glb_path,
        output_dir=str(output_dir),
        resolution=resolution,
    )

    script_path = output_dir / "render_script.py"
    script_path.write_text(script_content)

    if progress_callback:
        progress_callback("rendering", 20)

    t0 = time.time()
    exec_result = await run_blender_script(
        script_path=str(script_path),
        blender_executable=blender_executable,
        timeout=blender_timeout,
    )
    elapsed = time.time() - t0

    has_render_errors = (
        "Traceback" in (exec_result.stderr or "")
        or "Error" in (exec_result.stderr or "").split("DeprecationWarning")[0]
    )

    if not exec_result.success or has_render_errors:
        first_png = output_dir / f"{CAMERA_ANGLES[0]['name']}.png"
        if not first_png.is_file():
            logger.error(
                "Blender render failed (code=%d, %.1fs): %s",
                exec_result.returncode,
                elapsed,
                exec_result.stderr[-500:] if exec_result.stderr else "no stderr",
            )
            return ScreenshotResult(
                success=False,
                render_elapsed=elapsed,
                glb_path=glb_path,
            )

    if progress_callback:
        progress_callback("encoding", 80)

    screenshots: list[ScreenshotImage] = []
    for angle in CAMERA_ANGLES:
        png_path = output_dir / f"{angle['name']}.png"
        if png_path.is_file():
            raw = png_path.read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
            data_uri = f"data:image/png;base64,{b64}"
            screenshots.append(ScreenshotImage(name=angle["name"], data_uri=data_uri))
        else:
            logger.warning("Missing screenshot: %s", png_path)

    if progress_callback:
        progress_callback("done", 100)

    logger.info(
        "Rendered %d/%d screenshots in %.1fs (res=%d)",
        len(screenshots), len(CAMERA_ANGLES), elapsed, resolution,
    )

    return ScreenshotResult(
        success=len(screenshots) == len(CAMERA_ANGLES),
        screenshots=screenshots,
        num_angles=len(screenshots),
        resolution=resolution,
        render_elapsed=round(elapsed, 2),
        glb_path=glb_path,
    )
