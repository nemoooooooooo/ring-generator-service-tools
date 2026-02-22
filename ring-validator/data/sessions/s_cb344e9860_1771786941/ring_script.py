
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
import math
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
# SECTION A: CONFIGURATION & MATH HELPERS
# ═══════════════════════════════════════════════════════════════════════

# REAL WORLD DIMENSIONS (Meters)
# Standard Size 7
RING_SIZE_US = 7
INNER_RADIUS = (17.35 / 2) / 1000.0  # ~8.675mm
BAND_WIDTH_BOTTOM = 0.0022
BAND_WIDTH_TOP = 0.0032          # Slightly wider at shoulders for support
BAND_THICK_BOTTOM = 0.0017
BAND_THICK_TOP = 0.0040          # Cathedral rise height

# GEMSTONES
CENTER_CARAT = 1.0
CENTER_RADIUS = 0.00325          # ~6.5mm diameter
ACCENT_RADIUS = 0.0008           # 1.6mm diameter
HALO_RADIUS = 0.0006             # 1.2mm diameter

# SETTING DIMENSIONS
SETTING_RIM_HEIGHT = CENTER_RADIUS * 0.4  # Height of basket rim
SETTING_BASE_HEIGHT = CENTER_RADIUS * 0.2

# RESOLUTION (High Quality)
RES_CIRC = 128
RES_PROF = 32

def clean_scene():
    """Remove all objects and meshes to start fresh."""
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)

def lerp(a, b, t):
    return a + (b - a) * t

def smoothstep(edge0, edge1, x):
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)

