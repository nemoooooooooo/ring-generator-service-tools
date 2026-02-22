
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
from math import sin, cos, tan, pi, radians, sqrt, atan2, degrees, acos
from mathutils import Vector, Matrix, Euler

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
# SECTION A: CONFIGURATION & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Real-world dimensions in meters
RING_SIZE_US = 7.0
INNER_DIAMETER = (17.35 * 0.001)  # 17.35mm for US Size 7
INNER_RADIUS = INNER_DIAMETER / 2.0

# Band Dimensions
BAND_WIDTH_BOTTOM = 0.0022      # 2.2mm
BAND_THICKNESS_BOTTOM = 0.0016  # 1.6mm
BAND_WIDTH_TOP = 0.0030         # 3.0mm at shoulders (widened for channel)
BAND_THICKNESS_TOP = 0.0035     # 3.5mm rise for cathedral

# Gemstone (1.5 Carat Round Brilliant approx)
GEM_DIAMETER = 0.0074  # 7.4mm
GEM_RADIUS = GEM_DIAMETER / 2.0
GEM_DEPTH = GEM_DIAMETER * 0.61
GEM_TABLE_PCT = 0.56

# Calculated Vertical Positions
HEAD_HEIGHT_ABOVE_FINGER = INNER_RADIUS + BAND_THICKNESS_BOTTOM + 0.0015
GEM_CENTER_Z = HEAD_HEIGHT_ABOVE_FINGER + (GEM_DEPTH * 0.4) 

# Accent Stone Config (Shared between Shank and Accent Builders)
ACCENT_STONE_COUNT = 5
ACCENT_STONE_RADIUS = 0.00075 # 1.5mm diam
ACCENT_START_ANGLE = radians(65) # From top
ACCENT_END_ANGLE = radians(25)
CHANNEL_DEPTH = 0.0006
CHANNEL_WIDTH = (ACCENT_STONE_RADIUS * 2) + 0.0002

# Resolution
RES_CIRC = 128   # Circumferential segments
RES_PROF = 32    # Higher resolution for channel definition

# ═══════════════════════════════════════════════════════════════════════
# SECTION B: MATH UTILITIES
# ═══════════════════════════════════════════════════════════════════════

def lerp(a, b, t):
    """Linear interpolation."""
    return a + (b - a) * t

def smoothstep(edge0, edge1, x):
    """Hermite interpolation for organic smoothing."""
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)

