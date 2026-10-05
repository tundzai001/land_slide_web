"""
Generate a high-detail 3D Geotechnical Landslide Monitoring Digital Twin using Blender 5.2 LTS.

Run via:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P scripts/generate_blender_landing.py

Outputs:
  - frontend/assets/blender/landslide_twin.blend
  - frontend/assets/blender/landslide_twin.glb
  - frontend/assets/blender/hero_preview.png
  - frontend/assets/blender/story_preview.png
  - frontend/js/blender-assets.js (bundled base64 GLB + 3D anchor coordinates)
"""

import base64
import json
import math
import random
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector, noise


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BLENDER_DIR = PROJECT_ROOT / "frontend" / "assets" / "blender"
JS_OUT = PROJECT_ROOT / "frontend" / "js" / "blender-assets.js"

# Expanded monumental terrain dimensions (15.6m x 10.8m)
TERRAIN_WIDTH = 15.6
TERRAIN_DEPTH = 10.8


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(
    name: str,
    base_color=(0.06, 0.42, 0.39, 1.0),
    metallic=0.1,
    roughness=0.65,
    emission_color=None,
    emission_strength=0.0,
    alpha=1.0,
    use_vertex_color=False,
):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True

    # Set Blender Solid Viewport display colors so opening .blend in Blender is immediately vibrant!
    em_boost = min(0.38, emission_strength * 0.18) if emission_color else 0.0
    mat.diffuse_color = (
        min(1.0, base_color[0] + (emission_color[0] * em_boost if emission_color else 0.0)),
        min(1.0, base_color[1] + (emission_color[1] * em_boost if emission_color else 0.0)),
        min(1.0, base_color[2] + (emission_color[2] * em_boost if emission_color else 0.0)),
        alpha if alpha < 1.0 else (base_color[3] if len(base_color) > 3 else 1.0),
    )
    mat.metallic = metallic
    mat.roughness = roughness

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = base_color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
        if emission_color and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (*emission_color[:3], 1.0)
            bsdf.inputs["Emission Strength"].default_value = emission_strength
        if use_vertex_color:
            vc_node = nodes.new(type="ShaderNodeVertexColor")
            vc_node.layer_name = "Col"
            links.new(vc_node.outputs["Color"], bsdf.inputs["Base Color"])
    if alpha < 1.0:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        elif hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
    return mat


def road_center_x(y: float) -> float:
    """Curved mountain highway centerline X for y in [-5.4, 5.4]."""
    ny = y / (TERRAIN_DEPTH * 0.5)
    return 2.65 + 0.24 * math.sin(ny * 1.5)


def road_dx_dy(y: float) -> float:
    """Derivative dx/dy of the curved mountain highway centerline."""
    half_d = TERRAIN_DEPTH * 0.5
    return 0.24 * (1.5 / half_d) * math.cos((y / half_d) * 1.5)


def terrain_height(x: float, y: float) -> float:
    """
    Compute realistic expanded mountain slope height in Blender coordinates:
      x in [-7.8, 7.8]: slope descends from -X (high alpine crest) to +X (highway & Data Center plateau)
      y in [-5.4, 5.4]: front cutaway (-Y) to back ridge (+Y)
    """
    nx = x / (TERRAIN_WIDTH * 0.5)
    ny = y / (TERRAIN_DEPTH * 0.5)

    # Primary alpine mountain slope profile
    slope = -1.92 * nx + 0.42 * math.cos(nx * 1.35) + 0.28 * ny

    # Valley bench for 2-lane mountain highway around x ~ 2.65
    rc = road_center_x(y)
    dist_road = abs(x - rc)
    if dist_road < 1.05:
        t = dist_road / 1.05
        smooth = t * t * (3.0 - 2.0 * t)
        road_elev = -0.58 + 0.08 * ny
        slope = road_elev * (1.0 - smooth) + slope * smooth

    # Broad Eastern Command & Data Center Plateau (+X > 3.35)
    if x > 3.35:
        ridge_t = min(1.0, (x - 3.35) / 2.65)
        plateau_blend = ridge_t * ridge_t * (3.0 - 2.0 * ridge_t)
        slope += 1.05 * plateau_blend

    # Flatten the Data Center Campus terrace around (5.15, -0.65) so imported 3D buildings sit flush
    dx_ops = (x - 5.15) / 2.25
    dy_ops = (y - (-0.45)) / 2.85
    dist_ops = math.sqrt(dx_ops * dx_ops + dy_ops * dy_ops)
    ops_damp = min(1.0, max(0.08, (dist_ops - 0.55) / 0.65)) if x > 3.4 else 1.0

    # Multi-fractal geological ridge detail + subtle drainage gully
    n1 = noise.noise(Vector((x * 0.36 + 3.1, y * 0.36 + 1.7, 0.5)))
    n2 = noise.noise(Vector((x * 0.82 - 2.4, y * 0.82 + 4.2, 1.3))) * 0.32
    n3 = noise.noise(Vector((x * 1.65 + 0.7, y * 1.65 - 1.2, 2.7))) * 0.08
    road_damp = min(1.0, max(0.05, (dist_road - 0.42) / 0.62)) * ops_damp

    # Eroded mountain stream gully on the upper-back slope (y around 1.85)
    stream_y = 1.85 - 0.26 * nx
    dist_stream = abs(y - stream_y)
    gully = 0.0
    if x < 1.9 and dist_stream < 0.68:
        gt = 1.0 - (dist_stream / 0.68)
        gully = -0.22 * (gt * gt) * road_damp

    detail = (n1 * 0.48 + n2 + n3) * road_damp + gully
    raw_h = slope + detail
    terrace = math.sin(raw_h * 4.8) * 0.045 * road_damp
    return raw_h + terrace


def link_obj(obj, parent=None):
    if obj.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def add_cylinder(bm, center, r_bot, r_top, height, segs=14, rot_euler=(0.0, 0.0, 0.0), cap_ends=True):
    mat = (
        Matrix.Translation(center)
        @ Euler(rot_euler, "XYZ").to_matrix().to_4x4()
    )
    bmesh.ops.create_cone(
        bm,
        cap_ends=cap_ends,
        cap_tris=False,
        segments=segs,
        radius1=r_bot,
        radius2=r_top,
        depth=height,
        matrix=mat,
    )


def add_box(bm, center, size_xyz, rot_euler=(0.0, 0.0, 0.0)):
    mat = (
        Matrix.Translation(center)
        @ Euler(rot_euler, "XYZ").to_matrix().to_4x4()
        @ Matrix.Diagonal((*size_xyz, 1.0))
    )
    bmesh.ops.create_cube(bm, size=1.0, matrix=mat)


def add_strut(bm, p0, p1, radius=0.016, segs=6):
    v0 = Vector(p0)
    v1 = Vector(p1)
    diff = v1 - v0
    if diff.length < 1e-4:
        return
    mid = (v0 + v1) * 0.5
    rot_q = diff.to_track_quat("Z", "Y")
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        segments=segs,
        radius1=radius,
        radius2=radius,
        depth=diff.length,
        matrix=Matrix.Translation(mid) @ rot_q.to_matrix().to_4x4(),
    )


def lerp_color(c0, c1, t):
    t = max(0.0, min(1.0, t))
    return (
        c0[0] + (c1[0] - c0[0]) * t,
        c0[1] + (c1[1] - c0[1]) * t,
        c0[2] + (c1[2] - c0[2]) * t,
        1.0,
    )


def build_geological_block(root, mats):
    """Build expanded 15.6m x 10.8m sculpted mountain terrain with vertex colors, 3-layer cutaway + pedestal, slip zone, and groundwater."""
    nx, ny = 96, 70
    width, depth = TERRAIN_WIDTH, TERRAIN_DEPTH
    base_z = -2.45

    # 1. High-Res Top Terrain Surface Mesh with Biome Vertex Colors
    mesh_top = bpy.data.meshes.new("TerrainSurfaceMesh")
    bm = bmesh.new()
    color_layer = bm.loops.layers.color.new("Col")

    grid_verts = [[None] * ny for _ in range(nx)]
    for i in range(nx):
        x = -width / 2 + (i / (nx - 1)) * width
        for j in range(ny):
            y = -depth / 2 + (j / (ny - 1)) * depth
            z = terrain_height(x, y)
            grid_verts[i][j] = bm.verts.new((x, y, z))

    for i in range(nx - 1):
        for j in range(ny - 1):
            f = bm.faces.new(
                (grid_verts[i][j], grid_verts[i + 1][j], grid_verts[i + 1][j + 1], grid_verts[i][j + 1])
            )
            f.smooth = True

    bm.normal_update()

    # Paint rich biome vertex colors based on elevation, slope steepness, and landslide scar proximity
    c_high_forest = (0.04, 0.34, 0.26, 1.0)
    c_mid_meadow = (0.10, 0.48, 0.38, 1.0)
    c_steep_rock = (0.20, 0.32, 0.34, 1.0)
    c_scar_soil = (0.46, 0.31, 0.16, 1.0)
    c_valley = (0.06, 0.26, 0.25, 1.0)

    for face in bm.faces:
        for loop in face.loops:
            v = loop.vert
            vx, vy, vz = v.co.x, v.co.y, v.co.z
            elev_t = (vz + 1.25) / 3.7
            col = lerp_color(c_valley, c_mid_meadow, min(1.0, elev_t * 1.3))
            if elev_t > 0.55:
                col = lerp_color(col, c_high_forest, (elev_t - 0.55) / 0.45)

            steepness = 1.0 - max(0.0, v.normal.z)
            if steepness > 0.24:
                col = lerp_color(col, c_steep_rock, min(1.0, (steepness - 0.24) * 2.8))

            dx_s = (vx - (-1.15)) / 2.85
            dy_s = (vy - (-0.30)) / 2.45
            dist_scar = math.sqrt(dx_s * dx_s + dy_s * dy_s)
            if dist_scar < 1.15:
                scar_w = max(0.0, 1.0 - dist_scar / 1.15) ** 1.4
                col = lerp_color(col, c_scar_soil, scar_w * 0.75)

            loop[color_layer] = col

    bm.to_mesh(mesh_top)
    bm.free()

    terrain_obj = bpy.data.objects.new("TerrainSurface", mesh_top)
    terrain_obj.data.materials.append(mats["terrain_surface"])
    link_obj(terrain_obj, root)

    # 2. Multi-Layer Geological Cutaway Walls + Architectural Museum Pedestal
    mesh_soil_wall = bpy.data.meshes.new("SoilCutawayMesh")
    bm_soil = bmesh.new()
    mesh_rock_wall = bpy.data.meshes.new("BedrockCutawayMesh")
    bm_rock = bmesh.new()

    def add_wall_strip(perimeter_pts):
        for k in range(len(perimeter_pts) - 1):
            x0, y0 = perimeter_pts[k]
            x1, y1 = perimeter_pts[k + 1]
            z_top0 = terrain_height(x0, y0)
            z_top1 = terrain_height(x1, y1)
            z_mid0 = max(base_z + 0.48, z_top0 - 0.90 - 0.15 * math.sin(x0 * 0.8))
            z_mid1 = max(base_z + 0.48, z_top1 - 0.90 - 0.15 * math.sin(x1 * 0.8))

            sv1 = bm_soil.verts.new((x0, y0, z_mid0))
            sv2 = bm_soil.verts.new((x1, y1, z_mid1))
            sv3 = bm_soil.verts.new((x1, y1, z_top1))
            sv4 = bm_soil.verts.new((x0, y0, z_top0))
            bm_soil.faces.new((sv1, sv2, sv3, sv4))

            rv1 = bm_rock.verts.new((x0, y0, base_z))
            rv2 = bm_rock.verts.new((x1, y1, base_z))
            rv3 = bm_rock.verts.new((x1, y1, z_mid1))
            rv4 = bm_rock.verts.new((x0, y0, z_mid0))
            bm_rock.faces.new((rv1, rv2, rv3, rv4))

    front_edge = [(-width / 2 + (i / (nx - 1)) * width, -depth / 2) for i in range(nx)]
    right_edge = [(width / 2, -depth / 2 + (j / (ny - 1)) * depth) for j in range(ny)]
    back_edge = [(width / 2 - (i / (nx - 1)) * width, depth / 2) for i in range(nx)]
    left_edge = [(-width / 2, depth / 2 - (j / (ny - 1)) * depth) for j in range(ny)]

    for edge in (front_edge, right_edge, back_edge, left_edge):
        add_wall_strip(edge)

    # Embedded rock boulders & strata striations along front cutaway wall
    rng = random.Random(42)
    for _ in range(38):
        bx = rng.uniform(-width / 2 + 0.5, width / 2 - 0.5)
        bz_top = terrain_height(bx, -depth / 2)
        bz = rng.uniform(base_z + 0.3, bz_top - 0.25)
        br = rng.uniform(0.07, 0.18)
        bmesh.ops.create_icosphere(
            bm_soil if bz > bz_top - 0.90 else bm_rock,
            subdivisions=1,
            radius=br,
            matrix=Matrix.Translation((bx, -depth / 2 - 0.012, bz)) @ Matrix.Diagonal((1.4, 0.35, 0.75, 1.0)),
        )

    # Architectural Diorama Base Plinth & Depth Scale Tick Marks
    add_box(bm_rock, (0.0, 0.0, base_z - 0.14), (width + 0.32, depth + 0.32, 0.28))
    add_box(bm_rock, (0.0, 0.0, base_z - 0.32), (width + 0.64, depth + 0.64, 0.14))
    for tick_i in range(31):
        tx = -width / 2 + tick_i * 0.52
        if tx <= width / 2:
            add_box(bm_soil, (tx, -depth / 2 - 0.17, base_z - 0.14), (0.030, 0.045, 0.20 if tick_i % 2 == 0 else 0.11))

    bmesh.ops.remove_doubles(bm_soil, verts=bm_soil.verts, dist=0.001)
    bm_soil.normal_update()
    bm_soil.to_mesh(mesh_soil_wall)
    bm_soil.free()

    bmesh.ops.remove_doubles(bm_rock, verts=bm_rock.verts, dist=0.001)
    bm_rock.normal_update()
    bm_rock.to_mesh(mesh_rock_wall)
    bm_rock.free()

    soil_obj = bpy.data.objects.new("SoilStrataCutaway", mesh_soil_wall)
    soil_obj.data.materials.append(mats["soil_strata"])
    link_obj(soil_obj, root)

    rock_obj = bpy.data.objects.new("BedrockCutaway", mesh_rock_wall)
    rock_obj.data.materials.append(mats["bedrock_strata"])
    link_obj(rock_obj, root)

    # 3. Smooth Elliptical Radial Landslide Slip Surface + Fractured Unstable Wedge
    cx, cy = -1.15, -0.30
    rx, ry = 2.75, 2.35
    rings, segs = 18, 52

    mesh_slip = bpy.data.meshes.new("SlipSurfaceMesh")
    bm_slip = bmesh.new()
    mesh_wedge = bpy.data.meshes.new("UnstableWedgeMesh")
    bm_wedge = bmesh.new()
    wedge_col_layer = bm_wedge.loops.layers.color.new("Col")

    slip_center_z = terrain_height(cx, cy) - 0.96
    wedge_center_z = terrain_height(cx, cy) + 0.040
    v_slip_center = bm_slip.verts.new((cx, cy, slip_center_z))
    v_wedge_center = bm_wedge.verts.new((cx, cy, wedge_center_z))

    slip_rings = []
    wedge_rings = []
    for r_idx in range(1, rings + 1):
        r_frac = r_idx / rings
        s_ring = []
        w_ring = []
        for s_idx in range(segs):
            theta = (s_idx / segs) * math.pi * 2.0
            organic = 1.0 + 0.08 * math.sin(theta * 3.0 + 0.5) + 0.05 * math.cos(theta * 2.0)
            px = cx + math.cos(theta) * rx * r_frac * organic
            py = cy + math.sin(theta) * ry * r_frac * organic
            surf_z = terrain_height(px, py)
            bowl_depth = 0.96 * (1.0 - (r_frac ** 1.6))
            s_ring.append(bm_slip.verts.new((px, py, surf_z - bowl_depth - 0.02)))

            slump_step = 0.054 * math.sin(r_frac * 14.0 + math.cos(theta) * 2.0) * (1.0 - r_frac)
            w_ring.append(bm_wedge.verts.new((px, py, surf_z + 0.036 * (1.0 - 0.35 * r_frac) + slump_step)))
        slip_rings.append(s_ring)
        wedge_rings.append(w_ring)

    for s_idx in range(segs):
        nxt = (s_idx + 1) % segs
        f_s = bm_slip.faces.new((v_slip_center, slip_rings[0][s_idx], slip_rings[0][nxt]))
        f_s.smooth = True
        f_w = bm_wedge.faces.new((v_wedge_center, wedge_rings[0][s_idx], wedge_rings[0][nxt]))
        f_w.smooth = True

    for r_idx in range(rings - 1):
        for s_idx in range(segs):
            nxt = (s_idx + 1) % segs
            f_s = bm_slip.faces.new(
                (slip_rings[r_idx][s_idx], slip_rings[r_idx + 1][s_idx], slip_rings[r_idx + 1][nxt], slip_rings[r_idx][nxt])
            )
            f_s.smooth = True
            f_w = bm_wedge.faces.new(
                (wedge_rings[r_idx][s_idx], wedge_rings[r_idx + 1][s_idx], wedge_rings[r_idx + 1][nxt], wedge_rings[r_idx][nxt])
            )
            f_w.smooth = True

    for face in bm_wedge.faces:
        for loop in face.loops:
            vx, vy, vz = loop.vert.co
            n_val = 0.5 + 0.5 * noise.noise(Vector((vx * 2.0, vy * 2.0, vz)))
            crack_band = math.sin((vx - cx) * 6.5 + math.sin(vy * 1.8) * 0.8)
            base_c = lerp_color((0.36, 0.27, 0.16, 1.0), (0.10, 0.46, 0.36, 1.0), n_val)
            if crack_band > 0.80 and vx < cx + 1.15:
                base_c = lerp_color(base_c, (0.92, 0.44, 0.08, 1.0), (crack_band - 0.80) / 0.20)
            loop[wedge_col_layer] = base_c

    # Sleek Precision Crown Scarp Perimeter Ring around the unstable wedge
    for s_idx in range(segs):
        nxt = (s_idx + 1) % segs
        v0 = wedge_rings[-1][s_idx].co
        v1 = wedge_rings[-1][nxt].co
        rad = 0.026 if v0.x < cx else 0.016
        add_strut(bm_slip, v0 + Vector((0, 0, 0.018)), v1 + Vector((0, 0, 0.018)), radius=rad, segs=6)

    # Front cutaway slip plane indicator band
    for i in range(28):
        fx0 = -3.95 + (i / 28) * 5.2
        fx1 = -3.95 + ((i + 1) / 28) * 5.2
        fy = -depth / 2 - 0.030
        norm0 = (fx0 - (-1.35)) / 2.6
        norm1 = (fx1 - (-1.35)) / 2.6
        fz0 = terrain_height(fx0, -depth / 2) - 0.24 - 0.68 * max(0.0, 1.0 - norm0 * norm0)
        fz1 = terrain_height(fx1, -depth / 2) - 0.24 - 0.68 * max(0.0, 1.0 - norm1 * norm1)
        sv1 = bm_slip.verts.new((fx0, fy, fz0 - 0.052))
        sv2 = bm_slip.verts.new((fx1, fy, fz1 - 0.052))
        sv3 = bm_slip.verts.new((fx1, fy, fz1 + 0.052))
        sv4 = bm_slip.verts.new((fx0, fy, fz0 + 0.052))
        bm_slip.faces.new((sv1, sv2, sv3, sv4))

    bm_slip.normal_update()
    bm_slip.to_mesh(mesh_slip)
    bm_slip.free()

    bm_wedge.normal_update()
    bm_wedge.to_mesh(mesh_wedge)
    bm_wedge.free()

    slip_obj = bpy.data.objects.new("SlipSurface", mesh_slip)
    slip_obj.data.materials.append(mats["slip_surface"])
    link_obj(slip_obj, root)

    wedge_obj = bpy.data.objects.new("UnstableWedge", mesh_wedge)
    wedge_obj.data.materials.append(mats["unstable_wedge"])
    link_obj(wedge_obj, root)

    # 4. Subsurface Groundwater Table Mesh + Front Cutaway Aquifer Band
    mesh_water = bpy.data.meshes.new("GroundwaterTableMesh")
    bm_water = bmesh.new()
    wx_n, wy_n = 38, 30
    wt_verts = [[None] * wy_n for _ in range(wx_n)]
    for i in range(wx_n):
        x = -width / 2 + 0.08 + (i / (wx_n - 1)) * (width - 0.16)
        for j in range(wy_n):
            y = -depth / 2 + 0.08 + (j / (wy_n - 1)) * (depth - 0.16)
            surf_z = terrain_height(x, y)
            water_z = max(base_z + 0.45, surf_z - 0.94 + 0.12 * math.sin(x * 0.7 + y * 0.6))
            wt_verts[i][j] = bm_water.verts.new((x, y, water_z))
    for i in range(wx_n - 1):
        for j in range(wy_n - 1):
            f = bm_water.faces.new(
                (wt_verts[i][j], wt_verts[i + 1][j], wt_verts[i + 1][j + 1], wt_verts[i][j + 1])
            )
            f.smooth = True

    for i in range(wx_n - 1):
        x0 = wt_verts[i][0].co.x
        x1 = wt_verts[i + 1][0].co.x
        fy = -depth / 2 - 0.022
        wt_z0 = wt_verts[i][0].co.z
        wt_z1 = wt_verts[i + 1][0].co.z
        bot_z0 = max(base_z + 0.14, wt_z0 - 0.58)
        bot_z1 = max(base_z + 0.14, wt_z1 - 0.58)
        v_b0 = bm_water.verts.new((x0, fy, bot_z0))
        v_b1 = bm_water.verts.new((x1, fy, bot_z1))
        v_t1 = bm_water.verts.new((x1, fy, wt_z1))
        v_t0 = bm_water.verts.new((x0, fy, wt_z0))
        bm_water.faces.new((v_b0, v_b1, v_t1, v_t0))

    bm_water.normal_update()
    bm_water.to_mesh(mesh_water)
    bm_water.free()

    water_obj = bpy.data.objects.new("GroundwaterTable", mesh_water)
    water_obj.data.materials.append(mats["groundwater"])
    link_obj(water_obj, root)


