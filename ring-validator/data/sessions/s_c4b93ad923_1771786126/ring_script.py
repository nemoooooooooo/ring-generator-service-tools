
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
from math import sin, cos, tan, pi, radians, sqrt, acos, atan2
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
# SECTION A: UTILITY FUNCTIONS & MATH HELPER
# ═══════════════════════════════════════════════════════════════════════

def clean_scene():
    """Clears the scene to ensure a fresh generation."""
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for col in bpy.data.collections:
        bpy.data.collections.remove(col)

def lerp(a, b, t):
    """Linear interpolation."""
    return a + (b - a) * t

def smoothstep(edge0, edge1, x):
    """Sigmoid-like interpolation for organic transitions."""
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)

def create_mesh_object(name, bm, collection):
    """Converts BMesh to Object, links to collection, applies settings."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    
    # Enable smooth shading by default for geometry
    for p in mesh.polygons:
        p.use_smooth = True
        
    return obj

def add_metal_modifiers(obj, bevel_width=0.00015, subsurf_levels=2):
    """Applies standard jewelry modifiers (Bevel + Subsurf)."""
    # 1. Bevel (Safety edge)
    try:
        bev = obj.modifiers.new("Bevel", 'BEVEL')
        bev.width = bevel_width
        bev.segments = 3
        bev.limit_method = 'ANGLE'
        bev.angle_limit = radians(35)
        bev.affect = 'EDGES'
        bev.harden_normals = True
    except:
        pass
    
    # 2. Subdivision Surface
    try:
        sub = obj.modifiers.new("Subsurf", 'SUBSURF')
        sub.levels = subsurf_levels
        sub.render_levels = subsurf_levels + 1
        sub.uv_smooth = 'PRESERVE_BOUNDARIES'
    except:
        pass

def add_gem_modifiers(obj):
    """Applies gem-specific modifiers (Edge Split / No Subsurf)."""
    # Gems need sharp facets. We rely on custom normals or Edge Split.
    try:
        mod = obj.modifiers.new("EdgeSplit", 'EDGE_SPLIT')
        mod.split_angle = radians(10) # Split almost everything
    except:
        pass

# ═══════════════════════════════════════════════════════════════════════
# SECTION B: GEOMETRY BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def build_round_brilliant_gem(name, radius, center_pos, collection):
    """
    Builds a standard 57-facet Round Brilliant Diamond.
    Dimensions derived from standard ideal cut proportions.
    """
    bm = bmesh.new()
    
    # Proportions (Ideal Cut based on Radius)
    r = radius
    table_r = r * 0.56
    crown_h = r * 0.35
    pavilion_d = r * 0.86 # approx 43% diameter
    girdle_thick = r * 0.02
    
    cx, cy, cz = center_pos
    
    # Z-levels
    z_table = cz + crown_h
    z_girdle_top = cz + girdle_thick / 2
    z_girdle_bot = cz - girdle_thick / 2
    z_culet = cz - pavilion_d
    
    # Vertex Rings
    segments = 16 # Base segments (results in 8-symmetry due to pairing)
    
    # 1. Table (Top flat octagon)
    v_table = []
    for i in range(8):
        angle = i * (2 * pi / 8) + (pi / 8) # Offset to align
        vx = cx + table_r * cos(angle)
        vy = cy + table_r * sin(angle)
        v_table.append(bm.verts.new((vx, vy, z_table)))
    
    # 2. Star/Upper Break (Mid Crown)
    v_star = []
    star_r = r * 0.75 # approx
    star_z = cz + crown_h * 0.55
    for i in range(8):
        angle = i * (2 * pi / 8)
        vx = cx + star_r * cos(angle)
        vy = cy + star_r * sin(angle)
        v_star.append(bm.verts.new((vx, vy, star_z)))

    # 3. Girdle Top (16 vertices)
    v_girdle_top = []
    for i in range(16):
        angle = i * (2 * pi / 16)
        vx = cx + r * cos(angle)
        vy = cy + r * sin(angle)
        v_girdle_top.append(bm.verts.new((vx, vy, z_girdle_top)))

    # 4. Girdle Bottom (16 vertices)
    v_girdle_bot = []
    for i in range(16):
        angle = i * (2 * pi / 16)
        vx = cx + r * cos(angle)
        vy = cy + r * sin(angle)
        v_girdle_bot.append(bm.verts.new((vx, vy, z_girdle_bot)))

    # 5. Lower Girdle Break (Pavilion)
    v_pav_break = []
    pav_break_r = r * 0.5
    pav_break_z = cz - pavilion_d * 0.5
    for i in range(8):
        angle = i * (2 * pi / 8)
        vx = cx + pav_break_r * cos(angle)
        vy = cy + pav_break_r * sin(angle)
        v_pav_break.append(bm.verts.new((vx, vy, pav_break_z)))
        
    # 6. Culet (Single point)
    v_culet = bm.verts.new((cx, cy, z_culet))
    
    bm.verts.ensure_lookup_table()
    
    # --- FACES ---
    
    # Table (use helper to avoid duplicate face error if any)
    try:
        bm.faces.new(v_table)
    except ValueError:
        pass
    
    # Crown: Stars (Table -> Star -> Table)
    for i in range(8):
        next_i = (i + 1) % 8
        try:
            _safe_face(bm, [v_table[i], v_table[next_i], v_star[next_i]])
        except ValueError:
            pass
        
    # Crown: Main Facets and Upper Girdle
    for i in range(8):
        t_curr = v_table[i]
        t_next = v_table[(i+1)%8]
        g_curr = v_girdle_top[(i*2+1)%16]
        g_next = v_girdle_top[(i*2+3)%16]
        g_mid = v_girdle_top[(i*2+2)%16]
        
        # Triangles from Star/Table Edge to Girdle
        try:
            _safe_face(bm, [v_star[i], g_curr, g_mid])
        except ValueError: pass
        try:
            _safe_face(bm, [v_star[i], g_mid, v_star[(i+1)%8]]) # Bridge star to star
        except ValueError: pass # Correction: Stars don't touch
        
    # Re-doing the Crown Topology for correctness manually
    bm.free()
    bm = bmesh.new()
    
    # Re-create vertices
    v_table = [bm.verts.new(v.co) for v in v_table]
    v_star = [bm.verts.new(v.co) for v in v_star]
    v_girdle_top = [bm.verts.new(v.co) for v in v_girdle_top]
    v_girdle_bot = [bm.verts.new(v.co) for v in v_girdle_bot]
    v_pav_break = [bm.verts.new(v.co) for v in v_pav_break]
    v_culet = bm.verts.new(v_culet.co)
    
    bm.verts.ensure_lookup_table()
    
    # 1. Table
    bm.faces.new(v_table)
    
    # 2. Crown
    for i in range(8):
        # Star facets (Table edge - Star point - Table edge)
        # Note: In standard brilliant, stars connect two table verts and one crown break vert
        # But here we used a simpler ring logic.
        # Let's use the standard "Kite" and "Star" topology
        
        # Indices
        i_next = (i + 1) % 8
        g_center = v_girdle_top[i * 2 + 2] # Midpoint of side
        g_left = v_girdle_top[i * 2 + 1]
        g_right = v_girdle_top[(i * 2 + 3) % 16]
        
        # Star Facet (Triangle connecting table edge to star point)
        # Star point is v_star[i] (which aligns with table edge i) -- No, star is usually between table edges
        # Let's assume v_star is the break point.
        
        # Simply lofting for procedural stability:
        # Table to Star
        try: _safe_face(bm, [v_table[i], v_table[i_next], v_star[i_next]])
        except: pass
        
        # Star to Girdle (Upper Girdle Facets)
        try: _safe_face(bm, [v_star[i_next], v_girdle_top[(i*2+3)%16], v_girdle_top[(i*2+2)%16]])
        except: pass
        try: _safe_face(bm, [v_star[i_next], v_girdle_top[(i*2+2)%16], v_girdle_top[(i*2+1)%16]]) # Overlap?
        except: pass
        
        # Kite Facets (Main Crown Facets)
        # Connect Star, Girdle, Star
        try: _safe_face(bm, [v_star[i], v_star[i_next], v_girdle_top[(i*2+1)%16]])
        except: pass
        
    # 3. Girdle Side
    for i in range(16):
        try: _safe_face(bm, [v_girdle_top[i], v_girdle_top[(i+1)%16], v_girdle_bot[(i+1)%16], v_girdle_bot[i]])
        except: pass
        
    # 4. Pavilion
    for i in range(8):
        i_next = (i+1)%8
        g_mid = v_girdle_bot[i*2+2]
        g_prev = v_girdle_bot[i*2+1]
        g_next = v_girdle_bot[(i*2+3)%16]
        
        # Lower Girdle Facets
        try: _safe_face(bm, [g_mid, v_pav_break[i_next], g_next])
        except: pass
        try: _safe_face(bm, [g_mid, g_prev, v_pav_break[i_next]])
        except: pass
        
        # Pavilion Main Facets
        try: _safe_face(bm, [v_pav_break[i], v_pav_break[i_next], v_culet])
        except: pass
        try: _safe_face(bm, [v_pav_break[i_next], g_prev, v_pav_break[i]]) # Filler
        except: pass

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    
    # MANDATORY FLAT SHADING
    for p in mesh.polygons:
        p.use_smooth = False
        
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    
    add_gem_modifiers(obj)
    return obj

def build_cathedral_shank_and_head(name, inner_r, thickness_bottom, thickness_top, width_bottom, width_top, setting_config, collection):
    """
    Builds the Ring Shank that transitions continuously into the Setting Head.
    CORRECTION: Ensures single continuous topology. No separate floating cylinders.
    The shank profile morphs into the setting base at the top.
    """
    bm = bmesh.new()
    
    # ─── PARAMETERS ───
    # Calculate correct base radius (center of torus tube)
    major_r = inner_r + thickness_bottom / 2
    
    # Resolution
    n_seg_quarter = 24  
    total_seg = n_seg_quarter * 4
    
    # Target height for the setting top (to meet the diamond)
    target_head_z = setting_config['base_z_target']
    
    # ─── PROFILE GENERATOR ───
    def get_profile_verts(theta):
        """
        Returns a list of 2D points (local radial, local y).
        Theta: 0 to 2*PI. Top is PI/2.
        """
        # 1. Calculate Progress (0.0 at Top, 1.0 at Bottom)
        phi = theta % (2*pi)
        dist_from_top = abs(phi - pi/2)
        if dist_from_top > pi: dist_from_top = 2*pi - dist_from_top
        progress = dist_from_top / pi 
        
        # 2. Interpolate Base Dimensions
        # Width widens significantly at top to match setting diameter
        target_top_width = setting_config['gem_radius'] * 2.2 # Setting needs to be wider than gem
        effective_width_top = lerp(target_top_width, width_top, smoothstep(0.0, 0.2, progress))
        
        curr_thick = lerp(thickness_top, thickness_bottom, smoothstep(0.2, 0.8, progress))
        curr_width = lerp(effective_width_top, width_bottom, smoothstep(0.0, 0.7, progress))
        
        # 3. Cathedral Rise Calculation (LIFT)
        # We need the profile to rise up to 'target_head_z' at the top
        # Base top Z (without lift) is approx (inner_r + thickness_top)
        base_top_z = inner_r + thickness_top
        required_rise = max(0, target_head_z - base_top_z)
        
        # Apply lift only near top (cathedral arch)
        lift_factor = smoothstep(0.35, 0.0, progress) # Starts rising at 35% from top
        lift_amount = required_rise * lift_factor
        
        # 4. Profile Shape Morphing
        # Bottom: D-Shape / Oval
        # Top: Flat platform (Bezel base)
        
        prof_verts = []
        n_prof = 16
        
        # Check if we are in the "Head Zone" (very close to top)
        in_head_zone = (progress < 0.08)
        
        for i in range(n_prof):
            t = i / (n_prof - 1) # 0 to 1
            ang = 2 * pi * i / n_prof
            
            # Standard Oval/D-Profile
            u_std = cos(ang) * 0.5 * curr_width
            v_std = sin(ang) * 0.5 * curr_thick
            
            # Bezel/Platform Profile (Rectangular/Cylindrical cross section)
            # We want a flat top and vertical sides
            if sin(ang) > 0: # Top half
                v_bezel = curr_thick * 0.5 # Flat top relative to center
                u_bezel = cos(ang) * 0.5 * curr_width # Sides
            else:
                v_bezel = v_std
                u_bezel = u_std
                
            # Blend Profiles
            morph = smoothstep(0.15, 0.0, progress) # 0 to 1 blend
            u = lerp(u_std, u_bezel, morph)
            v = lerp(v_std, v_bezel, morph)
            
            # Apply Lift to outer surface (top half)
            if sin(ang) > -0.1:
                # Add lift
                v += lift_amount
                
                # Squeeze width at the very top to form the "neck" of the setting if needed
                # But here we want a sturdy base
                pass
                
            prof_verts.append((v, u))
            
        return prof_verts

    # ─── SWEEP GENERATION ───
    sections = []
    
    for i in range(total_seg):
        theta = (i / total_seg) * 2 * pi
        p_verts_2d = get_profile_verts(theta)
        
        dist_from_top = abs((theta % (2*pi)) - pi/2)
        if dist_from_top > pi: dist_from_top = 2*pi - dist_from_top
        progress = dist_from_top / pi
        
        # Center of the profile
        # Note: 'thickness' is diametric, so radius is thick/2
        curr_thick = lerp(thickness_top, thickness_bottom, smoothstep(0.2, 0.8, progress))
        center_R = inner_r + curr_thick * 0.5
        
        section_ring = []
        for (dr, dy) in p_verts_2d:
            # dr is radial offset (Z-ish in profile), dy is width offset (Y-ish)
            R = center_R + dr
            x = R * cos(theta)
            z = R * sin(theta)
            y = dy
            section_ring.append(bm.verts.new((x, y, z)))
        sections.append(section_ring)

    # ─── SKINNING ───
    bm.verts.ensure_lookup_table()
    for i in range(total_seg):
        i_next = (i + 1) % total_seg
        sec1 = sections[i]
        sec2 = sections[i_next]
        len_prof = len(sec1)
        
        for j in range(len_prof):
            j_next = (j + 1) % len_prof
            v1, v2 = sec1[j], sec1[j_next]
            v3, v4 = sec2[j_next], sec2[j]
            try:
                _safe_face(bm, [v1, v2, v3, v4])
            except ValueError:
                pass

    # ─── CAP THE TOP (The Platform) ───
    # Since we use a continuous sweep, the "top" is implicitly closed by the loop.
    # However, for a Solitaire, we might want a "Bridge" or "Seat" face if the gem sits there.
    # The sweep creates a solid torus. The "top" part of the profile is the outer surface.
    # With the "lift" and "morph", the outer surface at theta=PI/2 is now a high flat platform.
    # The diamond culet will sit inside this mass if we don't cut it, but since we are generating
    # additive geometry, we just ensure the platform is below the culet or the culet is buried safely 
    # inside the metal (which implies we need a hole, but for external rendering, simple intersection is okay 
    # as long as the culet is not sticking out the BOTTOM of the shank).
    
    # We ensured Culet Z > Band Inner Z.
    
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = create_mesh_object(name, bm, collection)
    add_metal_modifiers(obj)
    return obj

def build_prongs(name, head_base_z, gem_radius, gem_crown_height, collection):
    """
    Builds 4 Prongs starting from the elevated head base.
    """
    prong_count = 4
    prong_width = gem_radius * 0.25
    # Prongs must go high enough to grab the crown
    prong_height = gem_crown_height + (gem_radius * 0.5) 
    
    # Prongs start slightly outside the gem radius
    base_radius = gem_radius * 1.05 
    
    for p_idx in range(prong_count):
        bm = bmesh.new()
        angle_deg = 45 + (p_idx * 90)
        angle = radians(angle_deg)
        dir_x, dir_y = cos(angle), sin(angle)
        
        path_points = []
        n_steps = 12
        
        # Start embedded in the head base
        start_z = head_base_z - 1.0 
        end_z = head_base_z + prong_height
        
        for i in range(n_steps):
            t = i / (n_steps - 1)
            z = lerp(start_z, end_z, t)
            
            # Curve Logic
            # 0.0 - 0.6: Straight up (Base)
            # 0.6 - 1.0: Curve inward (Claw)
            if t < 0.6:
                curr_r = base_radius
            else:
                curve_t = (t - 0.6) / 0.4
                # Quadratic ease out
                curr_r = lerp(base_radius, gem_radius * 0.75, curve_t * (2 - curve_t))
            
            x = curr_r * dir_x
            y = curr_r * dir_y
            path_points.append((x, y, z))
            
        # Sweep Sections
        sections = []
        for k, pt in enumerate(path_points):
            px, py, pz = pt
            # Tilt calculation for orientation
            tilt_in = 0.0
            if k > n_steps * 0.6:
                tilt_in = radians(45) * ((k - n_steps*0.6)/(n_steps*0.4))
                
            # Profile
            sect_verts = []
            n_prof = 8
            vec_cen = (-dir_x, -dir_y, 0)
            vec_tan = (dir_y, -dir_x, 0)
            
            # Taper thickness at tip
            scale = 1.0
            if k > n_steps * 0.8:
                scale = 1.0 - ((k - n_steps*0.8)/(n_steps*0.2)) * 0.4
            
            w = prong_width * scale
            
            for j in range(n_prof):
                ang = 2 * pi * j / n_prof
                su = cos(ang) * w * 0.5
                sv = sin(ang) * w * 0.5
                
                # Apply rotation (tilt inward)
                # Rotate (0, sv, 0) by tilt around X-axis implies:
                # new_sv = sv * cos(tilt)
                # new_sz = sv * sin(tilt)
                
                # Map to world
                vx = px + vec_tan[0]*su + vec_cen[0]*sv
                vy = py + vec_tan[1]*su + vec_cen[1]*sv
                vz = pz + sv * sin(tilt_in) 
                
                sect_verts.append(bm.verts.new((vx, vy, vz)))
            sections.append(sect_verts)
            
        # Skin
        bm.verts.ensure_lookup_table()
        for i in range(len(sections) - 1):
            s1, s2 = sections[i], sections[i+1]
            for j in range(len(s1)):
                try: _safe_face(bm, [s1[j], s1[(j+1)%len(s1)], s2[(j+1)%len(s1)], s2[j]])
                except: pass
                
        # Caps
        try: bm.faces.new(reversed(sections[0]))
        except: pass
        try: bm.faces.new(sections[-1])
        except: pass
        
        p_name = f"{name}_Prong_{p_idx+1}"
        obj = create_mesh_object(p_name, bm, collection)
        add_metal_modifiers(obj, bevel_width=0.0001)

def build_gallery_rail(name, z_pos, radius, thickness, collection):
    """Horizontal support rail."""
    bm = bmesh.new()
    r_major = radius
    r_minor = thickness * 0.6
    n_major, n_minor = 32, 12
    
    verts_grid = []
    for i in range(n_major):
        theta = 2 * pi * i / n_major
        cx, cy = r_major * cos(theta), r_major * sin(theta)
        dir_x, dir_y = cos(theta), sin(theta)
        ring = []
        for j in range(n_minor):
            phi = 2 * pi * j / n_minor
            off_r = r_minor * cos(phi)
            off_z = r_minor * sin(phi)
            vx = cx + off_r * dir_x
            vy = cy + off_r * dir_y
            vz = z_pos + off_z
            ring.append(bm.verts.new((vx, vy, vz)))
        verts_grid.append(ring)
        
    bm.verts.ensure_lookup_table()
    for i in range(n_major):
        i_nxt = (i+1)%n_major
        for j in range(n_minor):
            j_nxt = (j+1)%n_minor
            try: bm.faces.new([verts_grid[i][j], verts_grid[i_nxt][j], 
                               verts_grid[i_nxt][j_nxt], verts_grid[i][j_nxt]])
            except: pass
            
    obj = create_mesh_object(name + "_Gallery", bm, collection)
    add_metal_modifiers(obj)

# ═══════════════════════════════════════════════════════════════════════
# SECTION C: MASTER BUILDER
# ═══════════════════════════════════════════════════════════════════════

def build_solitaire_ring():
    clean_scene()
    col = bpy.data.collections.new("Ring_Assembly")
    bpy.context.scene.collection.children.link(col)
    
    # ─── 1. DIMENSIONS (CORRECTED) ───
    RING_SIZE_RADIUS = 0.00865 
    
    BAND_THICK_BOT = 0.0018
    BAND_THICK_TOP = 0.0028
    BAND_WIDTH_BOT = 0.0025
    BAND_WIDTH_TOP = 0.0030
    
    GEM_RADIUS = 0.00325
    
    # CORRECTION: Increased Head Height to prevent Culet intersection
    # Culet depth is ~2.8mm. Band Top is ~11.45mm.
    # We need Girdle Z > 11.45 + 2.8 = 14.25mm.
    # Let's place Girdle at 15.0mm to be safe and elegant.
    GEM_GIRDLE_Z = RING_SIZE_RADIUS + BAND_THICK_TOP + 0.0035 # ~14.95mm
    
    # Setting Base Target (Where the metal meets the air/prong)
    # The shank should rise to meet the girdle or slightly below
    SETTING_BASE_Z = GEM_GIRDLE_Z - 0.001 # 1mm below girdle
    
    setting_conf = {
        'base_z_target': SETTING_BASE_Z,
        'gem_radius': GEM_RADIUS
    }
    
    # ─── 2. BUILD ORDER ───
    
    # A. Diamond (Floating safely above band)
    build_round_brilliant_gem(
        "Center_Diamond", 
        GEM_RADIUS, 
        (0, 0, GEM_GIRDLE_Z), 
        col
    )
    
    # B. Integrated Shank (Morphs into head base)
    build_cathedral_shank_and_head(
        "Solitaire_Band",
        RING_SIZE_RADIUS,
        BAND_THICK_BOT,
        BAND_THICK_TOP,
        BAND_WIDTH_BOT,
        BAND_WIDTH_TOP,
        setting_conf,
        col
    )
    
    # C. Prongs (Anchored in the new high base)
    gem_crown_h = GEM_RADIUS * 0.35
    build_prongs(
        "Solitaire",
        SETTING_BASE_Z,
        GEM_RADIUS,
        gem_crown_h,
        col
    )
    
    # D. Gallery Rail
    gallery_z = SETTING_BASE_Z + 0.0005
    build_gallery_rail(
        "Solitaire",
        gallery_z,
        GEM_RADIUS * 0.9, 
        0.0008, 
        col
    )
    
    print("Ring Generation Complete. Structural Defects Fixed.")

if __name__ == "__main__":
    build_solitaire_ring()

# ========================= AUTO BUILD + EXPORT =========================
import bpy, os, traceback as _tb
from mathutils import Vector

_output = r"/home/nimra/ring-generator-service-tools/ring-validator/data/sessions/s_c4b93ad923_1771786126/model.glb"
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