def create_mesh_object(name, bm, collection):
    """Safely converts BMesh to Object and links to collection."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    
    # Standard Mesh Cleanup for Blender 4.0+
    for poly in mesh.polygons:
        poly.use_smooth = True
        
    return obj

def apply_metal_modifiers(obj):
    """Standard luxury metal modifier stack."""
    # 1. Bevel (Holds edges)
    mod_bev = obj.modifiers.new("Bevel", 'BEVEL')
    mod_bev.width = 0.00015  # 0.15mm bevel
    mod_bev.segments = 3
    mod_bev.limit_method = 'ANGLE'
    mod_bev.angle_limit = radians(35)
    mod_bev.harden_normals = True
    
    # 2. Subdivision (Smooths flow)
    mod_sub = obj.modifiers.new("Subsurf", 'SUBSURF')
    mod_sub.levels = 2
    mod_sub.render_levels = 3
    mod_sub.quality = 4

def apply_gem_modifiers(obj):
    """Gem specific modifiers (Sharp edges)."""
    mod_es = obj.modifiers.new("EdgeSplit", 'EDGE_SPLIT')
    mod_es.split_angle = radians(20)

# ═══════════════════════════════════════════════════════════════════════
# SECTION C: GEOMETRY BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def build_round_brilliant_gem(name, radius, center_pos, collection):
    """Constructs a physically accurate Round Brilliant Cut diamond."""
    bm = bmesh.new()
    r = radius
    cx, cy, cz = center_pos
    
    table_r = r * 0.56
    crown_h = r * 0.35
    girdle_thick = r * 0.03
    pavilion_h = r * 0.86
    
    z_table = cz + crown_h
    z_girdle_top = cz + girdle_thick / 2
    z_girdle_bot = cz - girdle_thick / 2
    z_culet = cz - pavilion_h
    
    # 1. Table
    v_table = []
    for i in range(8):
        angle = i * (2 * pi / 8) + (pi/8)
        x = cx + table_r * cos(angle)
        y = cy + table_r * sin(angle)
        v_table.append(bm.verts.new((x, y, z_table)))
    bm.faces.new(v_table)
    
    # 2. Girdle Rings
    v_g_top = []
    v_g_bot = []
    for i in range(16):
        angle = i * (2 * pi / 16)
        x = cx + r * cos(angle)
        y = cy + r * sin(angle)
        v_g_top.append(bm.verts.new((x, y, z_girdle_top)))
        v_g_bot.append(bm.verts.new((x, y, z_girdle_bot)))

    # 3. Crown (Table to Girdle)
    for i in range(8):
        t_curr = v_table[i]
        t_next = v_table[(i+1)%8]
        g_idx = i * 2
        g1 = v_g_top[g_idx]
        g2 = v_g_top[(g_idx+1)%16]
        g3 = v_g_top[(g_idx+2)%16]
        
        # Star facet
        _safe_face(bm, [t_curr, g2, t_next])
        # Kite facets
        _safe_face(bm, [t_curr, g1, g2])
        _safe_face(bm, [t_next, g2, g3])

    # 4. Girdle faces
    for i in range(16):
        next_i = (i+1)%16
        _safe_face(bm, [v_g_top[i], v_g_top[next_i], v_g_bot[next_i], v_g_bot[i]])

    # 5. Pavilion
    culet = bm.verts.new((cx, cy, z_culet))
    for i in range(16):
        next_i = (i+1)%16
        _safe_face(bm, [v_g_bot[i], v_g_bot[next_i], culet])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = create_mesh_object(name, bm, collection)
    for p in obj.data.polygons: p.use_smooth = False
    apply_gem_modifiers(obj)
    return obj

def build_integrated_shank(name, collection):
    """
    Builds Shank + Cathedral + Bridge + Channel Cuts.
    Uses 'Variable-Profile Sweep' with awareness of Accent Stones.
    """
    bm = bmesh.new()
    
    def get_profile_verts(angle_rad, num_verts):
        """Generates cross-section at specific angle."""
        dist_from_top = abs(angle_rad - pi/2)
        if dist_from_top > pi: dist_from_top = abs(dist_from_top - 2*pi)
        
        # Blends
        shoulder_blend = smoothstep(radians(90), radians(20), dist_from_top)
        
        # Base Dimensions
        width = lerp(BAND_WIDTH_BOTTOM, BAND_WIDTH_TOP, shoulder_blend)
        thickness = lerp(BAND_THICKNESS_BOTTOM, BAND_THICKNESS_TOP, shoulder_blend)
        
        # Channel Logic
        in_channel_zone = (ACCENT_END_ANGLE <= dist_from_top <= ACCENT_START_ANGLE)
        # Taper channel depth at ends
        channel_factor = 0.0
        if in_channel_zone:
            # Distance into zone
            mid_zone = (ACCENT_START_ANGLE + ACCENT_END_ANGLE) / 2
            zone_width = (ACCENT_START_ANGLE - ACCENT_END_ANGLE) / 2
            norm_pos = 1.0 - (abs(dist_from_top - mid_zone) / zone_width)
            channel_factor = smoothstep(0.0, 0.2, norm_pos) # Fade in/out
            
        verts = []
        for i in range(num_verts):
            t = i / float(num_verts - 1)
            phi = t * 2 * pi
            
            # Base D-Profile
            local_x = (width/2) * cos(phi)
            local_z = (thickness/2) * sin(phi)
            
            # Comfort fit (flatten inner)
            if sin(phi) < -0.1:
                local_z *= 0.7 
            
            # Channel Cutting (Outer Surface)
            if channel_factor > 0 and sin(phi) > 0.4:
                # Check width for channel (Top of ring is X=0 in profile)
                # Channel width is along X axis of profile
                if abs(local_x) < (CHANNEL_WIDTH / 2):
                    # Cut inward
                    cut_depth = CHANNEL_DEPTH * channel_factor
                    # Box cut with slight taper
                    local_z -= cut_depth
            
            # Bridge Flattening (At the very top)
            if dist_from_top < radians(15) and sin(phi) > 0:
                # Flatten the top to form a seat
                bridge_blend = smoothstep(radians(15), radians(0), dist_from_top)
                # Flatten Z towards a datum
                flat_z = thickness * 0.4
                if local_z > flat_z:
                    local_z = lerp(local_z, flat_z, bridge_blend)

            verts.append(Vector((local_x, local_z, 0)))
            
        return verts, thickness

    ring_verts = []
    
    for i in range(RES_CIRC):
        theta = (i / RES_CIRC) * 2 * pi
        raw_verts, thickness = get_profile_verts(theta, RES_PROF)
        
        r_inner = INNER_RADIUS
        
        # Cathedral Rise
        dist_from_top = abs(theta - pi/2)
        if dist_from_top > pi: dist_from_top = 2*pi - dist_from_top
        cathedral_blend = smoothstep(radians(60), radians(15), dist_from_top)
        extra_rise = cathedral_blend * 0.002
        
        profile_ring = []
        for v_local in raw_verts:
            # Radial position
            r = r_inner + (thickness/2) + v_local.z
            
            # Apply rise to outer surface only
            if v_local.z > 0:
                r += extra_rise * (v_local.z / (thickness/2))
            
            # Transform to 3D
            # Theta 0 = Right, Theta 90 = Top
            x = r * cos(theta)
            z = r * sin(theta)
            y = v_local.x # Width along Y
            
            profile_ring.append(bm.verts.new((x, y, z)))
        ring_verts.append(profile_ring)

    bm.verts.ensure_lookup_table()
    
    # Skinning
    for i in range(RES_CIRC):
        next_i = (i+1) % RES_CIRC
        for j in range(RES_PROF - 1):
            v1 = ring_verts[i][j]
            v2 = ring_verts[i][j+1]
            v3 = ring_verts[next_i][j+1]
            v4 = ring_verts[next_i][j]
            bm.faces.new((v1, v2, v3, v4))
        # Loop closure
        bm.faces.new((ring_verts[i][RES_PROF-1], ring_verts[i][0], 
                      ring_verts[next_i][0], ring_verts[next_i][RES_PROF-1]))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = create_mesh_object(name, bm, collection)
    apply_metal_modifiers(obj)
    return obj

def build_prongs(name, gem_center, gem_radius, collection):
    """Creates prongs that respect the gem geometry without intersection."""
    prong_count = 4
    prong_width = 0.0008
    cx, cy, cz = gem_center
    
    for p_idx in range(prong_count):
        bm = bmesh.new()
        angle = (p_idx * (2 * pi / prong_count)) + (pi/4)
        dir_x, dir_y = cos(angle), sin(angle)
        
        # Control Points
        r_base = gem_radius + 0.0006 # Start outside
        z_base = cz - (GEM_DEPTH * 0.5)
        
        r_mid = gem_radius + 0.0002 # Clearance at girdle
        z_mid = cz
        
        r_tip = gem_radius * 0.90 # Overlap on crown
        z_tip = cz + (GEM_DEPTH * 0.25)
        
        curve_points = [
            Vector((cx + dir_x*r_base, cy + dir_y*r_base, z_base)),
            Vector((cx + dir_x*r_mid,  cy + dir_y*r_mid,  z_mid)),
            Vector((cx + dir_x*r_tip,  cy + dir_y*r_tip,  z_tip))
        ]
        
        segments = 12
        prev_verts = []
        
        for i in range(segments + 1):
            t = i / segments
            invT = 1 - t
            pt = (invT * invT * curve_points[0]) + \
                 (2 * invT * t * curve_points[1]) + \
                 (t * t * curve_points[2])
            
            w = prong_width * (1.0 - (t * 0.3))
            
            # Cross section logic
            tx, ty = -sin(angle), cos(angle)
            v_right = Vector((tx*w/2, ty*w/2, 0))
            v_out = Vector((dir_x*w/2, dir_y*w/2, 0))
            
            c1 = pt - v_right - v_out
            c2 = pt + v_right - v_out
            c3 = pt + v_right + v_out
            c4 = pt - v_right + v_out
            
            # Round top
            if t > 0.8:
                c3.z -= 0.0003 * ((t-0.8)*5)
                c4.z -= 0.0003 * ((t-0.8)*5)

            current = [bm.verts.new(c1), bm.verts.new(c2), bm.verts.new(c3), bm.verts.new(c4)]
            if i > 0:
                for k in range(4):
                    bm.faces.new((prev_verts[k], prev_verts[(k+1)%4], current[(k+1)%4], current[k]))
            prev_verts = current
            
        bm.faces.new(reversed(prev_verts))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        obj = create_mesh_object(f"{name}_{p_idx+1:02d}", bm, collection)
        apply_metal_modifiers(obj)

def build_setting_gallery(name, gem_center, gem_radius, collection):
    """Creates a structural basket rail under the gem."""
    bm = bmesh.new()
    cx, cy, cz = gem_center
    r_rail = gem_radius * 0.9
    z_rail = cz - (GEM_DEPTH * 0.5)
    thick = 0.0006
    height = 0.0008
    seg = 32
    
    verts_top = []
    verts_bot = []
    
    for i in range(seg):
        a = i * (2*pi/seg)
        c, s = cos(a), sin(a)
        # Profile is a rectangle swept
        # Create 4 verts for this section
        v1 = bm.verts.new((cx + c*r_rail, cy + s*r_rail, z_rail))
        v2 = bm.verts.new((cx + c*(r_rail+thick), cy + s*(r_rail+thick), z_rail))
        v3 = bm.verts.new((cx + c*(r_rail+thick), cy + s*(r_rail+thick), z_rail - height))
        v4 = bm.verts.new((cx + c*r_rail, cy + s*r_rail, z_rail - height))
        verts_top.append([v1, v2, v3, v4])

    for i in range(seg):
        nxt = (i+1)%seg
        # Connect sections
        vt = verts_top[i]
        vn = verts_top[nxt]
        # Top face
        _safe_face(bm, [vt[0], vt[1], vn[1], vn[0]])
        # Outer face
        _safe_face(bm, [vt[1], vt[2], vn[2], vn[1]])
        # Bottom face
        _safe_face(bm, [vt[2], vt[3], vn[3], vn[2]])
        # Inner face
        _safe_face(bm, [vt[3], vt[0], vn[0], vn[3]])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = create_mesh_object(name, bm, collection)
    apply_metal_modifiers(obj)

def build_accent_stones_channel(name, collection):
    """Places accent stones in the procedurally generated channel."""
    # Logic must match build_integrated_shank channel zone
    
    for side in [-1, 1]: 
        for i in range(ACCENT_STONE_COUNT):
            t = i / (ACCENT_STONE_COUNT - 1)
            angle_offset = lerp(ACCENT_START_ANGLE, ACCENT_END_ANGLE, t)
            theta = (pi/2) + (angle_offset * side)
            
            # Place on the Channel Floor
            # We must recalculate where the floor is
            # R_inner + thickness + rise - channel_depth
            
            # Re-compute R at this theta
            dist_from_top = abs(angle_offset)
            shoulder_blend = smoothstep(radians(90), radians(20), dist_from_top)
            thickness = lerp(BAND_THICKNESS_BOTTOM, BAND_THICKNESS_TOP, shoulder_blend)
            
            cathedral_blend = smoothstep(radians(60), radians(15), dist_from_top)
            extra_rise = cathedral_blend * 0.002
            
            # Base outer R (before channel cut)
            r_outer_base = INNER_RADIUS + thickness + extra_rise
            
            # Channel floor R
            r_floor = r_outer_base - CHANNEL_DEPTH
            
            # Gem center should be slightly above floor so girdle clears
            # Girdle is at r_floor + clearance
            gem_r_pos = r_floor + (ACCENT_STONE_RADIUS * 0.4) # Sits low
            
            x = gem_r_pos * cos(theta)
            z = gem_r_pos * sin(theta)
            y = 0 
            
            gem_name = f"accent_gem_{'L' if side<0 else 'R'}_{i}"
            gem_obj = build_round_brilliant_gem(gem_name, ACCENT_STONE_RADIUS, (0,0,0), collection)
            
            gem_obj.location = (x, 0, z) # Y is 0 because band is centered on Y
            
            # Rotation: Align gem Z to Surface Normal
            # Surface Normal is (cos(theta), 0, sin(theta))
            # Standard Gem is +Z.
            # Rotate around Y axis by -(theta - pi/2)
            rot_y = -1 * (theta - pi/2)
            gem_obj.rotation_euler = (0, rot_y, 0)

# ═══════════════════════════════════════════════════════════════════════
# SECTION D: MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════

def nuke():
    """Clear the scene completely."""
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
        
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for col in bpy.data.collections:
        pass

def build_ring():
    nuke()
    ring_col = bpy.data.collections.new("Ring_Solitaire_Channel")
    bpy.context.scene.collection.children.link(ring_col)
    
    print("Building Structural Ring Geometry...")
    
    # 1. Main Gem
    gem_center = Vector((0, 0, GEM_CENTER_Z))
    build_round_brilliant_gem("center_diamond", GEM_RADIUS, gem_center, ring_col)
    
    # 2. Shank with Channel & Bridge
    build_integrated_shank("platinum_shank", ring_col)
    
    # 3. Structural Prongs
    build_prongs("prong", gem_center, GEM_RADIUS, ring_col)
    
    # 4. Gallery Rail
    build_setting_gallery("gallery_rail", gem_center, GEM_RADIUS, ring_col)
    
    # 5. Accent Stones (Now sitting IN channel)
    build_accent_stones_channel("accents", ring_col)
    
    print("Geometry Complete.")

if __name__ == "__main__":
    build_ring()

# ========================= AUTO BUILD + EXPORT =========================
import bpy, os, traceback as _tb
from mathutils import Vector

_output = r"/home/nimra/ring-generator-service-tools/ring-validator/data/sessions/s_d1cc16cacc_1771787103/model.glb"
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