def build_mountain_road_and_wall(root, mats):
    """Build expanded 10.8m mountain highway with curbs, lane dashes, guardrails, streetlamps, tie-back retaining wall, and rockfall gallery."""
    mesh_road = bpy.data.meshes.new("MountainRoadMesh")
    bm = bmesh.new()
    steps = 64
    half_w = 0.56
    depth = TERRAIN_DEPTH

    left_verts = []
    right_verts = []
    for j in range(steps):
        y = -depth / 2 + (j / (steps - 1)) * depth
        rc = road_center_x(y)
        rz = terrain_height(rc, y) + 0.026
        left_verts.append(bm.verts.new((rc - half_w, y, rz)))
        right_verts.append(bm.verts.new((rc + half_w, y, rz)))

    for j in range(steps - 1):
        bm.faces.new((left_verts[j], right_verts[j], right_verts[j + 1], left_verts[j + 1]))

    bm.normal_update()
    bm.to_mesh(mesh_road)
    bm.free()

    road_obj = bpy.data.objects.new("MountainRoad", mesh_road)
    road_obj.data.materials.append(mats["asphalt"])
    link_obj(road_obj, root)

    # Dashed Center Line + Edge Lines + Guardrail Posts + Streetlights
    mesh_markings = bpy.data.meshes.new("RoadMarkingsMesh")
    bm_m = bmesh.new()
    for j in range(steps - 1):
        y0 = -depth / 2 + (j / (steps - 1)) * depth
        y1 = -depth / 2 + ((j + 1) / (steps - 1)) * depth
        ym = 0.5 * (y0 + y1)
        rc = road_center_x(ym)
        rz = terrain_height(rc, ym) + 0.034
        if j % 2 == 0:
            add_box(bm_m, (rc, ym, rz), (0.040, (depth / steps) * 0.65, 0.009))
        gx = rc + half_w - 0.04
        add_box(bm_m, (gx, ym, rz + 0.072), (0.026, (depth / steps) * 1.05, 0.040))
        if j % 3 == 0:
            add_cylinder(bm_m, (gx + 0.016, ym, rz + 0.045), 0.018, 0.018, 0.13, segs=6)
        if j in (4, 12, 20, 28, 36, 44, 52, 60):
            lx = rc + half_w + 0.07
            add_cylinder(bm_m, (lx, ym, rz + 0.32), 0.020, 0.015, 0.64, segs=8)
            add_box(bm_m, (lx - 0.10, ym, rz + 0.63), (0.22, 0.048, 0.030))

    bm_m.normal_update()
    bm_m.to_mesh(mesh_markings)
    bm_m.free()
    mark_obj = bpy.data.objects.new("RoadMarkings", mesh_markings)
    mark_obj.data.materials.append(mats["steel_housing"])
    link_obj(mark_obj, road_obj)

    # Uphill Tie-Back Anchored Retaining Wall + Cantilevered Concrete Rockfall Protection Gallery + Sabo Check Dam
    mesh_wall = bpy.data.meshes.new("RetainingWallMesh")
    bm_w = bmesh.new()
    for j in range(steps - 1):
        y0 = -depth / 2 + (j / (steps - 1)) * depth
        y1 = -depth / 2 + ((j + 1) / (steps - 1)) * depth
        rc0 = road_center_x(y0) - half_w - 0.04
        rc1 = road_center_x(y1) - half_w - 0.04
        z0 = terrain_height(rc0, y0)
        z1 = terrain_height(rc1, y1)
        h = 0.44
        v1 = bm_w.verts.new((rc0, y0, z0))
        v2 = bm_w.verts.new((rc1, y1, z1))
        v3 = bm_w.verts.new((rc1 - 0.10, y1, z1 + h))
        v4 = bm_w.verts.new((rc0 - 0.10, y0, z0 + h))
        bm_w.faces.new((v1, v2, v3, v4))
        if j % 3 == 0:
            ym = 0.5 * (y0 + y1)
            rcm = 0.5 * (rc0 + rc1)
            zm = 0.5 * (z0 + z1)
            add_box(bm_w, (rcm - 0.035, ym, zm + h * 0.5), (0.13, 0.075, h), rot_euler=(0, -0.22, 0))
            add_cylinder(bm_w, (rcm + 0.012, ym, zm + h * 0.55), 0.044, 0.030, 0.048, segs=8, rot_euler=(0, math.pi / 2, 0))

    # Monumental Reinforced Concrete Rockfall Protection Gallery over upper highway y in [0.85, 2.85]
    gal_steps = 10
    for g_i in range(gal_steps):
        gy = 0.85 + (g_i / (gal_steps - 1)) * 2.00
        grc = road_center_x(gy)
        grz = terrain_height(grc, gy) + 0.026
        add_box(bm_w, (grc + half_w - 0.06, gy, grz + 0.26), (0.070, 0.090, 0.52))
        add_box(bm_w, (grc - half_w - 0.09, gy, grz + 0.30), (0.15, 0.11, 0.60))
        add_box(bm_w, (grc - 0.04, gy, grz + 0.54), (half_w * 2.28, 0.13, 0.085), rot_euler=(0, 0.12, 0))
    for g_i in range(gal_steps - 1):
        gy0 = 0.85 + (g_i / (gal_steps - 1)) * 2.00
        gy1 = 0.85 + ((g_i + 1) / (gal_steps - 1)) * 2.00
        gym = 0.5 * (gy0 + gy1)
        grc = road_center_x(gym)
        grz = terrain_height(grc, gym) + 0.026
        add_box(bm_w, (grc - 0.04, gym, grz + 0.58), (half_w * 2.34, (2.00 / (gal_steps - 1)) * 1.05, 0.070), rot_euler=(0, 0.12, 0))

    # Stepped Concrete Sabo Check Dam across upper mountain gully (-2.35, 1.85)
    sx, sy = -2.35, 1.85
    sz = terrain_height(sx, sy)
    add_box(bm_w, (sx, sy, sz + 0.16), (0.26, 1.48, 0.38), rot_euler=(0, 0.18, 0.12))
    add_box(bm_w, (sx - 0.12, sy - 0.60, sz + 0.26), (0.36, 0.38, 0.48), rot_euler=(0, 0.15, 0.12))
    add_box(bm_w, (sx - 0.12, sy + 0.60, sz + 0.26), (0.36, 0.38, 0.48), rot_euler=(0, 0.15, 0.12))
    for slit_y in (-0.28, -0.10, 0.10, 0.28):
        add_cylinder(bm_w, (sx + 0.02, sy + slit_y, sz + 0.36), 0.026, 0.026, 0.26, segs=8)

    bm_w.normal_update()
    bm_w.to_mesh(mesh_wall)
    bm_w.free()

    wall_obj = bpy.data.objects.new("RetainingWall", mesh_wall)
    wall_obj.data.materials.append(mats["concrete"])
    link_obj(wall_obj, root)


def load_hardware_templates(mats):
    """Pre-load reusable real 3D GLB hardware templates for hill stations and the Operations Control Room."""
    templates = {}
    specs = [
        (
            "hex_pad",
            "hex_pad_small.glb",
            (0.148, 0.148, 0.140),
            {"HexagonSmall": mats["concrete"]},
        ),
        (
            "info_panel",
            "info_panel.glb",
            (0.095, 0.095, 0.095),
            {"TeleporterRoot": mats["ops_obsidian"], "Teleporter": mats["ops_glass_cyan"]},
        ),
        (
            "ptz_camera",
            "ptz_camera.glb",
            (0.088, 0.088, 0.088),
            {"Iron_01": mats["heli_white"], "Iron_02": mats["ops_obsidian"], "camera_01": mats["imu_glow"]},
        ),
        (
            "mini_pc",
            "mini_pc.glb",
            (0.105, 0.105, 0.135),
            {"Shared_Black_Matte_Mat": mats["ops_obsidian"], "Colony_Marbres_01_Mat": mats["ring_lime"]},
        ),
    ]
    for key, fname, sc, mmap in specs:
        obj = import_single_glb_mesh(fname, f"HwTmpl_{key}", scale_xyz=sc, mat_map=mmap)
        if obj:
            templates[key] = obj
    return templates


def cleanup_hardware_templates(templates):
    """Remove temporary hardware template objects after cloning."""
    if not templates:
        return
    for tmpl in list(templates.values()):
        if tmpl and tmpl.name in bpy.data.objects:
            bpy.data.objects.remove(tmpl, do_unlink=True)


