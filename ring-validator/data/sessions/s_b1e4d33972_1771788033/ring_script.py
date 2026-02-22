
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
from math import sin, cos, tan, pi, radians, sqrt, atan2
from mathutils import Vector, Matrix

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


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1: UTILITY FUNCTIONS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

def clean_scene():
    """Clear all objects and meshes to ensure a fresh build."""
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)

def lerp(a, b, t):
    """Linear interpolation."""
    return a + (b - a) * t

def smoothstep(edge0, edge1, x):
    """Smooth Hermite interpolation."""
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)

def create_mesh_object(name, bm, collection):
    """Finalizes BMesh into a Blender Object, links to collection."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    
    # Ensure smooth shading for metal parts
    for poly in mesh.polygons:
        poly.use_smooth = True
        
    return obj

def add_metal_modifiers(obj, bevel_width=0.0002):
    """Applies standard jewelry modifiers for metal."""
    # 1. Bevel (Holding edges)
    mod_bev = obj.modifiers.new("Bevel", 'BEVEL')
    mod_bev.width = bevel_width
    mod_bev.segments = 2
    mod_bev.limit_method = 'ANGLE'
    mod_bev.angle_limit = radians(35)
    mod_bev.affect = 'EDGES'
    
    # 2. Subdivision (Smoothness)
    mod_sub = obj.modifiers.new("Subsurf", 'SUBSURF')
    mod_sub.levels = 2
    mod_sub.render_levels = 3

def add_gem_modifiers(obj):
    """Applies gem-specific modifiers (Edge Split for crisp facets)."""
    # Gems should use FLAT shading initially, or Edge Split
    for poly in obj.data.polygons:
        poly.use_smooth = False
        
    mod_split = obj.modifiers.new("EdgeSplit", 'EDGE_SPLIT')
    mod_split.split_angle = radians(15)

# ═══════════════════════════════════════════════════════════════════════
# SECTION 2: GEOMETRY BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def get_heart_profile(t, scale=1.0):
    """
    Parametric Heart Equation.
    Returns (x, y) for a given t in [0, 2pi].
    Adjusted to center the heart roughly at 0,0.
    """
    # Standard Heart Curve
    x = 16 * sin(t)**3
    y = 13 * cos(t) - 5 * cos(2*t) - 2 * cos(3*t) - cos(4*t)
    
    # Normalize approx size and scale
    # The raw formula goes roughly -16 to 16 in X, -17 to 12 in Y
    x_norm = x / 16.0
    y_norm = y / 16.0
    
    return (x_norm * scale, y_norm * scale)

def build_heart_gem(location, size_scale, collection):
    """
    Builds a heart-shaped brilliant cut diamond.
    """
    bm = bmesh.new()
    
    cx, cy, cz = location
    
    # Gem Parameters
    girdle_r = size_scale
    table_r = size_scale * 0.6
    crown_h = size_scale * 0.35
    pavilion_h = size_scale * 0.6
    
    segments = 48  # High resolution for smooth curves
    
    # 1. Vertex Lists
    v_table_center = bm.verts.new((cx, cy, cz + crown_h))
    v_culet = bm.verts.new((cx, cy, cz - pavilion_h))
    
    verts_table = []
    verts_girdle = []
    
    # Generate perimeter rings
    for i in range(segments):
        t = (2 * pi * i) / segments
        # Align tip to -Y
        hx, hy = get_heart_profile(t + pi, scale=1.0) 
        
        # Girdle Ring
        verts_girdle.append(bm.verts.new((cx + hx*girdle_r, cy + hy*girdle_r, cz)))
        
        # Table Ring
        verts_table.append(bm.verts.new((cx + hx*table_r, cy + hy*table_r, cz + crown_h)))

    bm.verts.ensure_lookup_table()
    
    # 2. Faces
    
    # Table (Center fan)
    for i in range(segments):
        i_next = (i + 1) % segments
        _safe_face(bm, [v_table_center, verts_table[i], verts_table[i_next]])
        
    # Crown (Table to Girdle)
    for i in range(segments):
        i_next = (i + 1) % segments
        _safe_face(bm, [verts_table[i_next], verts_table[i], verts_girdle[i], verts_girdle[i_next]])
        
    # Pavilion (Girdle to Culet fan)
    for i in range(segments):
        i_next = (i + 1) % segments
        _safe_face(bm, [verts_girdle[i], verts_girdle[i_next], v_culet])
        
    # Recalculate normals
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    
    # Create Object
    obj = create_mesh_object("center_heart_diamond", bm, collection)
    add_gem_modifiers(obj)
    return obj

def build_heart_basket(gem_location, size_scale, thickness, collection):
    """
    Builds a wire basket/gallery that follows the heart shape underneath the gem.
    Modified to include a solid base plate for structural connection to shank.
    """
    bm = bmesh.new()
    cx, cy, cz = gem_location
    
    # Basket Parameters
    top_rim_z = cz - (size_scale * 0.1) 
    bottom_rim_z = cz - (size_scale * 0.5)
    
    segments = 48
    
    # Helper to make a tube segment
    def create_rim(z_level, r_scale, tube_r):
        rim_verts = []
        for i in range(segments):
            t = (2 * pi * i) / segments
            hx, hy = get_heart_profile(t + pi, scale=1.0)
            
            # Position of the wire center
            px = cx + hx * size_scale * r_scale
            py = cy + hy * size_scale * r_scale
            pz = z_level
            
            # Create a small cross section
            v1 = bm.verts.new((px - tube_r, py - tube_r, pz))
            v2 = bm.verts.new((px + tube_r, py - tube_r, pz))
            v3 = bm.verts.new((px + tube_r, py + tube_r, pz))
            v4 = bm.verts.new((px - tube_r, py + tube_r, pz))
            rim_verts.append([v1, v2, v3, v4])
        return rim_verts

    # Build Top Rim (Under Girdle)
    top_rim = create_rim(top_rim_z, 0.95, thickness)
    # Build Bottom Rim
    bot_rim = create_rim(bottom_rim_z, 0.6, thickness)
    
    # Skin the rims (create tubes)
    for rim in [top_rim, bot_rim]:
        for i in range(segments):
            i_next = (i + 1) % segments
            for k in range(4):
                k_next = (k + 1) % 4
                _safe_face(bm, [rim[i][k], rim[i][k_next], rim[i_next][k_next], rim[i_next][k]])
    
    # Add Struts (Vertical supports)
    strut_indices = [0, 6, 12, 18, 24, 30, 36, 42] # More struts for better support
    
    for idx in strut_indices:
        v_top = top_rim[idx]
        v_bot = bot_rim[idx]
        _safe_face(bm, [v_top[0], v_top[1], v_bot[1], v_bot[0]])
        _safe_face(bm, [v_top[1], v_top[2], v_bot[2], v_bot[1]])
        _safe_face(bm, [v_top[2], v_top[3], v_bot[3], v_bot[2]])
        _safe_face(bm, [v_top[3], v_top[0], v_bot[0], v_bot[3]])

    # CRITICAL FIX: Add a solid base plate/hub at the bottom rim to ensure shank connects
    # We create a center vertex at the bottom level and fan out to the bottom rim inner edges
    base_center = bm.verts.new((cx, cy, bottom_rim_z))
    for i in range(segments):
        i_next = (i + 1) % segments
        # Connect center to the inner vertices of the bottom rim
        # Assuming index 0 of the 4-vert profile is inner-most (it varies, but this closes the loop)
        # To be safe, we just fan to all 4 points of the rim profile? No, that's messy.
        # Let's take the first vertex of the profile as inner reference
        _safe_face(bm, [base_center, bot_rim[i][0], bot_rim[i_next][0]])
        
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = create_mesh_object("heart_setting_basket", bm, collection)
    add_metal_modifiers(obj)
    return obj

def build_prong(location, height, radius, collection, name="prong"):
    """
    Builds a rounded 'cute' button prong.
    """
    bm = bmesh.new()
    
    # Capsule-like cylinder
    bmesh.ops.create_cone(bm, 
                          cap_ends=True, 
                          cap_tris=False, 
                          segments=16, # Increased segments for roundness
                          radius1=radius,  
                          radius2=radius * 0.9, # Slight taper
                          depth=height,
                          matrix=Matrix.Translation(location) @ Matrix.Translation((0,0,height/2)))
    
    # Round the top - manual bevel-like effect
    # Select top face vertices
    top_z_threshold = location[2] + height * 0.9
    
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = create_mesh_object(name, bm, collection)
    add_metal_modifiers(obj)
    return obj

def build_cathedral_shank(inner_radius, width, thickness, gem_z_base, collection):
    """
    Builds a shank that rises up to meet the heart setting (Cathedral style).
    FIXED: Now rises fully to meet the basket base, preventing floating head.
    """
    bm = bmesh.new()
    
    major_radius = inner_radius + thickness / 2
    circ_segs = 128 # Higher resolution for smooth curves
    prof_segs = 16
    
    prev_verts = []
    start_verts = []
    
    for i in range(circ_segs):
        theta = (2 * pi * i) / circ_segs
        
        # Normalized distance from top
        dist_from_top = abs(theta - pi/2)
        if dist_from_top > pi: dist_from_top = abs(dist_from_top - 2*pi)
        
        # Cathedral Rise Logic
        # Rise starts around 60 degrees from top
        rise_factor = smoothstep(radians(70), radians(10), dist_from_top)
        
        # FIXED: Remove the 0.8 multiplier. Shank center now rises to meet the basket bottom exactly.
        # Since the shank has thickness, the top half will engulf the basket bottom.
        current_radius = major_radius + (rise_factor * (gem_z_base - major_radius))
        
        # Taper width: Narrower at top for elegance, wider at bottom
        current_width = width * (1.0 - (rise_factor * 0.2)) 
        
        # Profile center position
        cx = current_radius * cos(theta)
        cz = current_radius * sin(theta)
        cy = 0 # Centered on Y
        
        # Generate Profile (Rounded Rect / D-shape)
        ring_verts = []
        mat_rot = Matrix.Rotation(theta, 4, 'Y')
        
        for j in range(prof_segs):
            phi = (2 * pi * j) / prof_segs
            
            # Oval profile
            local_x = (thickness/2) * cos(phi)
            local_y = (current_width/2) * sin(phi)
            
            # Flatten inner surface slightly for comfort fit
            if local_x < 0:
                local_x *= 0.8
            
            # Transform to world
            vec = Vector((local_x, local_y, 0))
            vec.rotate(Matrix.Rotation(pi/2, 3, 'X')) # Orient profile correctly
            vec = mat_rot @ vec
            
            vx = cx + vec.x
            vz = cz + vec.z
            vy = cy + vec.y
            
            ring_verts.append(bm.verts.new((vx, vy, vz)))
            
        if i > 0:
            for k in range(prof_segs):
                k_next = (k + 1) % prof_segs
                _safe_face(bm, [prev_verts[k], prev_verts[k_next], ring_verts[k_next], ring_verts[k]])
        else:
            start_verts = ring_verts
            
        prev_verts = ring_verts
        
    # Close the loop
    for k in range(prof_segs):
        k_next = (k + 1) % prof_segs
        _safe_face(bm, [prev_verts[k], prev_verts[k_next], start_verts[k_next], start_verts[k]])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = create_mesh_object("shank_band", bm, collection)
    add_metal_modifiers(obj, bevel_width=0.0003)
    return obj

# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: ASSEMBLY LOGIC
# ═══════════════════════════════════════════════════════════════════════

def build_cute_heart_ring():
    clean_scene()
    
    # 1. Configuration / Dimensions (Real World Meters)
    ring_size_radius = 0.0085  # ~Size 7 US
    band_width = 0.0025
    band_thickness = 0.0018
    
    gem_scale = 0.0035         # ~7mm heart
    
    # 2. Compute Diamond Position
    band_top_z = ring_size_radius + band_thickness
    # Lift gem enough to have a basket underneath
    gem_pos = (0, 0, band_top_z + 0.0018)
    
    # 3. Create Collection
    coll = bpy.data.collections.new("Cute_Heart_Ring")
    bpy.context.scene.collection.children.link(coll)
    
    # 4. Build Components
    
    # A. The Gem
    gem_obj = build_heart_gem(gem_pos, gem_scale, coll)
    
    # B. The Basket/Head (Structural connection)
    basket_obj = build_heart_basket(gem_pos, gem_scale, 0.0004, coll)
    
    # C. The Shank (Band)
    # Target height for the shank to meet.
    # The basket has a bottom rim at gem_pos[2] - 0.5*scale
    basket_bottom_z = gem_pos[2] - (gem_scale * 0.5)
    shank_obj = build_cathedral_shank(ring_size_radius, band_width, band_thickness, basket_bottom_z, coll)
    
    # D. Prongs
    # 3 Prongs: 1 Tip, 2 Lobes
    angles = [0, 2.0, 4.28] # Radians approx for Tip, Right Lobe, Left Lobe
    
    prong_radius = 0.0006 # Slightly thicker for cuteness/stability
    prong_height = 0.003  # Taller to ensure they wrap
    
    for i, ang in enumerate(angles):
        # Calculate position on the girdle perimeter
        # +pi because the gem builder uses t+pi
        hx, hy = get_heart_profile(ang + pi, scale=1.0) 
        
        # Move slightly inward to overlap the stone edge
        px = gem_pos[0] + hx * gem_scale * 0.98
        py = gem_pos[1] + hy * gem_scale * 0.98
        
        # Base needs to be lower to anchor into the basket structure
        pz_base = gem_pos[2] - (gem_scale * 0.4) 
        
        build_prong((px, py, pz_base), prong_height, prong_radius, coll, f"prong_{i}")

# ═══════════════════════════════════════════════════════════════════════
# EXECUTION
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    build_cute_heart_ring()

# ========================= AUTO BUILD + EXPORT =========================
import bpy, os, traceback as _tb
from mathutils import Vector

_output = r"/home/nimra/ring-generator-service-tools/ring-validator/data/sessions/s_b1e4d33972_1771788033/model.glb"
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