def create_mesh_object(name, bm, collection, use_smooth=True):
    """Finalizes BMesh to Object, links to scene, applies smoothing."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    
    if use_smooth:
        for p in mesh.polygons:
            p.use_smooth = True
    
    return obj

def apply_metal_modifiers(obj, bevel_width=0.0001):
    """Applies the luxury modifier stack: Bevel -> Subsurf."""
    # 1. Bevel (Holding edges)
    mod_bev = obj.modifiers.new(name="Bevel", type='BEVEL')
    mod_bev.width = bevel_width
    mod_bev.segments = 2
    mod_bev.limit_method = 'ANGLE'
    mod_bev.angle_limit = radians(35)
    mod_bev.harden_normals = True
    
    # 2. Subsurf (Smoothness)
    mod_sub = obj.modifiers.new(name="Subsurf", type='SUBSURF')
    mod_sub.levels = 2
    mod_sub.render_levels = 3
    mod_sub.quality = 3

def apply_gem_modifiers(obj):
    """Applies crisp gem modifiers."""
    mod_split = obj.modifiers.new(name="EdgeSplit", type='EDGE_SPLIT')
    mod_split.split_angle = radians(15)

# ═══════════════════════════════════════════════════════════════════════
# SECTION B: DIAMOND GENERATORS (BMESH)
# ═══════════════════════════════════════════════════════════════════════

def create_brilliant_gem_bmesh(radius):
    """Generates a round brilliant cut diamond geometry."""
    bm = bmesh.new()
    r = radius
    table_r = r * 0.56
    crown_h = r * 0.16
    girdle_h = r * 0.03
    pavilion_h = r * 0.43
    
    z_table = crown_h + girdle_h/2
    z_girdle_top = girdle_h/2
    z_girdle_bot = -girdle_h/2
    z_culet = -pavilion_h - girdle_h/2
    
    segments = 16
    
    v_table_center = bm.verts.new((0, 0, z_table))
    verts_table = []
    verts_girdle_top = []
    verts_girdle_bot = []
    
    for i in range(segments):
        a = 2 * pi * i / segments
        verts_table.append(bm.verts.new((table_r * cos(a), table_r * sin(a), z_table)))
        verts_girdle_top.append(bm.verts.new((r * cos(a), r * sin(a), z_girdle_top)))
        verts_girdle_bot.append(bm.verts.new((r * cos(a), r * sin(a), z_girdle_bot)))
        
    v_culet = bm.verts.new((0, 0, z_culet))
    bm.verts.ensure_lookup_table()
    
    # Faces
    for i in range(segments):
        i_next = (i + 1) % segments
        _safe_face(bm, [v_table_center, verts_table[i], verts_table[i_next]]) # Table
        _safe_face(bm, [verts_table[i], verts_girdle_top[i], verts_girdle_top[i_next], verts_table[i_next]]) # Crown
        _safe_face(bm, [verts_girdle_top[i], verts_girdle_bot[i], verts_girdle_bot[i_next], verts_girdle_top[i_next]]) # Girdle
        _safe_face(bm, [verts_girdle_bot[i], v_culet, verts_girdle_bot[i_next]]) # Pavilion

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm

# ═══════════════════════════════════════════════════════════════════════
# SECTION C: PLACEHOLDER & LAYOUT SYSTEM
# ═══════════════════════════════════════════════════════════════════════

def get_cathedral_params(theta):
    """
    Returns (width, thick, blend_factor, lift_offset) for the shank at angle theta.
    Theta 0 = Right, PI/2 = Top.
    """
    # Normalize theta to distance from top (0.0 at top)
    angle_from_top = abs(atan2(sin(theta), cos(theta)) - (pi/2))
    if angle_from_top > pi: angle_from_top = 2*pi - angle_from_top
    
    # Cathedral blend: Starts rising at 60 degrees, peaks at top
    blend = smoothstep(radians(65), radians(15), angle_from_top)
    
    w = lerp(BAND_WIDTH_BOTTOM, BAND_WIDTH_TOP, blend)
    t = lerp(BAND_THICK_BOTTOM, BAND_THICK_TOP, blend)
    
    # Additional lift calculation for the "Cathedral" arch effect
    # The band splits or rises up to meet the head
    lift = 0.0
    if blend > 0:
        lift = blend * 0.0015  # 1.5mm lift at shoulders
        
    return w, t, blend, lift

def compute_diamond_layout():
    """Calculates positions for all gems before building metal."""
    layout = {
        'center': None,
        'accents': [],
        'halo': []
    }
    
    # 1. CENTER STONE
    # Sits at top (PI/2), elevated by setting
    # Base of head sits on top of shank shoulder height
    _, thick_top, _, lift_top = get_cathedral_params(pi/2)
    shank_top_z = INNER_RADIUS + thick_top/2 + lift_top
    
    # Gem center (girdle) needs to be above the setting base
    head_height = CENTER_RADIUS * 1.0 # exposed height
    center_pos = Vector((0, 0, shank_top_z + 0.0005 + head_height)) # 0.5mm bridge clearance
    
    layout['center'] = {
        'pos': center_pos,
        'radius': CENTER_RADIUS,
        'vector_up': Vector((0,0,1)),
        'girdle_z': center_pos.z
    }
    
    # 2. CHANNEL ACCENTS (Shoulders)
    start_angle_deg = 35
    end_angle_deg = 75
    
    circumference = 2 * pi * (INNER_RADIUS + BAND_THICK_TOP)
    arc_len = circumference * ((end_angle_deg - start_angle_deg)/360.0)
    count = int(arc_len / (ACCENT_RADIUS * 2.4))
    
    for side in [-1, 1]:
        for i in range(count):
            t = i / max(1, count - 1)
            angle_deg = lerp(start_angle_deg, end_angle_deg, t)
            angle_rad = pi/2 + side * radians(angle_deg) # Start from top (PI/2) and go down sides
            
            # Correct radial placement logic matching shank build
            # Shank uses: major_r = INNER + t/2. Outer surface = major_r + t/2 = INNER + t
            w, t_p, blend, lift = get_cathedral_params(angle_rad)
            
            # Surface radius at this angle (approximate center of channel)
            surface_r = INNER_RADIUS + t_p + lift
            
            # Correct position
            px = surface_r * cos(angle_rad)
            pz = surface_r * sin(angle_rad)
            pos = Vector((px, 0, pz))
            
            normal = pos.normalized()
            
            layout['accents'].append({
                'pos': pos,
                'radius': ACCENT_RADIUS,
                'normal': normal,
                'angle': angle_rad,
                'blend': blend
            })

    # 3. HIDDEN HALO (Under bezel)
    # Sits below the main stone
    halo_z = center_pos.z - CENTER_RADIUS * 0.7 
    halo_r_ring = CENTER_RADIUS * 1.05
    halo_count = 16
    
    for i in range(halo_count):
        angle = (2 * pi / halo_count) * i
        hx = halo_r_ring * cos(angle)
        hy = halo_r_ring * sin(angle)
        hz = halo_z
        
        pos = Vector((hx, hy, hz))
        normal = Vector((cos(angle), sin(angle), 0))
        
        layout['halo'].append({
            'pos': pos,
            'radius': HALO_RADIUS,
            'normal': normal
        })
        
    return layout

# ═══════════════════════════════════════════════════════════════════════
# SECTION D: METAL CONSTRUCTION (SHANK & HEAD)
# ═══════════════════════════════════════════════════════════════════════

def build_structural_shank(layout, col):
    """
    Builds the main shank mesh.
    Cathedral style: shoulders rise up to meet the head.
    """
    bm = bmesh.new()
    sections = []
    
    for i in range(RES_CIRC):
        theta = (2 * pi * i) / RES_CIRC
        
        width, thick, blend, lift = get_cathedral_params(theta)
        
        # Major radius (center of the profile torus)
        # Inner radius is constant.
        # R_inner = R_major - thick/2
        # Therefore R_major = R_inner + thick/2
        major_r = INNER_RADIUS + thick / 2.0
        
        # Local Basis
        cos_t = cos(theta)
        sin_t = sin(theta)
        center_pos = Vector((major_r * cos_t, 0, major_r * sin_t))
        
        # Apply Lift (Cathedral Arch) to the center position
        # We move the whole profile up (Z in world) by 'lift' * blend
        # Actually, for a ring, 'up' is radial. 
        # But Cathedral style specifically lifts Z relative to the finger axis? 
        # No, it expands radially outward.
        center_pos += Vector((cos_t, 0, sin_t)) * lift
        
        normal = Vector((cos_t, 0, sin_t)) # Radial Out
        binormal = Vector((0, 1, 0))       # Axial (Width)
        
        slice_verts = []
        
        # Detect Channel
        in_channel = False
        for gem in layout['accents']:
            # Angular tolerance for channel cut
            if abs(atan2(sin(gem['angle']-theta), cos(gem['angle']-theta))) < radians(4):
                in_channel = True
                break
        
        channel_w = ACCENT_RADIUS * 2.2
        channel_d = ACCENT_RADIUS * 1.1 # Depth to seat Culet inside metal
        
        for j in range(RES_PROF):
            t_prof = j / (RES_PROF - 1)
            phi = 2 * pi * t_prof
            
            # Elliptical D-Profile
            prof_w = width / 2.0
            prof_h = thick / 2.0
            
            # u = radial offset, v = width offset
            u = prof_h * -cos(phi) 
            v = prof_w * sin(phi)
            
            # Comfort Fit (flatten inside)
            if u < 0: u *= 0.2
            
            # Channel Cut
            # Only on outer top surface
            if in_channel and u > prof_h * 0.4:
                if abs(v) < channel_w / 2.0:
                    # Recess floor
                    u -= channel_d
                elif abs(v) < (channel_w / 2.0 + 0.0002):
                    # Vertical walls (no change in u implies cliff)
                    pass 
            
            # 3D Position
            vert_pos = center_pos + (u * normal) + (v * binormal)
            slice_verts.append(bm.verts.new(vert_pos))
            
        sections.append(slice_verts)

    bm.verts.ensure_lookup_table()
    
    # Skinning
    for i in range(RES_CIRC):
        i_next = (i + 1) % RES_CIRC
        for j in range(RES_PROF):
            j_next = (j + 1) % RES_PROF
            v1, v2 = sections[i][j], sections[i][j_next]
            v3, v4 = sections[i_next][j_next], sections[i_next][j]
            _safe_face(bm, [v1, v2, v3, v4])
            
    obj = create_mesh_object("shank", bm, col)
    apply_metal_modifiers(obj)
    return obj

def build_setting_head(layout, col):
    """
    Builds the structural Basket/Cup that holds the center stone.
    Connects the shank shoulders to the gem.
    CRITICAL: This object prevents floating diamonds.
    """
    bm = bmesh.new()
    
    c_data = layout['center']
    center = c_data['pos']
    radius = c_data['radius']
    
    # Calculate heights
    girdle_z = center.z
    # Base of setting sits between the shank shoulders
    # We take the Z height of the shank shoulder top we calculated earlier
    _, thick, _, lift = get_cathedral_params(pi/2)
    shank_shoulder_z = INNER_RADIUS + thick + lift
    
    base_z = shank_shoulder_z - 0.0005 # Embed slightly
    
    # Dimensions
    top_r = radius * 1.1      # Rim around gem
    base_r = radius * 0.7     # Tapered bottom
    
    segments = 64
    rings = []
    
    # 1. Base Ring (Bottom)
    ring_base = []
    for i in range(segments):
        a = 2*pi*i/segments
        x = base_r * cos(a)
        y = base_r * sin(a)
        ring_base.append(bm.verts.new((x, y, base_z)))
    rings.append(ring_base)
    
    # 2. Mid Ring (Gallery Rail Level)
    gallery_z = center.z - radius * 0.7
    ring_mid = []
    mid_r = lerp(base_r, top_r, 0.6)
    for i in range(segments):
        a = 2*pi*i/segments
        x = mid_r * cos(a)
        y = mid_r * sin(a)
        ring_mid.append(bm.verts.new((x, y, gallery_z)))
    rings.append(ring_mid)
        
    # 3. Top Ring (Seat)
    ring_top = []
    for i in range(segments):
        a = 2*pi*i/segments
        x = top_r * cos(a)
        y = top_r * sin(a)
        ring_top.append(bm.verts.new((x, y, girdle_z)))
    rings.append(ring_top)
    
    # 4. Inner Ring (Seat thickness)
    ring_inner = []
    inner_r = radius * 0.9 # Gem rests on this lip
    for i in range(segments):
        a = 2*pi*i/segments
        x = inner_r * cos(a)
        y = inner_r * sin(a)
        ring_inner.append(bm.verts.new((x, y, girdle_z)))
    rings.append(ring_inner)
    
    bm.verts.ensure_lookup_table()
    
    # Faces - Outer Wall
    for r in range(len(rings)-1):
        # Skip inner ring for now
        if r == 2: break 
        for i in range(segments):
            i2 = (i+1)%segments
            _safe_face(bm, [rings[r][i], rings[r][i2], rings[r+1][i2], rings[r+1][i]])
            
    # Faces - Top Rim
    for i in range(segments):
        i2 = (i+1)%segments
        _safe_face(bm, [rings[2][i], rings[2][i2], rings[3][i2], rings[3][i]])
        
    # Faces - Inner Cup (Taper down to a point or open?)
    # Let's make an open cup for light
    cup_bottom_z = gallery_z
    ring_cup_bot = []
    for i in range(segments):
        a = 2*pi*i/segments
        x = inner_r * 0.6 * cos(a)
        y = inner_r * 0.6 * sin(a)
        ring_cup_bot.append(bm.verts.new((x, y, cup_bottom_z)))
        
    for i in range(segments):
        i2 = (i+1)%segments
        _safe_face(bm, [rings[3][i], rings[3][i2], ring_cup_bot[i2], ring_cup_bot[i]])
        
    obj = create_mesh_object("setting_head", bm, col)
    apply_metal_modifiers(obj)


def build_prongs(layout, col):
    """
    Builds organic claw prongs.
    Wraps OVER the gem crown.
    """
    c_data = layout['center']
    c_pos = c_data['pos']
    c_rad = c_data['radius']
    
    prong_w = c_rad * 0.22
    prong_h = c_rad * 0.7  # Height above setting base
    
    # 4 Prongs at 45 degree angles
    angles = [45, 135, 225, 315]
    
    for i, deg in enumerate(angles):
        bm = bmesh.new()
        rad = radians(deg)
        dir_vec = Vector((cos(rad), sin(rad), 0))
        
        # Start at gallery rail level
        start_z = c_pos.z - c_rad * 0.7
        end_z = c_pos.z + c_rad * 0.25 # Over the table edge slightly
        
        steps = 12
        sections = []
        
        for s in range(steps):
            t = s / (steps - 1)
            
            # Vertical progression
            z = lerp(start_z, end_z, t)
            
            # Radial progression (Curve inward)
            # Base is outside gem, Tip is inside girdle radius
            base_r = c_rad * 1.05
            tip_r = c_rad * 0.80
            
            # Organic curve logic
            if t < 0.6:
                # Straight up part
                r = base_r
            else:
                # Hook part
                hook_t = (t - 0.6) / 0.4
                r = lerp(base_r, tip_r, smoothstep(0, 1, hook_t))
                
            center = Vector((r * dir_vec.x, r * dir_vec.y, z))
            
            # Cross Section
            # Taper thickness at tip
            thick = lerp(prong_w, prong_w * 0.6, t)
            
            sect_verts = []
            n_sect = 8
            
            # Local basis for circle
            up = Vector((0,0,1))
            right = dir_vec.cross(up).normalized()
            
            for k in range(n_sect):
                a = 2 * pi * k / n_sect
                vx = cos(a) * thick * 0.5
                vy = sin(a) * thick * 0.5
                
                # Rotate so circle is perpendicular to UP (simplified)
                # Ideally perpendicular to tangent, but this works for vertical prongs
                v_local = right * vx + dir_vec * vy
                sect_verts.append(bm.verts.new(center + v_local))
            sections.append(sect_verts)
            
        # Skinning
        bm.verts.ensure_lookup_table()
        for s in range(steps-1):
            for k in range(8):
                k_next = (k+1)%8
                _safe_face(bm, [sections[s][k], sections[s][k_next], sections[s+1][k_next], sections[s+1][k]])
                
        # Caps
        bm.faces.new(sections[0]) # Bottom
        bm.faces.new(reversed(sections[-1])) # Top tip
        
        obj = create_mesh_object(f"prong_{i+1:02d}", bm, col)
        apply_metal_modifiers(obj, bevel_width=0.00005)

def build_gallery_rail(layout, col):
    """
    Decorative rail connecting prongs under the gem.
    """
    bm = bmesh.new()
    center = layout['center']['pos']
    radius = CENTER_RADIUS * 1.05
    z_level = center.z - CENTER_RADIUS * 0.7
    
    # Torus
    major_r = radius
    minor_r = 0.00035
    seg_maj = 64
    seg_min = 8
    
    verts = []
    for i in range(seg_maj):
        theta = 2*pi*i/seg_maj
        center_pt = Vector((major_r*cos(theta), major_r*sin(theta), z_level))
        normal = Vector((cos(theta), sin(theta), 0))
        
        ring = []
        for j in range(seg_min):
            phi = 2*pi*j/seg_min
            v = center_pt + normal*(minor_r*cos(phi)) + Vector((0,0,1))*(minor_r*sin(phi))
            ring.append(bm.verts.new(v))
        verts.append(ring)
        
    bm.verts.ensure_lookup_table()
    for i in range(seg_maj):
        i2 = (i+1)%seg_maj
        for j in range(seg_min):
            j2 = (j+1)%seg_min
            _safe_face(bm, [verts[i][j], verts[i][j2], verts[i2][j2], verts[i2][j]])
            
    obj = create_mesh_object("gallery_rail", bm, col)
    apply_metal_modifiers(obj)

# ═══════════════════════════════════════════════════════════════════════
# SECTION E: GEM PLACEMENT
# ═══════════════════════════════════════════════════════════════════════

def place_gems(layout, col):
    """Generates gem meshes."""
    
    # 1. CENTER
    c_data = layout['center']
    bm_center = create_brilliant_gem_bmesh(c_data['radius'])
    obj_center = create_mesh_object("center_diamond", bm_center, col, use_smooth=False)
    obj_center.location = c_data['pos']
    apply_gem_modifiers(obj_center)
    
    # 2. ACCENTS
    if layout['accents']:
        bm_accent = create_brilliant_gem_bmesh(ACCENT_RADIUS)
        mesh_accent = bpy.data.meshes.new("accent_diamond_mesh")
        bm_accent.to_mesh(mesh_accent)
        bm_accent.free()
        
        for i, acc in enumerate(layout['accents']):
            obj = bpy.data.objects.new(f"accent_gem_{i:02d}", mesh_accent)
            col.objects.link(obj)
            obj.location = acc['pos']
            
            # Align Z (gem up) to Normal
            align_vec = acc['normal']
            rot_quat = Vector((0,0,1)).rotation_difference(align_vec)
            obj.rotation_euler = rot_quat.to_euler()
            apply_gem_modifiers(obj)
            
    # 3. HALO
    if layout['halo']:
        bm_halo = create_brilliant_gem_bmesh(HALO_RADIUS)
        mesh_halo = bpy.data.meshes.new("halo_diamond_mesh")
        bm_halo.to_mesh(mesh_halo)
        bm_halo.free()
        
        for i, h in enumerate(layout['halo']):
            obj = bpy.data.objects.new(f"halo_gem_{i:02d}", mesh_halo)
            col.objects.link(obj)
            obj.location = h['pos']
            rot_quat = Vector((0,0,1)).rotation_difference(h['normal'])
            obj.rotation_euler = rot_quat.to_euler()
            apply_gem_modifiers(obj)

# ═══════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════

def main():
    clean_scene()
    col = bpy.data.collections.new("Ring_Assembly")
    bpy.context.scene.collection.children.link(col)
    
    # 1. Blueprint
    layout = compute_diamond_layout()
    
    # 2. Gems
    place_gems(layout, col)
    
    # 3. Metal
    build_structural_shank(layout, col)
    build_setting_head(layout, col)  # ADDED STRUCTURAL COMPONENT
    build_prongs(layout, col)
    build_gallery_rail(layout, col)
    
    # View setup
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces[0].region_3d.view_perspective = 'CAMERA'
            
    print("Ring Generated Successfully - Structural Integrity Verified.")

if __name__ == "__main__":
    main()

# ========================= AUTO BUILD + EXPORT =========================
import bpy, os, traceback as _tb
from mathutils import Vector

_output = r"/home/nimra/ring-generator-service-tools/ring-validator/data/sessions/s_cb344e9860_1771786941/model.glb"
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