def spawn_hw_instance(templates, key: str, inst_name: str, parent, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    """Instantiate a pre-loaded 3D GLB hardware mesh under parent."""
    tmpl = templates.get(key) if templates else None
    if not tmpl:
        return None
    inst = bpy.data.objects.new(inst_name, tmpl.data.copy())
    inst.rotation_mode = "XYZ"
    inst.location = loc
    inst.rotation_euler = rot
    inst.scale = scale
    link_obj(inst, parent)
    return inst


def build_gnss_station(name: str, x: float, y: float, root, mats, is_base=False, templates=None):
    """Build an ultra-detailed industrial GNSS RTK field station with real 3D hexagonal platform, info terminal, edge-AI logger, PTZ slope camera, 4-leg steel lattice tower, dual solar wings, and multi-fin choke-ring geodetic radome."""
    z = terrain_height(x, y)
    station_grp = bpy.data.objects.new(name, None)
    station_grp.empty_display_type = "PLAIN_AXES"
    station_grp.location = (x, y, z)
    link_obj(station_grp, root)

    # 1. Real 3D Hexagonal Armored Foundation Pad (hex_pad_small.glb) + Telemetry Terminal + Edge-AI Logger + PTZ Camera
    pad_scale = 1.12 if is_base else 1.0
    spawn_hw_instance(
        templates, "hex_pad", f"{name}_HexPad", station_grp,
        loc=(0.0, 0.0, -0.02), rot=(0.0, 0.0, 0.0), scale=(pad_scale, pad_scale, 1.0)
    )
    spawn_hw_instance(
        templates, "info_panel", f"{name}_InfoPanel", station_grp,
        loc=(-0.23 * pad_scale, -0.19 * pad_scale, 0.13), rot=(0.0, 0.0, -0.35), scale=(1.0, 1.0, 1.0)
    )
    spawn_hw_instance(
        templates, "mini_pc", f"{name}_EdgeLogger", station_grp,
        loc=(0.24 * pad_scale, -0.14 * pad_scale, 0.24), rot=(0.0, 0.0, 0.45), scale=(1.0, 1.0, 1.0)
    )

    mast_h = 1.08 if not is_base else 1.32
    top_z = 0.22 + mast_h
    spawn_hw_instance(
        templates, "ptz_camera", f"{name}_PTZCamera", station_grp,
        loc=(0.17, -0.15, top_z - 0.26), rot=(0.0, 0.0, -0.45), scale=(0.95, 0.95, 0.95)
    )

    # 2. Tapered 4-Column Cross-Braced Steel Lattice Geodetic Tower + NEMA Cabinet + Perimeter Safety Rails
    mesh_body = bpy.data.meshes.new(f"{name}_BodyMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, 0.06), 0.36 * pad_scale, 0.32 * pad_scale, 0.14, segs=12)
    add_cylinder(bm, (0, 0, 0.18), 0.18, 0.14, 0.16, segs=16)

    # Hexagonal perimeter safety bollards and dual tubular guardrails
    fence_r = 0.36 * pad_scale
    fence_pts = [
        (math.cos(k * math.pi / 3.0) * fence_r, math.sin(k * math.pi / 3.0) * fence_r)
        for k in range(6)
    ]
    for fx, fy in fence_pts:
        add_cylinder(bm, (fx, fy, 0.21), 0.015, 0.015, 0.24, segs=8)
    for k in range(6):
        if k == 4:
            # Leave front walk-in gap on the hexagonal stair side
            continue
        p0 = fence_pts[k]
        p1 = fence_pts[(k + 1) % 6]
        add_strut(bm, (p0[0], p0[1], 0.30), (p1[0], p1[1], 0.30), radius=0.010, segs=6)
        add_strut(bm, (p0[0], p0[1], 0.21), (p1[0], p1[1], 0.21), radius=0.008, segs=6)

    # 4-Column Tapered Lattice Tower with 5 Horizontal Frame Tiers & Diagonal X-Bracing
    tiers = 5
    r_bot_tower = 0.095
    r_top_tower = 0.048
    corners = [
        (math.cos(a) * 1.0, math.sin(a) * 1.0)
        for a in (math.pi * 0.25, math.pi * 0.75, math.pi * 1.25, math.pi * 1.75)
    ]
    for cx_u, cy_u in corners:
        p_b = (cx_u * r_bot_tower, cy_u * r_bot_tower, 0.20)
        p_t = (cx_u * r_top_tower, cy_u * r_top_tower, top_z)
        add_strut(bm, p_b, p_t, radius=0.013, segs=8)

    for t_i in range(tiers):
        f0 = t_i / tiers
        f1 = (t_i + 1) / tiers
        z0 = 0.20 + mast_h * f0
        z1 = 0.20 + mast_h * f1
        r0 = r_bot_tower * (1.0 - f0) + r_top_tower * f0
        r1 = r_bot_tower * (1.0 - f1) + r_top_tower * f1
        for c_i in range(4):
            c_next = (c_i + 1) % 4
            p00 = (corners[c_i][0] * r0, corners[c_i][1] * r0, z0)
            p10 = (corners[c_next][0] * r0, corners[c_next][1] * r0, z0)
            p01 = (corners[c_i][0] * r1, corners[c_i][1] * r1, z1)
            p11 = (corners[c_next][0] * r1, corners[c_next][1] * r1, z1)
            add_strut(bm, p00, p10, radius=0.008, segs=6)
            add_strut(bm, p00, p11, radius=0.007, segs=6)
            add_strut(bm, p10, p01, radius=0.007, segs=6)

    # Central stainless coaxial riser tube + NEMA RTU pedestal + dual LoRa/UHF antennas + PTZ outrigger arm
    add_cylinder(bm, (0, 0, 0.20 + mast_h * 0.5), 0.022, 0.018, mast_h, segs=12)
    add_box(bm, (0.21 * pad_scale, -0.14 * pad_scale, 0.19), (0.14, 0.16, 0.14))
    add_box(bm, (0.09, 0.0, 0.56), (0.15, 0.20, 0.26))
    add_box(bm, (0.17, 0.0, 0.56), (0.022, 0.17, 0.22))
    add_cylinder(bm, (0.10, 0.07, 0.80), 0.008, 0.003, 0.28, segs=8)
    add_cylinder(bm, (0.10, -0.07, 0.78), 0.008, 0.003, 0.24, segs=8)
    add_strut(bm, (0.0, 0.0, top_z - 0.22), (0.17, -0.15, top_z - 0.22), radius=0.012, segs=8)

    # Upper sensor crossbar (ultrasonic wind sensor + microwave backhaul dish + lightning arrestor)
    add_box(bm, (0.0, 0.0, top_z - 0.11), (0.036, 0.48, 0.028))
    add_cylinder(bm, (0.0, 0.22, top_z - 0.05), 0.036, 0.036, 0.08, segs=12)
    add_cylinder(bm, (0.0, -0.22, top_z - 0.05), 0.028, 0.010, 0.09, segs=12)
    add_cylinder(bm, (0.04, 0.16, top_z - 0.11), 0.065, 0.022, 0.04, segs=16, rot_euler=(0.0, 1.35, 0.0))

    bm.normal_update()
    bm.to_mesh(mesh_body)
    bm.free()

    body_obj = bpy.data.objects.new(f"{name}_Body", mesh_body)
    body_obj.data.materials.append(mats["steel_housing"])
    link_obj(body_obj, station_grp)

    # 3. Dual-Wing Crystalline Photovoltaic Solar Array with Dark Obsidian Frame & Cell Grid Busbars
    mesh_solar_frame = bpy.data.meshes.new(f"{name}_SolarFrameMesh")
    bm_sf = bmesh.new()
    solar_rot = (0.38, -0.32, 0.0)
    for wing_y in (-0.19, 0.19):
        add_box(bm_sf, (-0.16, wing_y, 0.718), (0.32, 0.24, 0.022), rot_euler=solar_rot)
        add_strut(bm_sf, (0.0, 0.0, 0.62), (-0.16, wing_y, 0.71), radius=0.013, segs=6)
    bm_sf.normal_update()
    bm_sf.to_mesh(mesh_solar_frame)
    bm_sf.free()
    solar_frame_obj = bpy.data.objects.new(f"{name}_SolarFrame", mesh_solar_frame)
    solar_frame_obj.data.materials.append(mats["ops_obsidian"])
    link_obj(solar_frame_obj, station_grp)

    mesh_solar = bpy.data.meshes.new(f"{name}_SolarMesh")
    bm_s = bmesh.new()
    solar_rot_mat = Euler(solar_rot, "XYZ").to_matrix()
    for wing_y in (-0.19, 0.19):
        wing_center = Vector((-0.16, wing_y, 0.718))
        for cell_r in (-0.092, 0.0, 0.092):
            for cell_c in (-0.056, 0.056):
                cell_pos = wing_center + solar_rot_mat @ Vector((cell_r, cell_c, 0.009))
                add_box(
                    bm_s,
                    (cell_pos.x, cell_pos.y, cell_pos.z),
                    (0.082, 0.095, 0.012),
                    rot_euler=solar_rot,
                )
    bm_s.normal_update()
    bm_s.to_mesh(mesh_solar)
    bm_s.free()

    solar_obj = bpy.data.objects.new(f"{name}_Solar", mesh_solar)
    solar_obj.data.materials.append(mats["solar_panel"])
    link_obj(solar_obj, station_grp)

    # 4. Multi-Fin Choke-Ring Geodetic Radome Monument
    mesh_dome = bpy.data.meshes.new(f"{name}_DomeMesh")
    bm_d = bmesh.new()
    for fin_i in range(4):
        fin_z = top_z + 0.012 + fin_i * 0.016
        fin_r = 0.205 - fin_i * 0.008
        add_cylinder(bm_d, (0, 0, fin_z), fin_r, fin_r, 0.011, segs=28)
    add_cylinder(bm_d, (0, 0, top_z + 0.095), 0.175, 0.125, 0.068, segs=28)
    add_cylinder(bm_d, (0, 0, top_z + 0.148), 0.125, 0.052, 0.048, segs=28)
    add_cylinder(bm_d, (0, 0, top_z + 0.185), 0.052, 0.008, 0.032, segs=20)
    # Glowing cabinet telemetry status bar
    add_box(bm_d, (0.185, 0.0, 0.62), (0.012, 0.12, 0.028))
    bm_d.normal_update()
    bm_d.to_mesh(mesh_dome)
    bm_d.free()

    dome_obj = bpy.data.objects.new(f"{name}_Dome", mesh_dome)
    dome_obj.data.materials.append(mats["gnss_base_dome"] if is_base else mats["gnss_rover_dome"])
    link_obj(dome_obj, station_grp)

    # 5. Concentric Ground Laser Target Rings + Elevated Telemetry Scan Halo
    mesh_ring = bpy.data.meshes.new(f"{name}_RingMesh")
    bm_r = bmesh.new()
    for r_rad, thick, z_off in ((0.48, 1.10, 0.032), (0.68, 1.05, 0.032), (0.30, 1.08, top_z + 0.08)):
        c_geom = bmesh.ops.create_circle(bm_r, cap_ends=False, radius=r_rad, segments=36)
        c_verts = c_geom["verts"]
        c_edges = [e for e in bm_r.edges if e.verts[0] in c_verts and e.verts[1] in c_verts]
        ext = bmesh.ops.extrude_edge_only(bm_r, edges=c_edges)
        ext_verts = [ele for ele in ext["geom"] if isinstance(ele, bmesh.types.BMVert)]
        for v in ext_verts:
            v.co.x *= thick
            v.co.y *= thick
        for v in c_verts + ext_verts:
            v.co.z += z_off
    bm_r.normal_update()
    bm_r.to_mesh(mesh_ring)
    bm_r.free()

    ring_obj = bpy.data.objects.new(f"{name}_Ring", mesh_ring)
    ring_obj.data.materials.append(mats["ring_lime"] if is_base else mats["ring_teal"])
    link_obj(ring_obj, station_grp)

    return station_grp


def build_imu_borehole(root, mats, templates=None):
    """Build deep borehole inclinometer casing + real 3D hex pad & telemetry terminal + 6 subsurface MEMS IMU nodes + displacement vector."""
    x, y = -1.48, -0.68
    z = terrain_height(x, y)
    grp = bpy.data.objects.new("IMU_Borehole_Assembly", None)
    grp.location = (x, y, z)
    link_obj(grp, root)

    spawn_hw_instance(
        templates, "hex_pad", "IMU_HexPad", grp,
        loc=(0.0, 0.0, -0.02), rot=(0.0, 0.0, 0.52), scale=(0.76, 0.76, 0.85)
    )
    spawn_hw_instance(
        templates, "info_panel", "IMU_InfoPanel", grp,
        loc=(-0.22, -0.14, 0.10), rot=(0.0, 0.0, -0.28), scale=(0.82, 0.82, 0.82)
    )
    spawn_hw_instance(
        templates, "mini_pc", "IMU_EdgeLogger", grp,
        loc=(0.18, -0.14, 0.14), rot=(0.0, 0.0, 0.35), scale=(0.85, 0.85, 0.85)
    )

    mesh_casing = bpy.data.meshes.new("IMUCasingMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, 0.04), 0.28, 0.25, 0.09, segs=16)
    add_cylinder(bm, (0, 0, -1.02), 0.058, 0.058, 2.34, segs=16)
    add_cylinder(bm, (0, 0, 0.22), 0.135, 0.110, 0.28, segs=16)
    add_cylinder(bm, (0, 0, 0.38), 0.145, 0.145, 0.045, segs=16)
    for bx, by in ((0.22, 0.22), (-0.22, 0.22), (-0.22, -0.22), (0.22, -0.22)):
        add_cylinder(bm, (bx, by, 0.16), 0.022, 0.022, 0.28, segs=10)
    bm.normal_update()
    bm.to_mesh(mesh_casing)
    bm.free()

    casing_obj = bpy.data.objects.new("IMU_Casing", mesh_casing)
    casing_obj.data.materials.append(mats["imu_amber"])
    link_obj(casing_obj, grp)

    mesh_nodes = bpy.data.meshes.new("IMUNodesMesh")
    bm_n = bmesh.new()
    for depth_z in (-0.18, -0.46, -0.76, -1.06, -1.36, -1.66):
        add_cylinder(bm_n, (0, 0, depth_z), 0.102, 0.102, 0.15, segs=18)
        add_cylinder(bm_n, (0, 0, depth_z), 0.134, 0.134, 0.042, segs=18)
    # Surface telemetry halo around borehole head
    add_cylinder(bm_n, (0, 0, 0.42), 0.24, 0.22, 0.022, segs=24, cap_ends=False)
    bm_n.normal_update()
    bm_n.to_mesh(mesh_nodes)
    bm_n.free()

    nodes_obj = bpy.data.objects.new("IMU_Subsurface_Nodes", mesh_nodes)
    nodes_obj.data.materials.append(mats["imu_glow"])
    link_obj(nodes_obj, grp)

    mesh_arrow = bpy.data.meshes.new("DisplacementArrowMesh")
    bm_a = bmesh.new()
    rot_y = Euler((0.0, math.pi / 2 + 0.24, 0.0), "XYZ").to_matrix().to_4x4()
    bmesh.ops.create_cone(
        bm_a, cap_ends=True, segments=16, radius1=0.032, radius2=0.032, depth=0.86,
        matrix=Matrix.Translation((0.44, 0.0, 0.34)) @ rot_y
    )
    for ch_idx, offset_x in enumerate((0.70, 0.88, 1.06)):
        rad = 0.090 + ch_idx * 0.016
        bmesh.ops.create_cone(
            bm_a, cap_ends=True, segments=16, radius1=rad, radius2=0.005, depth=0.22,
            matrix=Matrix.Translation((offset_x, 0.0, 0.26 - ch_idx * 0.042)) @ rot_y
        )
    bm_a.normal_update()
    bm_a.to_mesh(mesh_arrow)
    bm_a.free()

    arrow_obj = bpy.data.objects.new("DisplacementVectorArrow", mesh_arrow)
    arrow_obj.data.materials.append(mats["imu_glow"])
    link_obj(arrow_obj, grp)
    return grp


def build_rain_and_piezometer(root, mats, templates=None):
    """Build Automatic Weather & Rain Gauge Station and Cutaway Piezometer Well with real 3D hardware pads, terminals, and cameras."""
    rx, ry = -3.25, -2.05
    rz = terrain_height(rx, ry)
    rain_grp = bpy.data.objects.new("Rain_Gauge_Station", None)
    rain_grp.location = (rx, ry, rz)
    link_obj(rain_grp, root)

    spawn_hw_instance(
        templates, "hex_pad", "Rain_HexPad", rain_grp,
        loc=(0.0, 0.0, -0.02), rot=(0.0, 0.0, 0.25), scale=(0.88, 0.88, 0.90)
    )
    spawn_hw_instance(
        templates, "info_panel", "Rain_InfoPanel", rain_grp,
        loc=(-0.22, -0.18, 0.12), rot=(0.0, 0.0, -0.32), scale=(0.90, 0.90, 0.90)
    )
    spawn_hw_instance(
        templates, "ptz_camera", "Rain_PTZCamera", rain_grp,
        loc=(0.20, -0.14, 0.42), rot=(0.0, 0.0, 0.40), scale=(0.85, 0.85, 0.85)
    )

    mesh_rg_stand = bpy.data.meshes.new("RainGaugeStandMesh")
    bm_s = bmesh.new()
    add_cylinder(bm_s, (0, 0, 0.05), 0.29, 0.26, 0.11, segs=16)
    add_cylinder(bm_s, (0, 0, 0.44), 0.032, 0.024, 0.78, segs=12)
    for k in range(4):
        ang = k * (math.pi / 2.0) + 0.4
        add_strut(bm_s, (math.cos(ang) * 0.22, math.sin(ang) * 0.22, 0.08), (0, 0, 0.46), radius=0.014, segs=8)
    add_box(bm_s, (0, 0, 0.78), (0.50, 0.032, 0.032))
    for cup_ang in (0, 2.09, 4.18):
        cx = -0.23 + math.cos(cup_ang) * 0.072
        cy = math.sin(cup_ang) * 0.072
        add_cylinder(bm_s, (cx, cy, 0.84), 0.026, 0.010, 0.034, segs=10)
    for sh_i in range(5):
        add_cylinder(bm_s, (0.22, 0, 0.64 + sh_i * 0.030), 0.048, 0.045, 0.020, segs=14)

    bm_s.normal_update()
    bm_s.to_mesh(mesh_rg_stand)
    bm_s.free()

    stand_obj = bpy.data.objects.new("RainGaugeStand", mesh_rg_stand)
    stand_obj.data.materials.append(mats["steel_housing"])
    link_obj(stand_obj, rain_grp)

    mesh_rg = bpy.data.meshes.new("RainGaugeMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, 0.52), 0.148, 0.148, 0.28, segs=24)
    add_cylinder(bm, (0, 0, 0.70), 0.148, 0.192, 0.095, segs=24)
    add_cylinder(bm, (0, 0, 0.76), 0.196, 0.196, 0.026, segs=24)
    add_cylinder(bm, (0, 0, 0.04), 0.44, 0.40, 0.020, segs=28, cap_ends=False)
    bm.normal_update()
    bm.to_mesh(mesh_rg)
    bm.free()

    rg_obj = bpy.data.objects.new("RainGaugeCollector", mesh_rg)
    rg_obj.data.materials.append(mats["rain_cyan"])
    link_obj(rg_obj, rain_grp)

    # 2. Piezometer Groundwater Monitoring Well on the front cutaway edge
    px, py = -2.25, -TERRAIN_DEPTH / 2 + 0.32
    pz = terrain_height(px, py)
    piezo_grp = bpy.data.objects.new("Piezometer_Well_Assembly", None)
    piezo_grp.location = (px, py, pz)
    link_obj(piezo_grp, root)

    spawn_hw_instance(
        templates, "hex_pad", "Piezo_HexPad", piezo_grp,
        loc=(0.0, 0.06, -0.02), rot=(0.0, 0.0, 0.0), scale=(0.75, 0.75, 0.85)
    )
    spawn_hw_instance(
        templates, "info_panel", "Piezo_InfoPanel", piezo_grp,
        loc=(-0.22, 0.04, 0.10), rot=(0.0, 0.0, -0.25), scale=(0.82, 0.82, 0.82)
    )
    spawn_hw_instance(
        templates, "mini_pc", "Piezo_EdgeLogger", piezo_grp,
        loc=(0.20, 0.04, 0.12), rot=(0.0, 0.0, 0.35), scale=(0.85, 0.85, 0.85)
    )

    mesh_well = bpy.data.meshes.new("PiezometerCasingMesh")
    bm_w = bmesh.new()
    add_cylinder(bm_w, (0, 0, 0.05), 0.25, 0.22, 0.11, segs=16)
    add_cylinder(bm_w, (0, 0, 0.24), 0.145, 0.125, 0.30, segs=18)
    add_box(bm_w, (0.145, 0, 0.28), (0.12, 0.14, 0.20))
    add_cylinder(bm_w, (0, -0.20, -0.86), 0.086, 0.086, 2.02, segs=18)
    bm_w.normal_update()
    bm_w.to_mesh(mesh_well)
    bm_w.free()

    well_obj = bpy.data.objects.new("PiezometerCasing", mesh_well)
    well_obj.data.materials.append(mats["steel_housing"])
    link_obj(well_obj, piezo_grp)

    mesh_col = bpy.data.meshes.new("PiezometerWaterMesh")
    bm_c = bmesh.new()
    add_cylinder(bm_c, (0, -0.24, -1.06), 0.108, 0.108, 1.28, segs=20)
    for ring_z in (-1.40, -1.08, -0.76, -0.44, 0.38):
        add_cylinder(bm_c, (0, -0.24 if ring_z < 0 else 0.0, ring_z), 0.132 if ring_z < 0 else 0.28, 0.132 if ring_z < 0 else 0.26, 0.038, segs=20)
    bm_c.normal_update()
    bm_c.to_mesh(mesh_col)
    bm_c.free()

    col_obj = bpy.data.objects.new("PiezometerWaterColumn", mesh_col)
    col_obj.data.materials.append(mats["water_glow"])
    link_obj(col_obj, piezo_grp)


def import_single_glb_mesh(filename: str, new_name: str, scale_xyz=(1.0, 1.0, 1.0), mat_map=None, exclude_names=()):
    """Import a real 3D .glb file, join its meshes in world space, recenter base to (0,0,0), scale, and assign clean materials."""
    fpath = BLENDER_DIR / "models" / filename
    if not fpath.exists():
        return None
    before_names = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=str(fpath))
    imp_names = set(bpy.data.objects.keys()) - before_names
    meshes = [
        bpy.data.objects[n]
        for n in imp_names
        if n in bpy.data.objects
        and bpy.data.objects[n].type == "MESH"
        and not any(ex in n for ex in exclude_names)
    ]
    if not meshes:
        for n in list(imp_names):
            if n in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
        return None

    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        mw = m.matrix_world.copy()
        m.parent = None
        m.rotation_mode = "XYZ"
        m.matrix_world = mw
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if len(meshes) > 1:
        bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined_orig_name = joined.name
    joined.name = new_name
    joined.rotation_mode = "XYZ"
    joined.location = (0, 0, 0)
    joined.rotation_euler = (0, 0, 0)
    joined.scale = (1, 1, 1)

    verts = [v.co for v in joined.data.vertices]
    min_x = min(v.x for v in verts)
    max_x = max(v.x for v in verts)
    min_y = min(v.y for v in verts)
    max_y = max(v.y for v in verts)
    min_z = min(v.z for v in verts)
    cx = 0.5 * (min_x + max_x)
    cy = 0.5 * (min_y + max_y)
    sx, sy, sz = scale_xyz
    for v in joined.data.vertices:
        v.co.x = (v.co.x - cx) * sx
        v.co.y = (v.co.y - cy) * sy
        v.co.z = (v.co.z - min_z) * sz
    joined.data.update()

    if mat_map:
        for slot in joined.material_slots:
            if not slot.material:
                continue
            mname = slot.material.name
            for k, replacement_mat in mat_map.items():
                if k.lower() in mname.lower():
                    slot.material = replacement_mat
                    break

    for n in list(imp_names):
        if n != joined_orig_name and n in bpy.data.objects and bpy.data.objects[n] != joined:
            bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    return joined


def build_operations_hub(root, mats, templates=None):
    """Build an Expanded Futuristic AI Command & Data Center Campus with Motorized Sliding Entrance Doors and a Walk-In Interior Control Room (5-Screen Video Wall, 3D Holographic Terrain Projector, Operator Consoles & Seats)."""
    ox, oy = 5.15, -0.55
    oz = terrain_height(ox, oy)
    ops_grp = bpy.data.objects.new("Operations_Command_Node", None)
    ops_grp.location = (ox, oy, oz)
    link_obj(ops_grp, root)

    # 1. Monumental Terraced Concrete Citadel Plaza + Grand Approach Ramp + Interior Control Room Deck
    mesh_pad = bpy.data.meshes.new("OpsCampusPadMesh")
    bm_pad = bmesh.new()
    add_box(bm_pad, (0.05, 0.05, 0.08), (4.25, 4.45, 0.18))
    add_box(bm_pad, (0.05, 0.08, 0.19), (3.85, 4.05, 0.09))
    # Front approach ramp & steps leading to the Entrance Portal at y = -1.52
    add_box(bm_pad, (0.0, -1.92, 0.16), (1.56, 0.72, 0.12), rot_euler=(0.12, 0.0, 0.0))
    # Interior elevated Control Room bridge deck (y = -1.10 .. +0.55, z = 0.36)
    add_box(bm_pad, (0.0, -0.25, 0.30), (1.88, 1.75, 0.14))
    add_box(bm_pad, (0.0, -1.24, 0.27), (1.32, 0.48, 0.12), rot_euler=(0.24, 0.0, 0.0))
    # Low-profile Octagonal Hologram Projection Table Pedestal in the center of the Control Room (y = -0.22)
    add_cylinder(bm_pad, (0.0, -0.22, 0.41), 0.32, 0.26, 0.08, segs=8)
    add_cylinder(bm_pad, (0.0, -0.22, 0.48), 0.28, 0.32, 0.05, segs=8)
    # Vaulted architectural structural arches framing the Open-View Control Room Sanctuary
    for arch_y in (-1.05, -0.45, 0.15, 0.52):
        add_box(bm_pad, (-0.96, arch_y, 0.82), (0.08, 0.10, 1.08))
        add_box(bm_pad, (0.96, arch_y, 0.82), (0.08, 0.10, 1.08))
        add_box(bm_pad, (0.0, arch_y, 1.36), (2.02, 0.10, 0.07))
    for bx in (-1.75, -1.25, -0.75, 0.75, 1.25, 1.75):
        add_box(bm_pad, (bx, -2.08, 0.11), (0.09, 0.10, 0.22))
        add_cylinder(bm_pad, (bx, -1.98, 0.30), 0.022, 0.022, 0.14, segs=8)
    bm_pad.normal_update()
    bm_pad.to_mesh(mesh_pad)
    bm_pad.free()
    pad_obj = bpy.data.objects.new("OpsCampusPad", mesh_pad)
    pad_obj.data.materials.append(mats["concrete"])
    link_obj(pad_obj, ops_grp)

    # 2. Rear Citadel Spire (aero_station.glb) framing the back of the Control Room + Flanking Biodomes
    aero_mat_map = {
        "Aero_Floor_01": mats["ops_obsidian"],
        "Aero_Floor_02": mats["steel_housing"],
        "Aero_Glass": mats["ops_glass_cyan"],
        "Aero_Glow_01": mats["ring_teal"],
        "Aero_Glow_02": mats["imu_glow"],
        "Aero_Holographic": mats["gnss_base_dome"],
        "Aero_Wall": mats["ops_obsidian"],
    }
    aero_obj = import_single_glb_mesh(
        "aero_station.glb",
        "OpsCommandStructure",
        scale_xyz=(0.118, 0.088, 0.058),
        mat_map=aero_mat_map,
    )
    if aero_obj:
        aero_obj.location = (0.0, 1.48, 0.21)
        link_obj(aero_obj, ops_grp)

    dome_mat_map = {
        "DomeBase": mats["steel_housing"],
        "DomeChip": mats["ops_glass_cyan"],
    }
    dome1_obj = import_single_glb_mesh(
        "sci_dome.glb",
        "OpsNorthBiodome",
        scale_xyz=(0.036, 0.032, 0.032),
        mat_map=dome_mat_map,
    )
    if dome1_obj:
        dome1_obj.location = (1.38, 0.68, 0.21)
        link_obj(dome1_obj, ops_grp)

    dome2_mat_map = {
        "DomeBase": mats["ops_obsidian"],
        "DomeChip": mats["gnss_rover_dome"],
    }
    dome2_obj = import_single_glb_mesh(
        "sci_dome_02.glb",
        "OpsSouthBiodome",
        scale_xyz=(0.028, 0.030, 0.028),
        mat_map=dome2_mat_map,
    )
    if dome2_obj:
        dome2_obj.location = (-1.38, 0.55, 0.21)
        link_obj(dome2_obj, ops_grp)

    # 3. Hexagonal Helipad Command Plaza on the East Forecourt (hex_pavilion.glb) + External AI Core (teleporter_hub.glb)
    hex_obj = import_single_glb_mesh(
        "hex_pavilion.glb",
        "OpsHelipadPavilion",
        scale_xyz=(0.046, 0.046, 0.046),
        mat_map={"HexagonVIP01": mats["ops_obsidian"], "ZenGarden": mats["ops_glass_cyan"]},
    )
    hx, hy, hz = 1.38, -1.05, 0.22
    if hex_obj:
        hex_obj.location = (hx, hy, 0.20)
        link_obj(hex_obj, ops_grp)

    holo_base = import_single_glb_mesh(
        "teleporter_hub.glb",
        "OpsControlGlass",
        scale_xyz=(0.32, 0.32, 0.28),
        mat_map={
            "AltarHolo": mats["ops_glass_cyan"],
            "PlatformBarrier": mats["ring_lime"],
            "Teleporter": mats["steel_housing"],
        },
    )
    if holo_base:
        holo_base.location = (1.38, -0.15, 0.21)
        link_obj(holo_base, ops_grp)

    # 4. GRAND MOTORIZED ENTRANCE PORTAL ARCHWAY (Open-Center Gateway) + ANIMATED SLIDING BLAST DOORS (OpsDoor_Left & OpsDoor_Right)
    mesh_portal = bpy.data.meshes.new("OpsEntrancePortalMesh")
    bm_pt = bmesh.new()
    for p_sign in (-1.0, 1.0):
        # Sculpted inner gateway pylons framing the 1.12m wide doorway opening
        add_box(bm_pt, (p_sign * 0.64, -1.52, 0.68), (0.16, 0.22, 0.92))
        # Outer pocket buttress wings that house the sliding doors when open
        add_box(bm_pt, (p_sign * 0.96, -1.52, 0.64), (0.48, 0.14, 0.84))
        add_box(bm_pt, (p_sign * 1.22, -1.52, 0.68), (0.14, 0.22, 0.92))
    # Overhead cantilevered portal lintel & aerodynamic marquee canopy
    add_box(bm_pt, (0.0, -1.52, 1.16), (2.58, 0.28, 0.12))
    add_box(bm_pt, (0.0, -1.60, 1.25), (1.84, 0.34, 0.07))
    bm_pt.normal_update()
    bm_pt.to_mesh(mesh_portal)
    bm_pt.free()
    portal_obj = bpy.data.objects.new("OpsEntrancePortal", mesh_portal)
    portal_obj.data.materials.append(mats["ops_obsidian"])
    link_obj(portal_obj, ops_grp)

    # Glowing Entrance Portal Arch & Floor Runway Strips leading straight up into the Control Room
    mesh_arch_glow = bpy.data.meshes.new("OpsEntranceArchGlowMesh")
    bm_ag = bmesh.new()
    add_box(bm_ag, (-0.58, -1.58, 0.68), (0.042, 0.06, 0.88))
    add_box(bm_ag, (0.58, -1.58, 0.68), (0.042, 0.06, 0.88))
    add_box(bm_ag, (0.0, -1.58, 1.14), (1.24, 0.08, 0.052))
    for rx_strip in (-0.28, 0.28):
        add_box(bm_ag, (rx_strip, -1.25, 0.37), (0.032, 1.45, 0.016))
    for arch_y in (-1.05, -0.45, 0.15, 0.52):
        add_box(bm_ag, (0.0, arch_y, 1.32), (1.84, 0.045, 0.028))
    bm_ag.normal_update()
    bm_ag.to_mesh(mesh_arch_glow)
    bm_ag.free()
    arch_glow_obj = bpy.data.objects.new("OpsEntranceArchGlow", mesh_arch_glow)
    arch_glow_obj.data.materials.append(mats["ops_glass_cyan"])
    link_obj(arch_glow_obj, ops_grp)

    # Left & Right Sliding Entrance Doors (OpsDoor_Left and OpsDoor_Right)
    def build_sliding_door_panel(door_name: str, side_sign: float):
        mesh_dr = bpy.data.meshes.new(f"{door_name}Mesh")
        bm_dr = bmesh.new()
        cx_panel = side_sign * 0.28
        add_box(bm_dr, (cx_panel, 0.0, 0.42), (0.55, 0.048, 0.82))
        add_box(bm_dr, (side_sign * 0.03, -0.015, 0.42), (0.055, 0.068, 0.82))
        for rib_z in (0.14, 0.42, 0.70):
            add_box(bm_dr, (cx_panel, -0.018, rib_z), (0.52, 0.062, 0.048))
        bm_dr.normal_update()
        bm_dr.to_mesh(mesh_dr)
        bm_dr.free()

        dr_obj = bpy.data.objects.new(door_name, mesh_dr)
        dr_obj.location = (0.0, -1.52, 0.24)
        dr_obj.data.materials.append(mats["steel_housing"])
        link_obj(dr_obj, ops_grp)

        mesh_win = bpy.data.meshes.new(f"{door_name}GlassMesh")
        bm_w = bmesh.new()
        add_box(bm_w, (cx_panel, -0.022, 0.56), (0.38, 0.022, 0.22))
        add_box(bm_w, (cx_panel, -0.022, 0.28), (0.38, 0.022, 0.20))
        bm_w.normal_update()
        bm_w.to_mesh(mesh_win)
        bm_w.free()
        win_obj = bpy.data.objects.new(f"{door_name}_Glass", mesh_win)
        win_obj.data.materials.append(mats["ops_glass_cyan"])
        link_obj(win_obj, dr_obj)
        return dr_obj

    build_sliding_door_panel("OpsDoor_Left", -1.0)
    build_sliding_door_panel("OpsDoor_Right", 1.0)

    # 5. INTERIOR AI COMMAND & CONTROL ROOM (Unobstructed 5-Screen Video Wall + Low-Profile 3D Hologram Table + Operator Desks & Seats)
    holo_proj = import_single_glb_mesh(
        "energy_projector.glb",
        "OpsHoloProjector",
        scale_xyz=(0.11, 0.11, 0.022),
        mat_map={
            "SciFi_Trim": mats["ops_obsidian"],
            "Tubes_Transparent": mats["ops_glass_cyan"],
            "Eclipse": mats["gnss_base_dome"],
        },
    )
    if holo_proj:
        holo_proj.location = (0.0, -0.22, 0.42)
        link_obj(holo_proj, ops_grp)

    # Floating 3D Holographic Mountain Terrain & Slip-Zone Model (OpsHoloTerrain) above the low-profile table (z = 0.54)
    mesh_holo_t = bpy.data.meshes.new("OpsHoloTerrainMesh")
    bm_ht = bmesh.new()
    add_cylinder(bm_ht, (0.0, 0.0, 0.0), 0.24, 0.22, 0.014, segs=24)
    add_box(bm_ht, (-0.05, 0.02, 0.036), (0.24, 0.18, 0.036), rot_euler=(0.08, 0.26, -0.15))
    add_box(bm_ht, (-0.09, 0.04, 0.068), (0.15, 0.12, 0.032), rot_euler=(0.10, 0.32, -0.15))
    for h_pt in ((-0.10, 0.04, 0.105), (-0.02, -0.02, 0.085), (0.05, 0.03, 0.06)):
        add_cylinder(bm_ht, h_pt, 0.012, 0.004, 0.048, segs=10)
    bm_ht.normal_update()
    bm_ht.to_mesh(mesh_holo_t)
    bm_ht.free()
    holo_terrain_obj = bpy.data.objects.new("OpsHoloTerrain", mesh_holo_t)
    holo_terrain_obj.location = (0.0, -0.22, 0.54)
    holo_terrain_obj.data.materials.append(mats["ops_glass_cyan"])
    link_obj(holo_terrain_obj, ops_grp)

    mesh_holo_slip = bpy.data.meshes.new("OpsHoloSlipMesh")
    bm_hs = bmesh.new()
    add_box(bm_hs, (-0.02, -0.01, 0.058), (0.12, 0.095, 0.018), rot_euler=(0.08, 0.28, -0.15))
    add_cylinder(bm_hs, (0.0, 0.0, 0.015), 0.28, 0.26, 0.010, segs=28, cap_ends=False)
    bm_hs.normal_update()
    bm_hs.to_mesh(mesh_holo_slip)
    bm_hs.free()
    holo_slip_obj = bpy.data.objects.new("OpsHoloSlip", mesh_holo_slip)
    holo_slip_obj.data.materials.append(mats["imu_glow"])
    link_obj(holo_slip_obj, holo_terrain_obj)

    # 5B. Operator Desks (table_futuristic.glb) & Operator Chairs (operator_seat.glb) & Edge-AI Terminals
    desk_tmpl = import_single_glb_mesh(
        "table_futuristic.glb",
        "Tmpl_OpsDesk",
        scale_xyz=(0.14, 0.14, 0.24),
        mat_map={"Table_Futuristic_01": mats["ops_obsidian"]},
    )
    seat_tmpl = import_single_glb_mesh(
        "operator_seat.glb",
        "Tmpl_OpsSeat",
        scale_xyz=(0.15, 0.15, 0.17),
        mat_map={"Seat_01": mats["steel_housing"]},
    )
    desk_configs = [
        ("OpsDesk_LeftFront", (-0.52, -0.58, 0.37), (0.0, 0.0, 0.28)),
        ("OpsDesk_RightFront", (0.52, -0.58, 0.37), (0.0, 0.0, -0.28)),
        ("OpsDesk_LeftRear", (-0.56, -0.08, 0.37), (0.0, 0.0, 0.35)),
        ("OpsDesk_RightRear", (0.56, -0.08, 0.37), (0.0, 0.0, -0.35)),
    ]
    for d_name, d_loc, d_rot in desk_configs:
        if desk_tmpl:
            d_inst = bpy.data.objects.new(d_name, desk_tmpl.data.copy())
            d_inst.location = d_loc
            d_inst.rotation_euler = d_rot
            link_obj(d_inst, ops_grp)
        if seat_tmpl:
            s_inst = bpy.data.objects.new(f"{d_name}_Seat", seat_tmpl.data.copy())
            s_inst.location = (d_loc[0] * 1.04, d_loc[1] - 0.18, d_loc[2])
            s_inst.rotation_euler = (0.0, 0.0, math.pi + d_rot[2])
            link_obj(s_inst, ops_grp)
        spawn_hw_instance(
            templates, "mini_pc", f"{d_name}_PC", ops_grp,
            loc=(d_loc[0], d_loc[1] + 0.03, d_loc[2] + 0.14), rot=d_rot, scale=(0.65, 0.65, 0.65)
        )

    for tmpl_d in (desk_tmpl, seat_tmpl):
        if tmpl_d and tmpl_d.name in bpy.data.objects:
            bpy.data.objects.remove(tmpl_d, do_unlink=True)

    spawn_hw_instance(
        templates, "info_panel", "OpsInteriorTerminal_L", ops_grp,
        loc=(-0.78, -0.42, 0.37), rot=(0.0, 0.0, 0.65), scale=(1.15, 1.15, 1.15)
    )
    spawn_hw_instance(
        templates, "info_panel", "OpsInteriorTerminal_R", ops_grp,
        loc=(0.78, -0.42, 0.37), rot=(0.0, 0.0, -0.65), scale=(1.15, 1.15, 1.15)
    )

    # 5C. CURVED 5-SCREEN PANORAMIC COMMAND VIDEO WALL (computer_structure.glb + computer_screen.glb + Unobstructed 3D Telemetry Dashboards)
    comp_struct_tmpl = import_single_glb_mesh(
        "computer_structure.glb",
        "Tmpl_CompStruct",
        scale_xyz=(0.068, 0.036, 0.068),
        mat_map={"Computer_Monitor": mats["ops_obsidian"]},
    )
    comp_screen_tmpl = import_single_glb_mesh(
        "computer_screen.glb",
        "Tmpl_CompScreen",
        scale_xyz=(0.065, 0.040, 0.055),
        mat_map={"Computer_Screen": mats["solar_panel"]},
    )
    # Placed slightly further back (y = 0.62 and y = 0.46) so the 5 glowing screen faces at y = 0.34 and y = 0.20 are 100% in front!
    wall_rig_configs = [
        ("OpsRig_Center", (0.0, 0.62, 0.37), (0.0, 0.0, math.pi), (1.35, 1.0, 1.18)),
        ("OpsRig_Left", (-0.66, 0.46, 0.37), (0.0, 0.0, math.pi - 0.42), (0.92, 1.0, 1.02)),
        ("OpsRig_Right", (0.66, 0.46, 0.37), (0.0, 0.0, math.pi + 0.42), (0.92, 1.0, 1.02)),
    ]
    for r_name, r_loc, r_rot, r_sc in wall_rig_configs:
        if comp_struct_tmpl:
            st_i = bpy.data.objects.new(r_name, comp_struct_tmpl.data.copy())
            st_i.location = r_loc
            st_i.rotation_euler = r_rot
            st_i.scale = r_sc
            link_obj(st_i, ops_grp)
        if comp_screen_tmpl:
            sc_i = bpy.data.objects.new(f"{r_name}_Screen", comp_screen_tmpl.data.copy())
            sc_i.location = (r_loc[0], r_loc[1] - 0.22, r_loc[2] + 0.34)
            sc_i.rotation_euler = r_rot
            sc_i.scale = r_sc
            link_obj(sc_i, ops_grp)

    for tmpl_c in (comp_struct_tmpl, comp_screen_tmpl):
        if tmpl_c and tmpl_c.name in bpy.data.objects:
            bpy.data.objects.remove(tmpl_c, do_unlink=True)

    # Panoramic 5-Screen Dark Obsidian Glass Bezel Backing at y = 0.35 (Center) and y = 0.21 (Left/Right Wings)
    mesh_wall_bezel = bpy.data.meshes.new("OpsVideoWallBezelMesh")
    bm_wb = bmesh.new()
    add_box(bm_wb, (0.0, 0.35, 0.88), (0.96, 0.032, 0.56))
    add_box(bm_wb, (-0.66, 0.21, 0.86), (0.48, 0.030, 0.50), rot_euler=(0.0, 0.0, 0.42))
    add_box(bm_wb, (0.66, 0.21, 0.86), (0.48, 0.030, 0.50), rot_euler=(0.0, 0.0, -0.42))
    bm_wb.normal_update()
    bm_wb.to_mesh(mesh_wall_bezel)
    bm_wb.free()
    wall_bezel_obj = bpy.data.objects.new("OpsVideoWallBezel", mesh_wall_bezel)
    wall_bezel_obj.data.materials.append(mats["ops_obsidian"])
    link_obj(wall_bezel_obj, ops_grp)

    # Layer 1 on Screens (y = 0.325): Cyan Topographic Contour Map, GNSS Waveforms & Left/Right Telemetry Charts
    mesh_scr_cyan = bpy.data.meshes.new("OpsScreenCyanTelemetryMesh")
    bm_sc = bmesh.new()
    add_box(bm_sc, (0.0, 0.326, 1.13), (0.90, 0.014, 0.018))
    add_box(bm_sc, (0.0, 0.326, 0.63), (0.90, 0.014, 0.018))
    add_box(bm_sc, (-0.44, 0.326, 0.88), (0.018, 0.014, 0.50))
    add_box(bm_sc, (0.44, 0.326, 0.88), (0.018, 0.014, 0.50))
    for c_idx in range(5):
        cz = 0.78 + c_idx * 0.062
        add_strut(bm_sc, (-0.38, 0.324, cz + 0.04), (-0.08, 0.324, cz - 0.02), radius=0.008, segs=6)
        add_strut(bm_sc, (-0.08, 0.324, cz - 0.02), (0.22, 0.324, cz + 0.03), radius=0.008, segs=6)
        add_strut(bm_sc, (0.22, 0.324, cz + 0.03), (0.38, 0.324, cz - 0.01), radius=0.008, segs=6)
    for b_i in range(14):
        bx_bar = -0.36 + b_i * 0.055
        bh = 0.040 + 0.060 * abs(math.sin(b_i * 0.85))
        add_box(bm_sc, (bx_bar, 0.324, 0.66 + bh * 0.5), (0.028, 0.014, bh))
    for l_i in range(6):
        t_off = -0.15 + l_i * 0.06
        lx_p = -0.66 + math.cos(0.42) * t_off
        ly_p = 0.182 + math.sin(0.42) * t_off
        bh = 0.09 + (l_i % 3) * 0.07
        add_box(bm_sc, (lx_p, ly_p, 0.69 + bh * 0.5), (0.032, 0.016, bh), rot_euler=(0.0, 0.0, 0.42))
    for r_i in range(6):
        t_off = -0.15 + r_i * 0.06
        rx_p = 0.66 + math.cos(-0.42) * t_off
        ry_p = 0.182 + math.sin(-0.42) * t_off
        bh = 0.10 + ((r_i + 1) % 3) * 0.065
        add_box(bm_sc, (rx_p, ry_p, 0.69 + bh * 0.5), (0.032, 0.016, bh), rot_euler=(0.0, 0.0, -0.42))
    bm_sc.normal_update()
    bm_sc.to_mesh(mesh_scr_cyan)
    bm_sc.free()
    scr_cyan_obj = bpy.data.objects.new("OpsScreen_CyanTelemetry", mesh_scr_cyan)
    scr_cyan_obj.data.materials.append(mats["ops_glass_cyan"])
    link_obj(scr_cyan_obj, ops_grp)

    # Layer 2 on Screens (y = 0.322): Amber Slip-Zone Warning Heatmap & Displacement Vector Arrows
    mesh_scr_alert = bpy.data.meshes.new("OpsScreenAlertTelemetryMesh")
    bm_sa = bmesh.new()
    add_box(bm_sa, (-0.04, 0.322, 0.91), (0.30, 0.014, 0.15), rot_euler=(0.0, 0.18, 0.0))
    add_strut(bm_sa, (-0.18, 0.320, 0.95), (0.16, 0.320, 0.85), radius=0.014, segs=8)
    add_box(bm_sa, (-0.66, 0.180, 1.01), (0.38, 0.016, 0.048), rot_euler=(0.0, 0.0, 0.42))
    add_box(bm_sa, (0.66, 0.180, 1.01), (0.38, 0.016, 0.048), rot_euler=(0.0, 0.0, -0.42))
    bm_sa.normal_update()
    bm_sa.to_mesh(mesh_scr_alert)
    bm_sa.free()
    scr_alert_obj = bpy.data.objects.new("OpsScreen_AlertOverlay", mesh_scr_alert)
    scr_alert_obj.data.materials.append(mats["imu_glow"])
    link_obj(scr_alert_obj, ops_grp)

    # Layer 3 on Screens (y = 0.318): Animated Vertical Laser Scan Bar (OpsScreenScanner) & Station Target Rings
    mesh_scanner = bpy.data.meshes.new("OpsScreenScannerMesh")
    bm_scan = bmesh.new()
    add_box(bm_scan, (0.0, 0.318, 0.88), (0.024, 0.016, 0.48))
    for st_pt in ((-0.26, 0.319, 0.98), (-0.04, 0.319, 0.90), (0.20, 0.319, 0.82)):
        add_cylinder(bm_scan, st_pt, 0.026, 0.026, 0.018, segs=14, rot_euler=(math.pi / 2, 0.0, 0.0))
    bm_scan.normal_update()
    bm_scan.to_mesh(mesh_scanner)
    bm_scan.free()
    scanner_obj = bpy.data.objects.new("OpsScreenScanner", mesh_scanner)
    scanner_obj.data.materials.append(mats["gnss_base_dome"])
    link_obj(scanner_obj, ops_grp)

    # 6. Tapered Steel Lattice Radar & Telemetry Tower + Dual Parabolic Dish Pedestals
    mesh_roof = bpy.data.meshes.new("OpsRoofTechMesh")
    bm_rt = bmesh.new()
    tx, ty = 0.0, 1.42
    tower_base_z = 1.52
    tower_top_z = 2.34
    for leg_i in range(4):
        ang = leg_i * (math.pi / 2.0) + (math.pi / 4.0)
        p_bot = (tx + math.cos(ang) * 0.18, ty + math.sin(ang) * 0.18, tower_base_z)
        p_top = (tx + math.cos(ang) * 0.065, ty + math.sin(ang) * 0.065, tower_top_z)
        add_strut(bm_rt, p_bot, p_top, radius=0.014, segs=6)
        ang_next = (leg_i + 1) * (math.pi / 2.0) + (math.pi / 4.0)
        for z_br in (1.72, 1.92, 2.12):
            t_f = (z_br - tower_base_z) / (tower_top_z - tower_base_z)
            r_cur = 0.18 * (1 - t_f) + 0.065 * t_f
            p0 = (tx + math.cos(ang) * r_cur, ty + math.sin(ang) * r_cur, z_br)
            p1 = (tx + math.cos(ang_next) * r_cur, ty + math.sin(ang_next) * r_cur, z_br)
            add_strut(bm_rt, p0, p1, radius=0.010, segs=6)
    add_cylinder(bm_rt, (tx, ty, tower_top_z), 0.12, 0.10, 0.042, segs=14)
    add_cylinder(bm_rt, (1.38, 0.68, 1.18), 0.085, 0.065, 0.14, segs=12)
    add_cylinder(bm_rt, (-1.38, 0.55, 1.08), 0.075, 0.055, 0.12, segs=12)
    bm_rt.normal_update()
    bm_rt.to_mesh(mesh_roof)
    bm_rt.free()

    roof_obj = bpy.data.objects.new("OpsRoofTech", mesh_roof)
    roof_obj.data.materials.append(mats["steel_housing"])
    link_obj(roof_obj, ops_grp)

    # 7. Primary & Secondary Steerable Deep-Space Ku-Band Parabolic Satellite Dishes
    def create_parabolic_dish(dish_name: str, feed_name: str, pivot_loc, scale_d=1.0):
        mesh_d = bpy.data.meshes.new(f"{dish_name}Mesh")
        bm_d = bmesh.new()
        dish_tilt = (-0.52, -0.25, 0.0)
        add_cylinder(bm_d, (0, 0, 0.0), 0.08 * scale_d, 0.045 * scale_d, 0.045 * scale_d, segs=16, rot_euler=dish_tilt)
        add_cylinder(bm_d, (0, 0.022 * scale_d, 0.04 * scale_d), 0.19 * scale_d, 0.08 * scale_d, 0.055 * scale_d, segs=20, rot_euler=dish_tilt)
        add_cylinder(bm_d, (0, 0.045 * scale_d, 0.085 * scale_d), 0.28 * scale_d, 0.19 * scale_d, 0.05 * scale_d, segs=24, rot_euler=dish_tilt)
        focal_pt = (0.0, 0.12 * scale_d, 0.25 * scale_d)
        for f_i in range(3):
            ang = f_i * (math.pi * 2.0 / 3.0)
            rim_pt = (math.cos(ang) * 0.19 * scale_d, (0.035 + math.sin(ang) * 0.16) * scale_d, 0.08 * scale_d)
            add_strut(bm_d, rim_pt, focal_pt, radius=0.007 * scale_d, segs=6)
        bm_d.normal_update()
        bm_d.to_mesh(mesh_d)
        bm_d.free()
        d_obj = bpy.data.objects.new(dish_name, mesh_d)
        d_obj.location = pivot_loc
        d_obj.data.materials.append(mats["steel_housing"])
        link_obj(d_obj, ops_grp)

        mesh_fd = bpy.data.meshes.new(f"{feed_name}Mesh")
        bm_fd = bmesh.new()
        add_cylinder(bm_fd, focal_pt, 0.030 * scale_d, 0.018 * scale_d, 0.05 * scale_d, segs=12, rot_euler=dish_tilt)
        bm_fd.normal_update()
        bm_fd.to_mesh(mesh_fd)
        bm_fd.free()
        f_obj = bpy.data.objects.new(feed_name, mesh_fd)
        f_obj.data.materials.append(mats["imu_glow"])
        link_obj(f_obj, d_obj)
        return d_obj

    create_parabolic_dish("OpsTrackingDish", "OpsDishFeed", (1.38, 0.68, 1.26), scale_d=1.28)
    create_parabolic_dish("OpsSecondaryDish", "OpsSecondaryDishFeed", (-1.38, 0.55, 1.15), scale_d=1.05)

    # 8. Helipad "H" Emblem + Perimeter Beacon Ring on the Hexagonal Helipad Plaza
    mesh_heli = bpy.data.meshes.new("OpsHelipadMarkingMesh")
    bm_h = bmesh.new()
    hz_mark = 0.50
    add_cylinder(bm_h, (hx, hy, hz_mark - 0.02), 0.44, 0.42, 0.035, segs=16)
    add_box(bm_h, (hx - 0.085, hy, hz_mark), (0.034, 0.22, 0.012))
    add_box(bm_h, (hx + 0.085, hy, hz_mark), (0.034, 0.22, 0.012))
    add_box(bm_h, (hx, hy, hz_mark), (0.170, 0.036, 0.012))
    for k in range(8):
        ang = k * (math.pi / 4.0)
        add_box(
            bm_h,
            (hx + math.cos(ang) * 0.32, hy + math.sin(ang) * 0.32, hz_mark),
            (0.12, 0.024, 0.010),
            rot_euler=(0, 0, ang + math.pi / 2),
        )
    bm_h.normal_update()
    bm_h.to_mesh(mesh_heli)
    bm_h.free()

    heli_mark_obj = bpy.data.objects.new("OpsHelipadMarking", mesh_heli)
    heli_mark_obj.data.materials.append(mats["ring_lime"])
    link_obj(heli_mark_obj, ops_grp)

    # 9. Rotating Phased-Array S-Band Doppler Radar Scanner (OpsBeaconCore)
    mesh_beacon = bpy.data.meshes.new("OpsBeaconMesh")
    bm_b = bmesh.new()
    add_cylinder(bm_b, (0, 0, 0.04), 0.062, 0.062, 0.08, segs=14)
    bmesh.ops.create_icosphere(bm_b, subdivisions=2, radius=0.078, matrix=Matrix.Translation((0, 0, 0.13)))
    add_box(bm_b, (0, 0, 0.065), (0.72, 0.068, 0.052))
    add_box(bm_b, (-0.36, 0, 0.075), (0.032, 0.16, 0.080))
    add_box(bm_b, (0.36, 0, 0.075), (0.032, 0.16, 0.080))
    bm_b.normal_update()
    bm_b.to_mesh(mesh_beacon)
    bm_b.free()

    beacon_obj = bpy.data.objects.new("OpsBeaconCore", mesh_beacon)
    beacon_obj.location = (tx, ty, tower_top_z + 0.03)
    beacon_obj.data.materials.append(mats["gnss_base_dome"])
    link_obj(beacon_obj, ops_grp)

    # 10. Import Real 3D Quadcopter Drones (drone.glb - 5,223 verts) for OpsSurveyDrone & OpsRescueDrone
    drone_mat_map = {
        "Material.001": mats["ops_obsidian"],
        "Material.002": mats["heli_white"],
        "Material.003": mats["imu_amber"],
        "Material.004": mats["ops_glass_cyan"],
        "Material.005": mats["heli_red_orange"],
        "Cylinder.001_0": mats["steel_housing"],
        "pale": mats["ops_glass_cyan"],
    }
    drone1 = import_single_glb_mesh(
        "drone.glb",
        "OpsSurveyDrone",
        scale_xyz=(0.62, 0.62, 0.62),
        mat_map=drone_mat_map,
        exclude_names=("Circle.006",),
    )
    if drone1:
        drone1.location = (ox + 0.45, oy - 0.55, oz + 1.45)
        link_obj(drone1, root)

    drone2_mat_map = dict(drone_mat_map)
    drone2_mat_map["pale"] = mats["gnss_base_dome"]
    drone2 = import_single_glb_mesh(
        "drone.glb",
        "OpsRescueDrone",
        scale_xyz=(0.58, 0.58, 0.58),
        mat_map=drone2_mat_map,
        exclude_names=("Circle.006",),
    )
    if drone2:
        drone2.location = (-1.15, 0.55, terrain_height(-1.15, 0.55) + 1.38)
        link_obj(drone2, root)

    # 11. Highway Early Warning Gantry
    gx_y = -1.65
    gx = road_center_x(gx_y)
    gz = terrain_height(gx, gx_y)

    mesh_gate_frame = bpy.data.meshes.new("HighwayGateFrameMesh")
    bm_gf = bmesh.new()
    for side_x in (-0.62, 0.62):
        add_cylinder(bm_gf, (side_x, 0, 0.045), 0.068, 0.056, 0.10, segs=8)
        add_cylinder(bm_gf, (side_x, 0, 0.42), 0.032, 0.026, 0.74, segs=10)
        add_cylinder(bm_gf, (side_x, -0.07, 0.42), 0.025, 0.020, 0.74, segs=8)
        for z_brace in (0.22, 0.42, 0.62):
            add_strut(bm_gf, (side_x, 0, z_brace), (side_x, -0.07, z_brace + 0.10), radius=0.010, segs=6)
    add_box(bm_gf, (0, 0.02, 0.74), (1.28, 0.044, 0.044))
    add_box(bm_gf, (0, 0.02, 0.63), (1.28, 0.044, 0.044))
    add_box(bm_gf, (0.56, -0.26, 0.12), (0.09, 0.09, 0.24))
    bm_gf.normal_update()
    bm_gf.to_mesh(mesh_gate_frame)
    bm_gf.free()

    gate_frame_obj = bpy.data.objects.new("HighwayGateFrame", mesh_gate_frame)
    gate_frame_obj.data.materials.append(mats["steel_housing"])
    gate_frame_obj.location = (gx, gx_y, gz)
    link_obj(gate_frame_obj, root)

    mesh_gate = bpy.data.meshes.new("HighwayWarningGateMesh")
    bm_g = bmesh.new()
    add_box(bm_g, (0, -0.035, 0.68), (0.96, 0.048, 0.18))
    add_cylinder(bm_g, (-0.42, -0.035, 0.80), 0.036, 0.036, 0.050, segs=10)
    add_cylinder(bm_g, (0.42, -0.035, 0.80), 0.036, 0.036, 0.050, segs=10)
    add_box(bm_g, (0.20, -0.26, 0.22), (0.68, 0.022, 0.028), rot_euler=(0, -0.08, 0))
    bm_g.normal_update()
    bm_g.to_mesh(mesh_gate)
    bm_g.free()

    gate_obj = bpy.data.objects.new("HighwayWarningGate", mesh_gate)
    gate_obj.data.materials.append(mats["imu_glow"])
    gate_obj.location = (gx, gx_y, gz)
    link_obj(gate_obj, root)
    return ops_grp



def import_helicopters(root, mats):
    """Import real 3D AgustaWestland AW101 Rescue Helicopter (helicopter.glb) with separate spinning main & tail rotors."""
    heli_glb = BLENDER_DIR / "models" / "helicopter.glb"
    if not heli_glb.exists():
        return

    def build_single_helicopter(heli_name: str, loc, rot_euler, target_length=1.62):
        before_names = set(bpy.data.objects.keys())
        bpy.ops.import_scene.gltf(filepath=str(heli_glb))
        imp_names = set(bpy.data.objects.keys()) - before_names

        meshes = {
            bpy.data.objects[n].name: bpy.data.objects[n]
            for n in imp_names
            if n in bpy.data.objects and bpy.data.objects[n].type == "MESH"
        }
        body_m = next((m for k, m in meshes.items() if "windows" not in k and "rotor" not in k and "propellar" not in k), None)
        win_m = next((m for k, m in meshes.items() if "windows" in k), None)
        main_r = next((m for k, m in meshes.items() if "propellar" in k), None)
        tail_r = next((m for k, m in meshes.items() if "backrotor" in k), None)

        if not body_m or not main_r or not tail_r:
            for n in list(imp_names):
                if n in bpy.data.objects:
                    bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
            return None

        bpy.ops.object.select_all(action="DESELECT")
        for m in (body_m, win_m, main_r, tail_r):
            if not m:
                continue
            mw = m.matrix_world.copy()
            m.parent = None
            m.rotation_mode = "XYZ"
            m.matrix_world = mw
            m.select_set(True)
        bpy.context.view_layer.objects.active = body_m
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Assign Search & Rescue Coast Guard Livery to fuselage BEFORE joining windows
        body_m.data.materials.clear()
        body_m.data.materials.append(mats["heli_red_orange"])  # 0: High-vis rescue red-orange
        body_m.data.materials.append(mats["heli_white"])       # 1: Crisp alpine white cabin band
        body_m.data.materials.append(mats["ops_obsidian"])     # 2: Dark carbon landing gear & exhausts
        body_m.data.materials.append(mats["ops_glass_cyan"])   # 3: Glowing cyan rescue telemetry stripe
        for poly in body_m.data.polygons:
            c = poly.center
            if c.z < -3.05:
                poly.material_index = 2
            elif -1.18 <= c.z <= -0.92 and -7.2 < c.y < 3.6:
                poly.material_index = 3
            elif -2.35 < c.z < -1.18 and -6.8 < c.y < 2.5:
                poly.material_index = 1
            else:
                poly.material_index = 0

        if win_m:
            win_m.data.materials.clear()
            win_m.data.materials.append(mats["ops_glass_cyan"])
            for poly in win_m.data.polygons:
                poly.material_index = 0
            bpy.ops.object.select_all(action="DESELECT")
            body_m.select_set(True)
            win_m.select_set(True)
            bpy.context.view_layer.objects.active = body_m
            bpy.ops.object.join()

        # Compute body center and scale factor
        b_verts = [v.co for v in body_m.data.vertices]
        min_x = min(v.x for v in b_verts)
        max_x = max(v.x for v in b_verts)
        min_y = min(v.y for v in b_verts)
        max_y = max(v.y for v in b_verts)
        min_z = min(v.z for v in b_verts)
        max_z = max(v.z for v in b_verts)
        bc = Vector((0.5 * (min_x + max_x), 0.5 * (min_y + max_y), 0.5 * (min_z + max_z)))
        span_y = max(0.01, max_y - min_y)
        s = target_length / span_y

        for v in body_m.data.vertices:
            v.co = (v.co - bc) * s
        body_m.data.update()
        body_m.name = heli_name
        body_m.rotation_mode = "XYZ"

        # Configure Main Top Rotor centered at its hub
        mr_verts = [v.co for v in main_r.data.vertices]
        mr_c = Vector((
            0.5 * (min(v.x for v in mr_verts) + max(v.x for v in mr_verts)),
            0.5 * (min(v.y for v in mr_verts) + max(v.y for v in mr_verts)),
            0.5 * (min(v.z for v in mr_verts) + max(v.z for v in mr_verts)),
        ))
        max_r_dist = max(((v.co - mr_c).xy.length for v in main_r.data.vertices), default=1.0)
        main_r.data.materials.clear()
        main_r.data.materials.append(mats["ops_obsidian"])
        main_r.data.materials.append(mats["imu_glow"])
        for poly in main_r.data.polygons:
            r_dist = (poly.center - mr_c).xy.length
            poly.material_index = 1 if r_dist > 0.80 * max_r_dist else 0
        for v in main_r.data.vertices:
            v.co = (v.co - mr_c) * s
        main_r.data.update()
        main_r.name = f"{heli_name}_Rotor"
        main_r.rotation_mode = "XYZ"
        main_r.location = (mr_c - bc) * s
        link_obj(main_r, body_m)

        # Configure Tail Rotor centered at its hub
        tr_verts = [v.co for v in tail_r.data.vertices]
        tr_c = Vector((
            0.5 * (min(v.x for v in tr_verts) + max(v.x for v in tr_verts)),
            0.5 * (min(v.y for v in tr_verts) + max(v.y for v in tr_verts)),
            0.5 * (min(v.z for v in tr_verts) + max(v.z for v in tr_verts)),
        ))
        tail_r.data.materials.clear()
        tail_r.data.materials.append(mats["imu_glow"])
        for poly in tail_r.data.polygons:
            poly.material_index = 0
        for v in tail_r.data.vertices:
            v.co = (v.co - tr_c) * s
        tail_r.data.update()
        tail_r.name = f"{heli_name}_TailRotor"
        tail_r.rotation_mode = "XYZ"
        tail_r.location = (tr_c - bc) * s
        link_obj(tail_r, body_m)

        body_m.location = loc
        body_m.rotation_euler = rot_euler
        link_obj(body_m, root)

        # Cleanup empty nodes from glTF import
        keep = {body_m, main_r, tail_r}
        for n in list(imp_names):
            obj = bpy.data.objects.get(n)
            if obj and obj not in keep:
                bpy.data.objects.remove(obj, do_unlink=True)
        return body_m

    # 1. Primary Rescue Helicopter patrolling over the Landslide Slip Zone & Highway Corridor
    build_single_helicopter(
        "Rescue_Helicopter_01",
        loc=(-0.55, -0.45, 2.78),
        rot_euler=(0.08, -0.05, -0.85),
        target_length=1.68,
    )
    # 2. Secondary Command Helicopter hovering/banking over the Data Center Helipad & Valley
    build_single_helicopter(
        "Rescue_Helicopter_02",
        loc=(4.65, -1.35, 2.38),
        rot_euler=(0.06, 0.04, 2.35),
        target_length=1.46,
    )


def import_web_vehicles(root, mats):
    """Import multi-part 3D vehicles from frontend/assets/blender/models/cars_big_set.glb and place them along the mountain highway."""
    cars_glb = BLENDER_DIR / "models" / "cars_big_set.glb"
    if not cars_glb.exists():
        return

    before_names = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=str(cars_glb))
    imported_names = set(bpy.data.objects.keys()) - before_names

    for mat in bpy.data.materials:
        if "lospec" in mat.name.lower() or "material.001" in mat.name.lower():
            mat.diffuse_color = (0.28, 0.68, 0.88, 1.0)
            mat.metallic = 0.25
            mat.roughness = 0.24
            if mat.node_tree:
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    bsdf.inputs["Roughness"].default_value = 0.24
                    bsdf.inputs["Metallic"].default_value = 0.25

    def extract_vehicle_mesh(car_name: str, target_width=0.33):
        car_obj = bpy.data.objects.get(car_name)
        if not car_obj or car_obj.type != "MESH":
            return None
        parts = [car_obj] + [ch for ch in car_obj.children_recursive if ch.type == "MESH"]
        bpy.ops.object.select_all(action="DESELECT")
        for p in parts:
            p.select_set(True)
        bpy.context.view_layer.objects.active = car_obj
        bpy.ops.object.duplicate()
        dup_parts = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        if not dup_parts:
            return None
        # CRITICAL FIX: Set rotation_mode = "XYZ" BEFORE assigning matrix_world so quaternion rotations are preserved!
        for d in dup_parts:
            mw = d.matrix_world.copy()
            d.parent = None
            d.rotation_mode = "XYZ"
            d.matrix_world = mw
        bpy.context.view_layer.objects.active = dup_parts[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        if len(dup_parts) > 1:
            bpy.ops.object.join()
        joined = bpy.context.view_layer.objects.active
        joined.rotation_mode = "XYZ"
        joined.location = (0, 0, 0)
        joined.rotation_euler = (0, 0, 0)
        joined.scale = (1, 1, 1)

        verts = [v.co for v in joined.data.vertices]
        min_x = min(v.x for v in verts)
        max_x = max(v.x for v in verts)
        min_y = min(v.y for v in verts)
        max_y = max(v.y for v in verts)
        min_z = min(v.z for v in verts)
        cx = 0.5 * (min_x + max_x)
        cy = 0.5 * (min_y + max_y)
        span_x = max(0.01, max_x - min_x)
        s = target_width / span_x
        for v in joined.data.vertices:
            v.co.x = (v.co.x - cx) * s
            v.co.y = (v.co.y - cy) * s
            v.co.z = (v.co.z - min_z) * s
        joined.data.update()
        return joined

    # 12 Moving Highway Vehicles along the expanded 10.8m highway
    vehicle_placements = [
        # Northbound (+Y_blender / -Z_three, right lane +0.21)
        ("Vehicle_01_PoliceCruiser", "car_police", -4.45, 0.21, True, 0.33),
        ("Vehicle_02_RescueBoxTruck", "car_removals", -2.80, 0.215, True, 0.36),
        ("Vehicle_04_GeoFieldPickup", "car_pickup", -1.15, 0.21, True, 0.33),
        ("Vehicle_05_TelemetryMinivan", "car_minivan", 0.50, 0.21, True, 0.33),
        ("Vehicle_08_SportCoupe", "car_beemer", 2.15, 0.21, True, 0.32),
        ("Vehicle_11_PatrolInterceptor", "car_police", 3.80, 0.21, True, 0.33),
        # Southbound (-Y_blender / +Z_three, left lane -0.21)
        ("Vehicle_07_SedanDaily", "car_daily", -3.95, -0.21, False, 0.32),
        ("Vehicle_03_CivilianCharger", "car_charger", -2.30, -0.21, False, 0.33),
        ("Vehicle_10_SurveyStriped", "car_sports_striped", -0.65, -0.21, False, 0.32),
        ("Vehicle_09_AlpineTourer", "car_sports_skiis", 1.00, -0.21, False, 0.32),
        ("Vehicle_06_EngineeringVan", "car_breadvan", 2.65, -0.21, False, 0.34),
        ("Vehicle_12_HeavyUtilityTruck", "car_pickup", 4.30, -0.21, False, 0.34),
    ]

    fleet_grp = bpy.data.objects.new("Highway_Vehicle_Fleet", None)
    link_obj(fleet_grp, root)

    for v_name, src_name, ry, lane_x, north, tw in vehicle_placements:
        v_obj = extract_vehicle_mesh(src_name, target_width=tw)
        if not v_obj:
            continue
        v_obj.name = v_name
        v_obj.rotation_mode = "XYZ"
        rc = road_center_x(ry)
        vx = rc + lane_x
        vz = terrain_height(rc, ry) + 0.030
        dx_dy = road_dx_dy(ry)
        yaw = math.atan2(dx_dy, -1.0) if north else math.atan2(-dx_dy, 1.0)
        v_obj.location = (vx, ry, vz)
        v_obj.rotation_euler = (0.0, 0.0, yaw)
        link_obj(v_obj, fleet_grp)

    # Place 3 command/utility vehicles parked on the Data Center Citadel forecourt flanking the entrance ramp
    parked_configs = [
        ("Vehicle_13_OpsUtilityPickup", "car_mini-pickup", 3.92, -2.32, 0.38, 0.33),
        ("Vehicle_14_OpsCommandSUV", "car_minivan", 4.38, -2.48, 0.22, 0.33),
        ("Vehicle_15_OpsPatrolUnit", "car_police", 5.95, -2.38, -0.28, 0.33),
    ]
    for p_name, p_src, px, py, pyaw, ptw in parked_configs:
        ops_veh = extract_vehicle_mesh(p_src, target_width=ptw)
        if ops_veh:
            ops_veh.name = p_name
            ops_veh.rotation_mode = "XYZ"
            pz = terrain_height(5.15, -0.55) + 0.24
            ops_veh.location = (px, py, pz)
            ops_veh.rotation_euler = (0.0, 0.0, pyaw)
            link_obj(ops_veh, fleet_grp)

    for name in list(imported_names):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)


def import_nasa_satellites(sat_grp, mats):
    """Import real NASA 3D spacecraft models (EO-1, DSCOVR, TDRS & CubeSat) and deploy a high-altitude orbital constellation."""
    templates = {}
    sat_files = {
        "eo1": ("nasa_eo1.glb", 0.08, 1.55),
        "dscovr": ("nasa_dscovr.glb", 0.09, 1.62),
        "tdrs": ("nasa_tdrs.glb", 1.0, 1.68),
        "cubesat": ("cubesat.glb", 1.0, 1.28),
    }

    for key, (fname, dec_ratio, target_span) in sat_files.items():
        fpath = BLENDER_DIR / "models" / fname
        if not fpath.exists():
            continue
        before_names = set(bpy.data.objects.keys())
        bpy.ops.import_scene.gltf(filepath=str(fpath))
        imp_names = set(bpy.data.objects.keys()) - before_names
        meshes = [bpy.data.objects[n] for n in imp_names if n in bpy.data.objects and bpy.data.objects[n].type == "MESH"]
        if not meshes:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        for m in meshes:
            mw = m.matrix_world.copy()
            m.parent = None
            m.rotation_mode = "XYZ"
            m.matrix_world = mw
            m.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        if len(meshes) > 1:
            bpy.ops.object.join()
        joined = bpy.context.view_layer.objects.active
        joined_name = joined.name
        joined.rotation_mode = "XYZ"
        joined.location = (0, 0, 0)
        joined.rotation_euler = (0, 0, 0)
        joined.scale = (1, 1, 1)

        if dec_ratio < 0.99:
            bm_clean = bmesh.new()
            bm_clean.from_mesh(joined.data)
            bmesh.ops.remove_doubles(bm_clean, verts=bm_clean.verts, dist=0.02)
            bm_clean.normal_update()
            bm_clean.to_mesh(joined.data)
            bm_clean.free()

            mod = joined.modifiers.new("DecimateSat", "DECIMATE")
            mod.ratio = dec_ratio
            bpy.ops.object.modifier_apply(modifier="DecimateSat")

        verts = [v.co for v in joined.data.vertices]
        min_v = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
        max_v = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
        center = 0.5 * (min_v + max_v)
        span = max(0.01, max(max_v - min_v))
        scale_f = target_span / span
        for v in joined.data.vertices:
            v.co = (v.co - center) * scale_f
        joined.data.update()

        # Assign clean procedural spacecraft materials (Gold Foil, Solar Array, Spacecraft White)
        for slot in joined.material_slots:
            m = slot.material
            if not m:
                continue
            mname = m.name.lower()
            if any(k in mname for k in ("gold", "brass", "foil", "yellow", "layer10", "layer6", "cube0", "seg20")):
                slot.material = mats["sat_gold_foil"]
            elif any(k in mname for k in ("solar", "panel", "layer1", "shiny_panel", "tex_01", "wing", "blue")):
                slot.material = mats["sat_solar_wing"]
            else:
                slot.material = mats["sat_bus_silver"]

        templates[key] = joined
        for name in list(imp_names):
            if name != joined_name and name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)

    # Deploy 8 High-Altitude Satellites (DSCOVR, EO-1, TDRS & CubeSat) spread wide across the sky
    sat_configs = [
        ("GNSS_Sat_01", "dscovr", (-3.85, 0.25, 0.15), (0.32, 0.22, -0.35), 1.00),
        ("GNSS_Sat_02", "tdrs", (-1.35, 0.65, 0.38), (0.38, 0.18, 0.45), 1.06),
        ("GNSS_Sat_03", "dscovr", (1.25, 0.28, 0.30), (0.30, -0.24, 0.28), 1.02),
        ("GNSS_Sat_04", "eo1", (3.65, -0.25, 0.14), (-0.22, -0.30, -0.42), 0.98),
        ("GNSS_Sat_05", "eo1", (-2.55, 1.85, 0.45), (0.24, -0.28, 0.62), 0.96),
        ("GNSS_Sat_06", "tdrs", (2.45, 1.55, 0.36), (0.35, 0.16, -0.25), 1.02),
        ("GNSS_Sat_07", "cubesat", (-4.85, 1.45, 0.28), (0.28, -0.22, 0.38), 1.05),
        ("GNSS_Sat_08", "cubesat", (4.85, 0.85, 0.24), (-0.26, 0.24, -0.32), 1.05),
    ]

    for s_name, t_key, loc, rot, sc in sat_configs:
        tmpl = templates.get(t_key) or next(iter(templates.values()), None)
        if not tmpl:
            continue
        sat_obj = bpy.data.objects.new(s_name, tmpl.data.copy())
        sat_obj.rotation_mode = "XYZ"
        sat_obj.location = loc
        sat_obj.rotation_euler = rot
        sat_obj.scale = (sc, sc, sc)
        link_obj(sat_obj, sat_grp)

    for tmpl in list(templates.values()):
        if tmpl.name in bpy.data.objects:
            bpy.data.objects.remove(tmpl, do_unlink=True)


def import_web_trees_and_forest(root, mats):
    """Import real 3D sculpted trees (pine_tree.glb, tree_01.glb, tree_02.glb) and populate a lush 64-tree alpine forest."""
    tree_templates = []
    tree_files = [
        ("pine_tree.glb", (0.042, 0.042, 0.032), {"Wood": mats["tree_bark"], "Light": mats["pine_emerald"]}),
        ("tree_01.glb", (0.052, 0.052, 0.068), {"Wood": mats["tree_bark"], "Leaves": mats["canopy_jade"]}),
        ("tree_02.glb", (0.055, 0.055, 0.068), {"Wood": mats["tree_bark"], "Leaves": mats["canopy_lime_green"]}),
    ]
    for idx, (fname, sc_xyz, mmap) in enumerate(tree_files):
        t_obj = import_single_glb_mesh(
            fname,
            f"TreeTemplate_{idx}",
            scale_xyz=sc_xyz,
            mat_map=mmap,
            exclude_names=("collider",),
        )
        if t_obj:
            tree_templates.append(t_obj)

    tree_spots = [
        # High Northwest & Southwest Mountain Ridge
        (-7.1, 4.4), (-6.6, 3.8), (-6.1, 3.1), (-6.8, 2.2), (-6.3, 1.4),
        (-6.9, 0.4), (-6.4, -0.6), (-6.7, -1.7), (-5.6, 4.5), (-5.1, 3.9),
        (-4.4, 4.2), (-3.7, 3.6), (-3.1, 4.6), (-2.3, 4.2), (-1.4, 4.5),
        (-0.5, 4.0), (0.5, 4.3), (1.3, 3.8), (1.8, 4.4), (-5.3, 2.5),
        (-4.7, 2.9), (-4.0, 2.6), (-5.6, -1.2), (-5.1, -2.0), (-5.8, -3.4),
        (-4.9, -4.0), (-4.1, -3.7), (-0.9, -3.8), (0.3, -4.2), (1.2, -3.9),
        (1.8, -3.5), (-2.7, 2.9), (-1.8, 3.1), (0.6, 2.9), (1.4, 2.5),
        (-7.0, -2.9), (-6.1, -4.3), (-5.4, 0.8), (-4.5, -1.1), (-3.8, -2.6),
        # Eastern Valley & Data Center Campus Perimeter
        (3.8, 4.1), (4.4, 3.5), (5.2, 4.0), (6.1, 3.2), (6.8, 2.4),
        (6.5, 1.5), (7.1, 0.6), (4.1, 2.3), (6.6, -2.6), (5.9, -3.4),
        (6.8, -3.9), (4.8, -4.0), (3.7, -3.8), (7.1, -1.2), (7.2, 3.8),
        (3.6, 1.2), (3.6, -2.5), (6.9, -0.3),
    ]

    rng = random.Random(108)
    spawned_trees = []
    if tree_templates:
        for idx, (tx, ty) in enumerate(tree_spots):
            tz = terrain_height(tx, ty)
            tmpl = tree_templates[idx % len(tree_templates)]
            inst = bpy.data.objects.new(f"TreeInst_{idx}", tmpl.data.copy())
            inst.rotation_mode = "XYZ"
            sc = 0.78 + (idx % 5) * 0.14
            inst.location = (tx, ty, tz - 0.02)
            inst.rotation_euler = (
                rng.uniform(-0.05, 0.05),
                rng.uniform(-0.05, 0.05),
                rng.uniform(0.0, math.pi * 2.0),
            )
            inst.scale = (sc, sc, sc * rng.uniform(0.92, 1.12))
            link_obj(inst)
            spawned_trees.append(inst)

        # Join all 3D trees into MountainForest mesh for ultra-fast WebGL draw calls
        bpy.ops.object.select_all(action="DESELECT")
        for inst in spawned_trees:
            inst.select_set(True)
        bpy.context.view_layer.objects.active = spawned_trees[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.join()
        forest_obj = bpy.context.view_layer.objects.active
        forest_obj.name = "MountainForest"
        link_obj(forest_obj, root)

        for tmpl in tree_templates:
            if tmpl.name in bpy.data.objects:
                bpy.data.objects.remove(tmpl, do_unlink=True)


def build_satellites_and_trees(root, mats):
    """Build 8 high-altitude NASA satellites, 2 rescue helicopters, 15 highway/campus vehicles, and 58 real 3D mountain trees."""
    sat_grp = bpy.data.objects.new("Satellite_Constellation", None)
    # Raised high into orbital space (z = 3.88, more than 2x higher!) well above mountain peaks & helicopters
    sat_grp.location = (-0.15, 0.25, 3.88)
    link_obj(sat_grp, root)

    import_nasa_satellites(sat_grp, mats)
    import_helicopters(root, mats)
    import_web_vehicles(root, mats)
    import_web_trees_and_forest(root, mats)


def setup_lighting_and_render_previews():
    """Configure Blender EEVEE lighting & camera to render studio previews, returning created objects."""
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    scene.render.film_transparent = True

    world = bpy.data.worlds.new("GeotechWorld")
    scene.world = world
    bg = world.node_tree.nodes.get("Background") if world.node_tree else None
    if bg:
        bg.inputs[0].default_value = (0.025, 0.11, 0.12, 1.0)
        bg.inputs[1].default_value = 1.25

    key_data = bpy.data.lights.new(name="KeyLight", type="SUN")
    key_data.energy = 4.0
    key_data.color = (0.94, 1.0, 0.97)
    key_obj = bpy.data.objects.new(name="KeyLight", object_data=key_data)
    key_obj.rotation_euler = (0.65, 0.35, -0.55)
    link_obj(key_obj)

    rim_data = bpy.data.lights.new(name="RimLight", type="AREA")
    rim_data.energy = 260.0
    rim_data.size = 8.5
    rim_data.color = (0.35, 0.92, 0.83)
    rim_obj = bpy.data.objects.new(name="RimLight", object_data=rim_data)
    rim_obj.location = (-7.5, 5.5, 6.2)
    rim_obj.rotation_euler = (-0.75, -0.55, 0.4)
    link_obj(rim_obj)

    fill_data = bpy.data.lights.new(name="SlipFillLight", type="POINT")
    fill_data.energy = 150.0
    fill_data.color = (1.0, 0.68, 0.22)
    fill_obj = bpy.data.objects.new(name="SlipFillLight", object_data=fill_data)
    fill_obj.location = (-1.2, -3.2, 2.8)
    link_obj(fill_obj)

    ops_oz = terrain_height(5.15, -0.55)
    ctrl_light_data = bpy.data.lights.new(name="ControlRoomLight", type="POINT")
    ctrl_light_data.energy = 95.0
    ctrl_light_data.color = (0.28, 0.96, 0.92)
    ctrl_light_obj = bpy.data.objects.new(name="ControlRoomLight", object_data=ctrl_light_data)
    ctrl_light_obj.location = (5.15, -0.75, ops_oz + 1.12)
    link_obj(ctrl_light_obj)

    cam_data = bpy.data.cameras.new(name="RenderCam")
    cam_data.lens = 34.0
    cam_obj = bpy.data.objects.new(name="RenderCam", object_data=cam_data)
    scene.camera = cam_obj
    link_obj(cam_obj)

    def look_at(cam, pos, target):
        cam.location = Vector(pos)
        direction = Vector(target) - Vector(pos)
        rot_quat = direction.to_track_quat("-Z", "Y")
        cam.rotation_euler = rot_quat.to_euler()

    look_at(cam_obj, (-2.4, -10.2, 4.8), (0.0, -0.1, 0.65))
    hero_png = BLENDER_DIR / "hero_preview.png"
    scene.render.filepath = str(hero_png)
    bpy.ops.render.render(write_still=True)

    look_at(cam_obj, (1.4, -10.6, 5.1), (0.35, 0.0, 0.55))
    story_png = BLENDER_DIR / "story_preview.png"
    scene.render.filepath = str(story_png)
    bpy.ops.render.render(write_still=True)

    return (key_obj, rim_obj, fill_obj, ctrl_light_obj, cam_obj)


def build_blender_animations():
    """Author 180-frame Blender keyframe animations for the 12 highway vehicles, 2 rescue helicopters + rotors, Data Center radar/dishes, Control Room sliding doors + hologram + screen scanner, 2 survey drones, and high-altitude NASA satellites."""
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 180
    scene.render.fps = 30

    beacon = bpy.data.objects.get("OpsBeaconCore")
    dish = bpy.data.objects.get("OpsTrackingDish")
    dish2 = bpy.data.objects.get("OpsSecondaryDish")
    drone = bpy.data.objects.get("OpsSurveyDrone")
    drone2 = bpy.data.objects.get("OpsRescueDrone")
    sat_grp = bpy.data.objects.get("Satellite_Constellation")

    door_left = bpy.data.objects.get("OpsDoor_Left")
    door_right = bpy.data.objects.get("OpsDoor_Right")
    holo_terrain = bpy.data.objects.get("OpsHoloTerrain")
    scr_scanner = bpy.data.objects.get("OpsScreenScanner")

    heli1 = bpy.data.objects.get("Rescue_Helicopter_01")
    heli1_rotor = bpy.data.objects.get("Rescue_Helicopter_01_Rotor")
    heli1_tail = bpy.data.objects.get("Rescue_Helicopter_01_TailRotor")
    heli2 = bpy.data.objects.get("Rescue_Helicopter_02")
    heli2_rotor = bpy.data.objects.get("Rescue_Helicopter_02_Rotor")
    heli2_tail = bpy.data.objects.get("Rescue_Helicopter_02_TailRotor")

    vehicle_specs = [
        ("Vehicle_01_PoliceCruiser", -4.45, 0.21, True, 0.92),
        ("Vehicle_02_RescueBoxTruck", -2.80, 0.215, True, 0.92),
        ("Vehicle_04_GeoFieldPickup", -1.15, 0.21, True, 0.92),
        ("Vehicle_05_TelemetryMinivan", 0.50, 0.21, True, 0.92),
        ("Vehicle_08_SportCoupe", 2.15, 0.21, True, 0.92),
        ("Vehicle_11_PatrolInterceptor", 3.80, 0.21, True, 0.92),
        ("Vehicle_07_SedanDaily", -3.95, -0.21, False, 0.86),
        ("Vehicle_03_CivilianCharger", -2.30, -0.21, False, 0.86),
        ("Vehicle_10_SurveyStriped", -0.65, -0.21, False, 0.86),
        ("Vehicle_09_AlpineTourer", 1.00, -0.21, False, 0.86),
        ("Vehicle_06_EngineeringVan", 2.65, -0.21, False, 0.86),
        ("Vehicle_12_HeavyUtilityTruck", 4.30, -0.21, False, 0.86),
    ]

    keyframes = (1, 45, 90, 115, 135, 165, 180)
    for frame in keyframes:
        scene.frame_set(frame)
        t = (frame - 1) / 179.0
        ang = t * math.pi * 2.0

        if beacon:
            beacon.rotation_euler = (0.0, 0.0, ang * 2.0)
            beacon.keyframe_insert(data_path="rotation_euler", frame=frame)
        if dish:
            dish.rotation_euler = (math.sin(ang) * 0.12, 0.0, math.sin(ang) * 0.45)
            dish.keyframe_insert(data_path="rotation_euler", frame=frame)
        if dish2:
            dish2.rotation_euler = (math.cos(ang) * 0.10, 0.0, -math.sin(ang) * 0.38)
            dish2.keyframe_insert(data_path="rotation_euler", frame=frame)

        # Animate Control Room Sliding Doors (closed at frame 1, slide wide open during frames 115..165)
        door_open = 1.0 if 115 <= frame <= 165 else 0.0
        if door_left:
            door_left.location = (-0.56 * door_open, -1.52, 0.24)
            door_left.keyframe_insert(data_path="location", frame=frame)
        if door_right:
            door_right.location = (0.56 * door_open, -1.52, 0.24)
            door_right.keyframe_insert(data_path="location", frame=frame)
        if holo_terrain:
            holo_terrain.rotation_euler = (0.0, 0.0, ang * 2.0)
            holo_terrain.location = (0.0, -0.18, 0.66 + math.sin(ang * 2.0) * 0.025)
            holo_terrain.keyframe_insert(data_path="rotation_euler", frame=frame)
            holo_terrain.keyframe_insert(data_path="location", frame=frame)
        if scr_scanner:
            scr_scanner.location = (math.sin(ang * 2.0) * 0.36, 0.0, 0.0)
            scr_scanner.keyframe_insert(data_path="location", frame=frame)

        # Animate Primary & Secondary Rescue Helicopters and high-speed spinning rotors
        if heli1:
            hx1 = -0.35 + math.cos(ang) * 1.95
            hy1 = -0.25 + math.sin(ang * 2.0) * 1.15
            hz1 = 2.78 + math.sin(ang) * 0.18
            vx1 = -math.sin(ang) * 1.95
            vy1 = math.cos(ang * 2.0) * 2.30
            hyaw1 = math.atan2(vx1, -vy1)
            heli1.location = (hx1, hy1, hz1)
            heli1.rotation_euler = (0.10, math.sin(ang) * 0.12, hyaw1)
            heli1.keyframe_insert(data_path="location", frame=frame)
            heli1.keyframe_insert(data_path="rotation_euler", frame=frame)
        if heli1_rotor:
            heli1_rotor.rotation_euler = (0.0, 0.0, ang * 18.0)
            heli1_rotor.keyframe_insert(data_path="rotation_euler", frame=frame)
        if heli1_tail:
            heli1_tail.rotation_euler = (ang * 24.0, 0.0, 0.0)
            heli1_tail.keyframe_insert(data_path="rotation_euler", frame=frame)

        if heli2:
            hx2 = 4.65 + math.sin(ang) * 1.35
            hy2 = -1.15 + math.cos(ang) * 1.15
            hz2 = 2.38 + math.cos(ang * 2.0) * 0.14
            vx2 = math.cos(ang) * 1.35
            vy2 = -math.sin(ang) * 1.15
            hyaw2 = math.atan2(vx2, -vy2)
            heli2.location = (hx2, hy2, hz2)
            heli2.rotation_euler = (0.08, -math.cos(ang) * 0.10, hyaw2)
            heli2.keyframe_insert(data_path="location", frame=frame)
            heli2.keyframe_insert(data_path="rotation_euler", frame=frame)
        if heli2_rotor:
            heli2_rotor.rotation_euler = (0.0, 0.0, -ang * 18.0)
            heli2_rotor.keyframe_insert(data_path="rotation_euler", frame=frame)
        if heli2_tail:
            heli2_tail.rotation_euler = (-ang * 24.0, 0.0, 0.0)
            heli2_tail.keyframe_insert(data_path="rotation_euler", frame=frame)

        if drone:
            dx = 2.15 + math.cos(ang) * 2.35
            dy = -0.65 + math.sin(ang * 2.0) * 0.85
            dz = terrain_height(dx, dy) + 1.18 + math.sin(ang) * 0.18
            drone.location = (dx, dy, dz)
            drone.rotation_euler = (math.sin(ang) * 0.08, math.cos(ang) * 0.10, ang)
            drone.keyframe_insert(data_path="location", frame=frame)
            drone.keyframe_insert(data_path="rotation_euler", frame=frame)
        if drone2:
            dx2 = -1.35 + math.sin(ang) * 1.85
            dy2 = 0.65 + math.cos(ang * 2.0) * 0.95
            dz2 = terrain_height(dx2, dy2) + 1.28 + math.cos(ang) * 0.16
            drone2.location = (dx2, dy2, dz2)
            drone2.rotation_euler = (math.cos(ang) * 0.08, math.sin(ang) * 0.10, -ang)
            drone2.keyframe_insert(data_path="location", frame=frame)
            drone2.keyframe_insert(data_path="rotation_euler", frame=frame)
        if sat_grp:
            sat_grp.location = (-0.15 + math.sin(ang) * 0.42, 0.25 + math.cos(ang) * 0.24, 3.88)
            sat_grp.keyframe_insert(data_path="location", frame=frame)

        for v_name, ry0, lane_x, north, spd in vehicle_specs:
            v_obj = bpy.data.objects.get(v_name)
            if not v_obj:
                continue
            v_obj.rotation_mode = "XYZ"
            direction = 1.0 if north else -1.0
            span = 10.0
            ry = ((ry0 + 5.0 + direction * t * spd * 4.2) % span) - 5.0
            rc = road_center_x(ry)
            vx = rc + lane_x
            vz = terrain_height(rc, ry) + 0.030
            dx_dy = road_dx_dy(ry)
            yaw = math.atan2(dx_dy, -1.0) if north else math.atan2(-dx_dy, 1.0)
            v_obj.location = (vx, ry, vz)
            v_obj.rotation_euler = (0.0, 0.0, yaw)
            v_obj.keyframe_insert(data_path="location", frame=frame)
            v_obj.keyframe_insert(data_path="rotation_euler", frame=frame)

    scene.frame_set(1)


def purge_unused_datablocks():
    """Remove unused materials and heavy textures from imported GLBs so landslide_twin.glb stays compact and fast."""
    used_mats = set()
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data:
            for m in obj.data.materials:
                if m:
                    used_mats.add(m)
    for m in list(bpy.data.materials):
        if m not in used_mats:
            bpy.data.materials.remove(m, do_unlink=True)

    used_imgs = set()
    for m in used_mats:
        if m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    used_imgs.add(n.image)
    for img in list(bpy.data.images):
        if img not in used_imgs:
            bpy.data.images.remove(img, do_unlink=True)


def main():
    BLENDER_DIR.mkdir(parents=True, exist_ok=True)
    clear_scene()

    mats = {
        "terrain_surface": make_material(
            "TerrainSurfaceMat",
            base_color=(0.08, 0.44, 0.36, 1.0),
            metallic=0.06,
            roughness=0.68,
            use_vertex_color=True,
        ),
        "contour_line": make_material(
            "ContourLineMat",
            base_color=(0.38, 0.92, 0.82, 1.0),
            emission_color=(0.35, 0.88, 0.78),
            emission_strength=0.65,
            alpha=0.52,
        ),
        "soil_strata": make_material(
            "SoilStrataMat",
            base_color=(0.34, 0.25, 0.16, 1.0),
            metallic=0.05,
            roughness=0.78,
        ),
        "bedrock_strata": make_material(
            "BedrockStrataMat",
            base_color=(0.12, 0.20, 0.24, 1.0),
            metallic=0.22,
            roughness=0.82,
        ),
        "slip_surface": make_material(
            "SlipSurfaceMat",
            base_color=(1.0, 0.52, 0.08, 1.0),
            metallic=0.15,
            roughness=0.28,
            emission_color=(1.0, 0.45, 0.05),
            emission_strength=1.55,
            alpha=0.82,
        ),
        "unstable_wedge": make_material(
            "UnstableWedgeMat",
            base_color=(0.24, 0.52, 0.36, 1.0),
            metallic=0.08,
            roughness=0.56,
            use_vertex_color=True,
        ),
        "groundwater": make_material(
            "GroundwaterMat",
            base_color=(0.12, 0.68, 0.96, 1.0),
            metallic=0.12,
            roughness=0.20,
            emission_color=(0.14, 0.65, 0.95),
            emission_strength=0.78,
            alpha=0.64,
        ),
        "asphalt": make_material(
            "AsphaltRoadMat",
            base_color=(0.10, 0.16, 0.20, 1.0),
            metallic=0.18,
            roughness=0.72,
        ),
        "concrete": make_material(
            "ConcreteWallMat",
            base_color=(0.56, 0.68, 0.66, 1.0),
            metallic=0.12,
            roughness=0.58,
        ),
        "steel_housing": make_material(
            "SteelHousingMat",
            base_color=(0.78, 0.92, 0.90, 1.0),
            metallic=0.68,
            roughness=0.26,
        ),
        "ops_obsidian": make_material(
            "OpsObsidianMat",
            base_color=(0.08, 0.18, 0.24, 1.0),
            metallic=0.78,
            roughness=0.22,
        ),
        "ops_glass_cyan": make_material(
            "OpsGlassCyanMat",
            base_color=(0.18, 0.92, 0.98, 1.0),
            metallic=0.85,
            roughness=0.10,
            emission_color=(0.14, 0.86, 0.96),
            emission_strength=1.95,
        ),
        "solar_panel": make_material(
            "SolarPanelMat",
            base_color=(0.06, 0.34, 0.64, 1.0),
            metallic=0.78,
            roughness=0.16,
            emission_color=(0.10, 0.52, 0.82),
            emission_strength=0.42,
        ),
        "gnss_rover_dome": make_material(
            "GNSSRoverDomeMat",
            base_color=(0.36, 0.96, 0.86, 1.0),
            metallic=0.2,
            roughness=0.18,
            emission_color=(0.36, 0.92, 0.83),
            emission_strength=1.5,
        ),
        "gnss_base_dome": make_material(
            "GNSSBaseDomeMat",
            base_color=(0.84, 0.94, 0.45, 1.0),
            metallic=0.25,
            roughness=0.18,
            emission_color=(0.84, 0.94, 0.45),
            emission_strength=1.7,
        ),
        "ring_teal": make_material(
            "RingTealMat",
            base_color=(0.36, 0.92, 0.83, 1.0),
            emission_color=(0.36, 0.92, 0.83),
            emission_strength=1.45,
            alpha=0.78,
        ),
        "ring_lime": make_material(
            "RingLimeMat",
            base_color=(0.84, 0.94, 0.45, 1.0),
            emission_color=(0.84, 0.94, 0.45),
            emission_strength=1.55,
            alpha=0.84,
        ),
        "imu_amber": make_material(
            "IMUAmberMat",
            base_color=(0.95, 0.55, 0.12, 1.0),
            metallic=0.48,
            roughness=0.28,
            emission_color=(1.0, 0.55, 0.08),
            emission_strength=0.75,
        ),
        "imu_glow": make_material(
            "IMUGlowMat",
            base_color=(1.0, 0.69, 0.12, 1.0),
            emission_color=(1.0, 0.62, 0.08),
            emission_strength=2.1,
        ),
        "rain_cyan": make_material(
            "RainCyanMat",
            base_color=(0.48, 0.84, 0.98, 1.0),
            metallic=0.38,
            roughness=0.20,
            emission_color=(0.48, 0.83, 0.98),
            emission_strength=1.05,
        ),
        "water_glow": make_material(
            "WaterGlowMat",
            base_color=(0.22, 0.74, 0.97, 1.0),
            emission_color=(0.22, 0.74, 0.97),
            emission_strength=1.65,
            alpha=0.82,
        ),
        "tree_bark": make_material(
            "TreeBarkMat",
            base_color=(0.36, 0.22, 0.12, 1.0),
            metallic=0.04,
            roughness=0.85,
        ),
        "pine_emerald": make_material(
            "PineEmeraldMat",
            base_color=(0.06, 0.48, 0.34, 1.0),
            metallic=0.05,
            roughness=0.62,
        ),
        "canopy_jade": make_material(
            "CanopyJadeMat",
            base_color=(0.12, 0.60, 0.40, 1.0),
            metallic=0.05,
            roughness=0.58,
        ),
        "canopy_lime_green": make_material(
            "CanopyLimeGreenMat",
            base_color=(0.22, 0.68, 0.38, 1.0),
            metallic=0.06,
            roughness=0.55,
        ),
        "heli_red_orange": make_material(
            "HeliRescueRedMat",
            base_color=(0.98, 0.28, 0.08, 1.0),
            metallic=0.45,
            roughness=0.22,
            emission_color=(0.98, 0.28, 0.08),
            emission_strength=0.35,
        ),
        "heli_white": make_material(
            "HeliAlpineWhiteMat",
            base_color=(0.95, 0.98, 1.0, 1.0),
            metallic=0.32,
            roughness=0.20,
        ),
        "sat_gold_foil": make_material(
            "SatGoldFoilMat",
            base_color=(0.98, 0.76, 0.18, 1.0),
            metallic=0.88,
            roughness=0.18,
            emission_color=(0.98, 0.74, 0.16),
            emission_strength=0.45,
        ),
        "sat_solar_wing": make_material(
            "SatSolarWingMat",
            base_color=(0.08, 0.42, 0.76, 1.0),
            metallic=0.85,
            roughness=0.14,
            emission_color=(0.14, 0.58, 0.92),
            emission_strength=0.52,
        ),
        "sat_bus_silver": make_material(
            "SatBusSilverMat",
            base_color=(0.86, 0.96, 0.94, 1.0),
            metallic=0.72,
            roughness=0.20,
            emission_color=(0.48, 0.94, 0.84),
            emission_strength=0.32,
        ),
    }

    root = bpy.data.objects.new("LandslideDigitalTwin", None)
    link_obj(root)

    build_geological_block(root, mats)
    build_mountain_road_and_wall(root, mats)

    hw_templates = load_hardware_templates(mats)
    build_gnss_station("GNSS_Station_Crown", -4.35, 1.15, root, mats, is_base=False, templates=hw_templates)
    build_gnss_station("GNSS_Station_Mid", -1.05, -0.45, root, mats, is_base=False, templates=hw_templates)
    build_gnss_station("GNSS_Station_Toe", 1.35, 0.85, root, mats, is_base=False, templates=hw_templates)
    build_gnss_station("GNSS_Base_CORS", -5.65, -2.55, root, mats, is_base=True, templates=hw_templates)

    build_imu_borehole(root, mats, templates=hw_templates)
    build_rain_and_piezometer(root, mats, templates=hw_templates)
    build_operations_hub(root, mats, templates=hw_templates)
    cleanup_hardware_templates(hw_templates)

    build_satellites_and_trees(root, mats)
    purge_unused_datablocks()
    build_blender_animations()

    studio_objs = setup_lighting_and_render_previews()

    # Save .blend WITH studio lights, camera, and vibrant material diffuse colors!
    blend_path = BLENDER_DIR / "landslide_twin.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    # Remove studio lights & camera before exporting the WebGL .glb asset
    for obj in studio_objs:
        if obj and obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)

    glb_path = BLENDER_DIR / "landslide_twin.glb"
    # CRITICAL FIX: export_apply=False so frame-1 vehicle yaw rotations are NOT baked into mesh vertices!
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        export_yup=True,
        export_apply=False,
        export_materials="EXPORT",
    )

    glb_bytes = glb_path.read_bytes()
    glb_b64 = base64.b64encode(glb_bytes).decode("ascii")

    def to_three(x, y, z=None):
        if z is None:
            z = terrain_height(x, y)
        return [round(x, 3), round(z, 3), round(-y, 3)]

    ops_oz = terrain_height(5.15, -0.55)
    anchors = {
        "gnss_crown": to_three(-4.35, 1.15, terrain_height(-4.35, 1.15) + 1.42),
        "gnss_mid": to_three(-1.05, -0.45, terrain_height(-1.05, -0.45) + 1.42),
        "gnss_toe": to_three(1.35, 0.85, terrain_height(1.35, 0.85) + 1.42),
        "gnss_base": to_three(-5.65, -2.55, terrain_height(-5.65, -2.55) + 1.62),
        "imu_borehole": to_three(-1.48, -0.68, terrain_height(-1.48, -0.68) + 0.52),
        "rain_gauge": to_three(-3.25, -2.05, terrain_height(-3.25, -2.05) + 0.88),
        "piezometer": to_three(-2.25, -TERRAIN_DEPTH / 2 + 0.32, terrain_height(-2.25, -TERRAIN_DEPTH / 2 + 0.32) + 0.46),
        "ops_hub": to_three(5.15, -0.55, ops_oz + 1.65),
        "ops_entrance": to_three(5.15, -0.55 - 1.52, ops_oz + 0.68),
        "ops_holo_table": to_three(5.15, -0.55 - 0.18, ops_oz + 0.68),
        "ops_control_room": to_three(5.15, -0.55 + 0.36, ops_oz + 0.86),
        "highway_gate": to_three(road_center_x(-1.65), -1.65, terrain_height(road_center_x(-1.65), -1.65) + 0.68),
    }

    road_profile = [
        round(
            terrain_height(
                road_center_x(-5.0 + i * (10.0 / 50.0)),
                -5.0 + i * (10.0 / 50.0),
            ),
            4,
        )
        for i in range(51)
    ]

    js_content = f"""// Auto-generated by scripts/generate_blender_landing.py using Blender {bpy.app.version_string}
export const BLENDER_META = {json.dumps({"blenderVersion": bpy.app.version_string, "glbBytes": len(glb_bytes), "anchors": anchors, "roadProfile": road_profile}, indent=2)};

export const LANDSLIDE_TWIN_GLB_B64 = "{glb_b64}";

export function decodeBlenderGLB() {{
    const binary = atob(LANDSLIDE_TWIN_GLB_B64);
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {{
        bytes[i] = binary.charCodeAt(i);
    }}
    return bytes.buffer;
}}
"""
    JS_OUT.write_text(js_content, encoding="utf-8")
    print(f"SUCCESS: Exported {glb_path.name} ({len(glb_bytes):,} bytes) and {JS_OUT.name}")


if __name__ == "__main__":
    main()

