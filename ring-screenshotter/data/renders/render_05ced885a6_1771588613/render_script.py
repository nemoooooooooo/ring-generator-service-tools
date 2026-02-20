
import bpy
import os
import math
import sys
from mathutils import Vector

# ─── Configuration ───
GLB_PATH = r"/home/nimra/ring-generator-service-tools/ring-screenshotter/data/renders/_uploads/05abbd657d1d4d0ebb13b65a0a84b9fc_1.glb"
OUTPUT_DIR = r"/home/nimra/ring-generator-service-tools/ring-screenshotter/data/renders/render_05ced885a6_1771588613"
RESOLUTION = 1024
ANGLES = [{'name': 'front', 'pos': (0, 0, 5)}, {'name': 'back', 'pos': (0, 0, -5)}, {'name': 'left', 'pos': (-5, 0, 0)}, {'name': 'right', 'pos': (5, 0, 0)}, {'name': 'top', 'pos': (0, 5, 0)}, {'name': 'bottom', 'pos': (0, -5, 0)}, {'name': 'angle1', 'pos': (3, 3, 3)}, {'name': 'angle2', 'pos': (-3, 2, -3)}]

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

# ─── Import GLB ───
print(f"[SCREENSHOT] Importing GLB: {GLB_PATH}")
bpy.ops.import_scene.gltf(filepath=GLB_PATH)

# ─── Compute bounding box for normalization ───
# Matches Three.js: const scale = maxDim > 0 ? 2.5 / maxDim : 1;
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
center = (all_min + all_max) / 2.0

print(f"[SCREENSHOT] Bounding box: size={size}, max_dim={max_dim:.4f}, scale={scale_factor:.4f}")

# ─── Center and scale all mesh objects ───
# Matches Three.js: modelGroup.position.set(0,0,0); modelGroup.scale.setScalar(scale);
for obj in mesh_objects:
    obj.location -= center
    obj.scale *= scale_factor

bpy.context.view_layer.update()

# ─── Apply flat material matching createFlatMaterial() ───
# Original: MeshPhysicalMaterial(color: 0xd4d4d8, metalness: 0.85, roughness: 0.2,
#   reflectivity: 0.8, clearcoat: 0.15, clearcoatRoughness: 0.1,
#   envMapIntensity: 0.8, side: DoubleSide)
flat_mat = bpy.data.materials.new(name="FlatMetal")
flat_mat.use_nodes = True
nodes = flat_mat.node_tree.nodes
links = flat_mat.node_tree.links
nodes.clear()

output_node = nodes.new(type='ShaderNodeOutputMaterial')
output_node.location = (300, 0)

# 0xd4d4d8 = rgb(212, 212, 216) → linear: (0.646, 0.646, 0.663)
principled = nodes.new(type='ShaderNodeBsdfPrincipled')
principled.location = (0, 0)
principled.inputs['Base Color'].default_value = (0.646, 0.646, 0.663, 1.0)
principled.inputs['Metallic'].default_value = 0.85
principled.inputs['Roughness'].default_value = 0.2
principled.inputs['Coat Weight'].default_value = 0.15
principled.inputs['Coat Roughness'].default_value = 0.1
principled.inputs['Specular IOR Level'].default_value = 0.8

links.new(principled.outputs['BSDF'], output_node.inputs['Surface'])

for obj in mesh_objects:
    obj.data.materials.clear()
    obj.data.materials.append(flat_mat)

# ─── Studio lighting ───
# Matches captureValidationScreenshots() exactly:
# Key light: DirectionalLight(0xffffff, 2.5) at (5, 10, 5)
# Fill light: DirectionalLight(0xffffff, 1.0) at (-5, 5, -5)
# Rim light: DirectionalLight(0xffffff, 1.5) at (0, 5, -10)
# Ambient: AmbientLight(0xffffff, 0.4)

# Three.js intensity roughly maps to Blender energy with a scale factor.
# Three.js DirectionalLight intensity 1.0 ≈ Blender Sun energy ~3.0 for
# comparable visual output in EEVEE at this scene scale.
INTENSITY_SCALE = 3.0

def add_sun_light(name, energy, location, rotation_target):
    light_data = bpy.data.lights.new(name=name, type='SUN')
    light_data.energy = energy
    light_data.color = (1.0, 1.0, 1.0)
    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    bpy.context.collection.objects.link(light_obj)
    light_obj.location = Vector(location)
    direction = Vector(rotation_target) - Vector(location)
    light_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return light_obj

add_sun_light("KeyLight",  2.5 * INTENSITY_SCALE, (5, 10, 5),   (0, 0, 0))
add_sun_light("FillLight", 1.0 * INTENSITY_SCALE, (-5, 5, -5),  (0, 0, 0))
add_sun_light("RimLight",  1.5 * INTENSITY_SCALE, (0, 5, -10),  (0, 0, 0))

# Ambient light via world shader
world = bpy.data.worlds.new("ScreenshotWorld")
bpy.context.scene.world = world
world.use_nodes = True
wnodes = world.node_tree.nodes
wlinks = world.node_tree.links
wnodes.clear()
bg_node = wnodes.new(type='ShaderNodeBackground')
bg_node.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
bg_node.inputs['Strength'].default_value = 0.4
wo_node = wnodes.new(type='ShaderNodeOutputWorld')
wlinks.new(bg_node.outputs['Background'], wo_node.inputs['Surface'])

# ─── Set transparent background ───
bpy.context.scene.render.film_transparent = True

# ─── Camera setup ───
# Three.js uses PerspectiveCamera with default FOV ~50° (actually 75° in code, but
# the validation captures use standard lookAt). We use 50° to match the visual field
# that the perspective projection produces at these camera distances.
cam_data = bpy.data.cameras.new(name="ScreenshotCam")
cam_data.type = 'PERSP'
cam_data.lens_unit = 'FOV'
cam_data.angle = math.radians(50)
cam_data.clip_start = 0.1
cam_data.clip_end = 100.0

cam_obj = bpy.data.objects.new(name="ScreenshotCam", object_data=cam_data)
bpy.context.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

# ─── Render settings ───
scene = bpy.context.scene
# Blender 5.0 uses 'BLENDER_EEVEE'; older/newer versions may differ
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

# EEVEE quality — 32 samples is sufficient for validation screenshots
# (the original Three.js renderer uses real-time with no multisampling)
if hasattr(scene.eevee, 'taa_render_samples'):
    scene.eevee.taa_render_samples = 32
if hasattr(scene.eevee, 'use_gtao'):
    scene.eevee.use_gtao = True

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

    output_path = os.path.join(OUTPUT_DIR, f"{name}.png")
    scene.render.filepath = output_path

    print(f"[SCREENSHOT] Rendering {name} from {pos}")
    bpy.ops.render.render(write_still=True)

    if os.path.isfile(output_path):
        file_size = os.path.getsize(output_path)
        print(f"[SCREENSHOT] OK: {name}.png ({file_size} bytes)")
        rendered_count += 1
    else:
        print(f"[SCREENSHOT] FAILED: {name}.png not written")

print(f"[SCREENSHOT] COMPLETE: {rendered_count}/{len(ANGLES)} screenshots rendered")
