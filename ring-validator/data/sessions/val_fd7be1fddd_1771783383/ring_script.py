
# ========================= AUTO SCENE CLEAR =========================
import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
for m in list(bpy.data.meshes):
    bpy.data.meshes.remove(m)
for mat in list(bpy.data.materials):
    bpy.data.materials.remove(mat)
print("[PIPELINE] Scene cleared")
# ========================= END SCENE CLEAR =========================

import bpy
import bmesh
from math import sin, cos, pi, radians, sqrt

# ===== AUTO-INJECTED SAFETY =====
def _safe_face(_bm_arg, _verts_arg):
    try:
        if len(_verts_arg) < 3:
            return None
        if len(set(id(v) for v in _verts_arg)) != len(_verts_arg):
            return None
        return _bm_arg.faces.new(_verts_arg)
    except (ValueError, IndexError, TypeError):
        return None
# ===== END SAFETY =====


def build():
    # ─── SCENE SETUP ─────────────────────────────────────────────────────
    # Clear scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)
    
    # Create collection
    ring_col = bpy.data.collections.new("Ring_Assembly")
    bpy.context.scene.collection.children.link(ring_col)

    # ─── DIMENSIONS (Real World Scale: Meters) ───────────────────────────
    # US Size 7 approx
    ring_size_inner_diameter = 0.0173  # 17.3mm
    inner_radius = ring_size_inner_diameter / 2
    
    band_width = 0.0035      # 3.5mm wide
    band_thickness = 0.0018  # 1.8mm thick
    
    # Major radius (center of the metal profile)
    major_radius = inner_radius + (band_thickness / 2)

    # Resolution
    n_circ = 80   # Circumferential segments
    n_prof = 24   # Profile cross-section segments

    # ─── BUILDER: LUXURY COMFORT-FIT BAND ────────────────────────────────
    bm = bmesh.new()
    
    # Generate the torus with a D-Profile (Comfort Fit)
    # D-Profile: Flat/slightly curved inside, domed outside
    
    vert_grid = []  # To store verts for face creation
    
    for i in range(n_circ):
        theta = 2 * pi * i / n_circ
        
        # Matrix basis vectors for the profile plane at angle theta
        # Radial vector (outward from ring center)
        r_vec = (cos(theta), sin(theta), 0)
        # Tangent vector is not needed for position, just Z (up)
        
        profile_verts = []
        
        for j in range(n_prof):
            phi = 2 * pi * j / n_prof
            
            # Parametric Ellipse for cross-section
            # y_local: width direction (Z axis in Blender world for the profile ring?) 
            # Actually, let's align:
            # Ring lies on XY plane.
            # Z is up (thickness direction? No, usually Z is up for ring viewing).
            # The prompt defines Z as UP (face of ring). Y is finger axis.
            # Let's follow Standard Orientation:
            # Ring bore is along Y axis. Ring "face" is Z axis.
            # theta rotates around Y axis.
            
            # Re-orienting to "Standing Ring" (Section B of rules):
            # Bore along Y axis.
            # Sweep theta around Y axis (in XZ plane).
            
            # Radial position (distance from Y axis)
            # R_base = major_radius
            
            # Profile shape (local coords u, v)
            # u = width direction (along Y)
            # v = thickness direction (Radial offset)
            
            u = (band_width / 2) * cos(phi)
            v = (band_thickness / 2) * sin(phi)
            
            # Apply D-Profile logic (Comfort Fit)
            # If v < 0 (inner surface), flatten it significantly but keep curve
            if v < 0:
                v *= 0.2  # Flatten the inside for comfort fit
                
            # Compute 3D position
            # R = Distance from Y axis
            R = major_radius + v
            
            # World coordinates
            # X = R * cos(theta)
            # Z = R * sin(theta)
            # Y = u
            
            x = R * cos(theta)
            z = R * sin(theta)
            y = u
            
            vert = bm.verts.new((x, y, z))
            profile_verts.append(vert)
            
        vert_grid.append(profile_verts)

    bm.verts.ensure_lookup_table()

    # Create Faces (Quads)
    for i in range(n_circ):
        i_next = (i + 1) % n_circ
        for j in range(n_prof):
            j_next = (j + 1) % n_prof
            
            v1 = vert_grid[i][j]
            v2 = vert_grid[i][j_next]
            v3 = vert_grid[i_next][j_next]
            v4 = vert_grid[i_next][j]
            
            bm.faces.new((v1, v2, v3, v4))

    # Recalculate normals
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # Create Mesh Data
    mesh_data = bpy.data.meshes.new("Gold_Band_Mesh")
    bm.to_mesh(mesh_data)
    bm.free()

    # Apply Smooth Shading
    for poly in mesh_data.polygons:
        poly.use_smooth = True

    # Create Object
    band_obj = bpy.data.objects.new("Gold_Band", mesh_data)
    ring_col.objects.link(band_obj)

    # ─── MODIFIERS (Non-Destructive) ─────────────────────────────────────
    
    # 1. Bevel (Catch light on edges)
    mod_bev = band_obj.modifiers.new("Bevel", 'BEVEL')
    mod_bev.width = 0.0002  # 0.2mm bevel
    mod_bev.segments = 3
    mod_bev.limit_method = 'ANGLE'
    mod_bev.angle_limit = radians(35)
    mod_bev.harden_normals = True

    # 2. Subdivision Surface (Luxury Smoothness)
    mod_sub = band_obj.modifiers.new("Subsurf", 'SUBSURF')
    mod_sub.levels = 2
    mod_sub.render_levels = 3
    mod_sub.quality = 3

