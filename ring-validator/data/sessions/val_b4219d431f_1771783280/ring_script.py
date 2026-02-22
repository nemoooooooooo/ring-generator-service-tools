
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
    # ═══════════════════════════════════════════════════════════════════════
    # SETUP & CLEANUP
    # ═══════════════════════════════════════════════════════════════════════
    
    # Ensure we are in object mode to prevent context errors
    if bpy.context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except:
            pass
            
    # Clear existing objects to regenerate the ring cleanly
    # (Safe cleanup pattern)
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
        
    # ═══════════════════════════════════════════════════════════════════════
    # 1. COMPUTE DIMENSIONS (Real World Scale - Meters)
    # ═══════════════════════════════════════════════════════════════════════
    
    # Standard US Size 7 Ring
    # Inner Diameter: ~17.3 mm
    # Converted to meters: 0.0173 m
    inner_diameter_mm = 17.3
    inner_radius = (inner_diameter_mm / 2.0) * 0.001
    
    # Band Design Proportions
    # A "Simple Gold Band" implies a classic Wedding Band style
    # Width: 4.0mm (Standard width)
    # Thickness: 2.0mm (Luxury weight)
    band_width = 4.0 * 0.001
    band_thickness = 2.0 * 0.001
    
    # Major Radius (Distance from center to the centroid of the band profile)
    major_radius = inner_radius + (band_thickness / 2.0)
    
    # Resolution (High density for luxury smoothness)
    n_circ = 128  # Circumferential segments
    n_prof = 32   # Cross-section profile segments
    
    # ═══════════════════════════════════════════════════════════════════════
    # 2. CONSTRUCT GEOMETRY (BMESH - No Operators)
    # ═══════════════════════════════════════════════════════════════════════
    
    bm = bmesh.new()
    
    # Storage for grid of vertices [ring_index][profile_index]
    vert_grid = []
    
    # Generate the Ring Sweep
    # We sweep a "Comfort Fit" profile around the Y-axis (Finger axis)
    # The ring sits in the X-Z plane.
    
    for i in range(n_circ):
        # Theta: Angle around the finger (0 to 2*PI)
        theta = 2 * pi * i / n_circ
        
        # Profile Ring Generation
        profile_verts = []
        for j in range(n_prof):
            # t: Parameter around the cross-section (0 to 1)
            t = j / n_prof
            p_angle = 2 * pi * t
            
            # ─── PROFILE SHAPE LOGIC ─────────────────────────────
            # We create a "Comfort Fit" D-Profile
            # Local coordinates:
            # u = Radial offset (Thickness axis)
            # v = Axial offset (Width axis)
            
            # Start with an ellipse base
            u_raw = (band_thickness / 2.0) * cos(p_angle)
            v_raw = (band_width / 2.0) * sin(p_angle)
            
            # Apply D-Shape deformation
            # The "inner" side (negative u) should be flatter than the outer dome
            # This creates the "Comfort Fit" interior
            u = u_raw
            v = v_raw
            
            if u < 0:
                # Flatten the inner surface curvature by 60%
                u *= 0.4
            
            # ─── TRANSFORM TO GLOBAL SPACE ───────────────────────
            # Radial distance from ring center (Y-axis)
            r_final = major_radius + u
            
            # Map to X-Z plane (Ring stands up, Y is finger axis)
            # Global X
            x = r_final * cos(theta)
            # Global Z
            z = r_final * sin(theta)
            # Global Y (Width)
            y = v
            
            vert = bm.verts.new((x, y, z))
            profile_verts.append(vert)
            
        vert_grid.append(profile_verts)
        
    bm.verts.ensure_lookup_table()
    
    # ═══════════════════════════════════════════════════════════════════════
    # 3. CREATE FACES (Topology)
    # ═══════════════════════════════════════════════════════════════════════
    
    for i in range(n_circ):
        i_next = (i + 1) % n_circ
        for j in range(n_prof):
            j_next = (j + 1) % n_prof
            
            # Define quad corners
            v1 = vert_grid[i][j]
            v2 = vert_grid[i][j_next]
            v3 = vert_grid[i_next][j_next]
            v4 = vert_grid[i_next][j]
            
            # Add face
            try:
                bm.faces.new((v1, v2, v3, v4))
            except ValueError:
                pass # Skip duplicate faces if any
                
    # Recalculate normals to ensure outside is outside
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    
    # ═══════════════════════════════════════════════════════════════════════
    # 4. FINAL OBJECT CREATION
    # ═══════════════════════════════════════════════════════════════════════
    
    mesh_name = "Gold_Band_Mesh"
    obj_name = "Gold_Band"
    
    mesh_data = bpy.data.meshes.new(mesh_name)
    bm.to_mesh(mesh_data)
    bm.free()
    
    obj = bpy.data.objects.new(obj_name, mesh_data)
    bpy.context.collection.objects.link(obj)
    
    # ═══════════════════════════════════════════════════════════════════════
    # 5. AESTHETIC MODIFIERS (Non-Destructive)
    # ═══════════════════════════════════════════════════════════════════════
    
    # A. Smooth Shading (Essential for round metal)
    for poly in mesh_data.polygons:
        poly.use_smooth = True
        
    # B. Bevel Modifier
    # catches highlights on the edges, making it look manufactured not generated
    mod_bev = obj.modifiers.new("Bevel", 'BEVEL')
    mod_bev.width = 0.0003  # 0.3mm bevel width
    mod_bev.segments = 3    # Smooth roundover
    mod_bev.limit_method = 'ANGLE'
    mod_bev.angle_limit = radians(35)
    mod_bev.harden_normals = True
    
    # C. Subdivision Surface
    # Ensures perfect curvature at render time
    mod_sub = obj.modifiers.new("Subsurf", 'SUBSURF')
    mod_sub.levels = 2
    mod_sub.render_levels = 3

# (build call moved to auto-export section)

# ========================= AUTO BUILD + EXPORT =========================
import bpy, os, traceback as _tb
from mathutils import Vector

_output = r"/home/nimra/ring-generator-service-tools/ring-validator/data/sessions/val_b4219d431f_1771783280/model.glb"
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