# (build call moved to auto-export section)

# ========================= AUTO BUILD + EXPORT =========================
import bpy, os, traceback as _tb
from mathutils import Vector

_output = r"/home/nimra/ring-generator-service-tools/ring-validator/data/sessions/val_fd7be1fddd_1771783383/model.glb"
os.makedirs(os.path.dirname(_output), exist_ok=True)

print("[PIPELINE] Running build()...")
try:
    build()
    print("[PIPELINE] build() completed")
except Exception as _be:
    print(f"[PIPELINE] build() error: {_be}")
    _tb.print_exc()
    print("[PIPELINE] Attempting partial export...")

_obj_count = len([o for o in bpy.data.objects if o.type == 'MESH'])
print(f"[PIPELINE] Scene has {_obj_count} mesh objects")

# ========================= SPATIAL REPORT GENERATION =========================
print("===SPATIAL_REPORT_START===")
try:
    for _obj in bpy.data.objects:
        if _obj.type == 'MESH':
            _mesh = _obj.data
            _loc = _obj.location
            _rot = _obj.rotation_euler
            _scale = _obj.scale

            _verts = len(_mesh.vertices)
            _edges = len(_mesh.edges)
            _faces = len(_mesh.polygons)

            _bbox = [_obj.matrix_world @ Vector(v) for v in _obj.bound_box]
            _bbox_min = Vector((min([v.x for v in _bbox]), min([v.y for v in _bbox]), min([v.z for v in _bbox])))
            _bbox_max = Vector((max([v.x for v in _bbox]), max([v.y for v in _bbox]), max([v.z for v in _bbox])))

            _parent = _obj.parent.name if _obj.parent else "None"
            _mods = [m.type for m in _obj.modifiers]

            print(f"MESH: {_obj.name}")
            print(f"  Location: {_loc.x:.4f}, {_loc.y:.4f}, {_loc.z:.4f}")
            print(f"  Rotation: {_rot.x:.4f}, {_rot.y:.4f}, {_rot.z:.4f}")
            print(f"  Scale: {_scale.x:.4f}, {_scale.y:.4f}, {_scale.z:.4f}")
            print(f"  Geometry: {_verts} verts, {_edges} edges, {_faces} faces")
            print(f"  BBox Min: {_bbox_min.x:.4f}, {_bbox_min.y:.4f}, {_bbox_min.z:.4f}")
            print(f"  BBox Max: {_bbox_max.x:.4f}, {_bbox_max.y:.4f}, {_bbox_max.z:.4f}")
            print(f"  Parent: {_parent}")
            print(f"  Modifiers: {_mods}")
            print("---")
except Exception as _spatial_err:
    print(f"Spatial report generation failed: {_spatial_err}")
print("===SPATIAL_REPORT_END===")
# ========================= END SPATIAL REPORT =========================

if _obj_count == 0:
    print("[PIPELINE] No mesh objects to export!")
else:
    bpy.ops.object.select_all(action='SELECT')
    print(f"[PIPELINE] Exporting GLB to: {_output}")
    try:
        bpy.ops.export_scene.gltf(
            filepath=_output,
            export_format='GLB',
            use_selection=True,
            export_apply=True,
            export_animations=False,
            export_cameras=False,
            export_lights=False
        )
        _size = os.path.getsize(_output)
        print(f"[PIPELINE] GLB exported: {_size} bytes")
    except Exception as _e:
        print(f"[PIPELINE] Export FAILED: {_e}")
        _tb.print_exc()
