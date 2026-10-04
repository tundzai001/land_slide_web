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


def terrain_height(x: float, y: float) -> float:
    """
    Compute realistic mountain slope height in Blender coordinates:
      x in [-5.5, 5.5]: slope descends from -X (mountain crest) to +X (valley/highway)
      y in [-4.0, 4.0]: front cutaway (-Y) to back ridge (+Y)
    """
    nx = x / 5.5
    ny = y / 4.0

    # Primary mountain slope profile
    slope = -1.68 * nx + 0.36 * math.cos(nx * 1.35) + 0.24 * ny

    # Valley bench for highway around x in [1.9, 3.1]
    road_center = 2.45 + 0.18 * math.sin(ny * 1.5)
    dist_road = abs(x - road_center)
    if dist_road < 0.88:
        t = dist_road / 0.88
        smooth = t * t * (3.0 - 2.0 * t)
        road_elev = -0.58 + 0.07 * ny
        slope = road_elev * (1.0 - smooth) + slope * smooth

    # Counter-ridge on far right (+X > 3.05) for Operations Command Hub overlook
    if x > 3.05:
        ridge_t = min(1.0, (x - 3.05) / 2.15)
        slope += 0.88 * (ridge_t * ridge_t * (3.0 - 2.0 * ridge_t))

    # Multi-fractal geological ridge detail + subtle drainage gully at y ~ 1.4
    n1 = noise.noise(Vector((x * 0.42 + 3.1, y * 0.42 + 1.7, 0.5)))
    n2 = noise.noise(Vector((x * 0.92 - 2.4, y * 0.92 + 4.2, 1.3))) * 0.32
    n3 = noise.noise(Vector((x * 1.85 + 0.7, y * 1.85 - 1.2, 2.7))) * 0.08
    road_damp = min(1.0, max(0.06, (dist_road - 0.36) / 0.55))

    # Eroded mountain stream gully on the upper-back slope (y around 1.55)
    stream_y = 1.55 - 0.22 * nx
    dist_stream = abs(y - stream_y)
    gully = 0.0
    if x < 1.8 and dist_stream < 0.55:
        gt = 1.0 - (dist_stream / 0.55)
        gully = -0.18 * (gt * gt) * road_damp

    detail = (n1 * 0.46 + n2 + n3) * road_damp + gully
    raw_h = slope + detail
    terrace = math.sin(raw_h * 5.0) * 0.045 * road_damp
    return raw_h + terrace


def link_obj(obj, parent=None):
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
    """Build sculpted mountain terrain with vertex colors, topographic contours, 3-layer cutaway + pedestal, slip zone, and groundwater."""
    nx, ny = 76, 58
    width, depth = 11.0, 8.0
    base_z = -2.35

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

    # Paint vertex colors based on elevation, slope steepness, road proximity, and landslide scar proximity
    c_high_forest = (0.04, 0.28, 0.22, 1.0)
    c_mid_meadow = (0.08, 0.42, 0.34, 1.0)
    c_steep_rock = (0.16, 0.27, 0.28, 1.0)
    c_scar_soil = (0.38, 0.27, 0.16, 1.0)
    c_valley = (0.05, 0.22, 0.21, 1.0)

    for face in bm.faces:
        for loop in face.loops:
            v = loop.vert
            vx, vy, vz = v.co.x, v.co.y, v.co.z
            elev_t = (vz + 1.2) / 3.4
            col = lerp_color(c_valley, c_mid_meadow, min(1.0, elev_t * 1.3))
            if elev_t > 0.55:
                col = lerp_color(col, c_high_forest, (elev_t - 0.55) / 0.45)

            # Steep slope rock exposure
            steepness = 1.0 - max(0.0, v.normal.z)
            if steepness > 0.26:
                col = lerp_color(col, c_steep_rock, min(1.0, (steepness - 0.26) * 2.8))

            # Landslide zone weathered soil tint
            dx_s = (vx - (-0.82)) / 2.25
            dy_s = (vy - (-0.25)) / 1.95
            dist_scar = math.sqrt(dx_s * dx_s + dy_s * dy_s)
            if dist_scar < 1.15:
                scar_w = max(0.0, 1.0 - dist_scar / 1.15) ** 1.4
                col = lerp_color(col, c_scar_soil, scar_w * 0.72)

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
            z_mid0 = max(base_z + 0.45, z_top0 - 0.85 - 0.14 * math.sin(x0 * 0.9))
            z_mid1 = max(base_z + 0.45, z_top1 - 0.85 - 0.14 * math.sin(x1 * 0.9))

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
    for _ in range(28):
        bx = rng.uniform(-width / 2 + 0.4, width / 2 - 0.4)
        bz_top = terrain_height(bx, -depth / 2)
        bz = rng.uniform(base_z + 0.3, bz_top - 0.25)
        br = rng.uniform(0.06, 0.16)
        bmesh.ops.create_icosphere(
            bm_soil if bz > bz_top - 0.85 else bm_rock,
            subdivisions=1,
            radius=br,
            matrix=Matrix.Translation((bx, -depth / 2 - 0.01, bz)) @ Matrix.Diagonal((1.4, 0.35, 0.75, 1.0)),
        )

    # Architectural Diorama Base Plinth & Depth Scale Tick Marks
    add_box(bm_rock, (0.0, 0.0, base_z - 0.12), (width + 0.24, depth + 0.24, 0.24))
    add_box(bm_rock, (0.0, 0.0, base_z - 0.28), (width + 0.48, depth + 0.48, 0.12))
    for tick_i in range(23):
        tx = -width / 2 + tick_i * 0.5
        add_box(bm_soil, (tx, -depth / 2 - 0.13, base_z - 0.12), (0.025, 0.04, 0.18 if tick_i % 2 == 0 else 0.10))

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
    cx, cy = -0.82, -0.25
    rx, ry = 2.15, 1.85
    rings, segs = 16, 48

    mesh_slip = bpy.data.meshes.new("SlipSurfaceMesh")
    bm_slip = bmesh.new()
    mesh_wedge = bpy.data.meshes.new("UnstableWedgeMesh")
    bm_wedge = bmesh.new()
    wedge_col_layer = bm_wedge.loops.layers.color.new("Col")

    slip_center_z = terrain_height(cx, cy) - 0.88
    wedge_center_z = terrain_height(cx, cy) + 0.035
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
            bowl_depth = 0.88 * (1.0 - (r_frac ** 1.6))
            s_ring.append(bm_slip.verts.new((px, py, surf_z - bowl_depth - 0.02)))

            # Rotational slump terrace steps inside the unstable landslide mass
            slump_step = 0.048 * math.sin(r_frac * 14.0 + math.cos(theta) * 2.0) * (1.0 - r_frac)
            w_ring.append(bm_wedge.verts.new((px, py, surf_z + 0.032 * (1.0 - 0.35 * r_frac) + slump_step)))
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

    # Paint vertex colors on UnstableWedge (disturbed earth + mossy patches + dark tension fracture bands)
    for face in bm_wedge.faces:
        for loop in face.loops:
            vx, vy, vz = loop.vert.co
            n_val = 0.5 + 0.5 * noise.noise(Vector((vx * 2.2, vy * 2.2, vz)))
            crack_band = math.sin((vx - cx) * 7.5 + math.sin(vy * 2.0) * 0.8)
            base_c = lerp_color((0.32, 0.25, 0.16, 1.0), (0.09, 0.42, 0.34, 1.0), n_val)
            if crack_band > 0.82 and vx < cx + 0.9:
                base_c = lerp_color(base_c, (0.78, 0.38, 0.08, 1.0), (crack_band - 0.82) / 0.18)
            loop[wedge_col_layer] = base_c

    # Sleek Precision Crown Scarp Perimeter Ring around the unstable wedge
    for s_idx in range(segs):
        nxt = (s_idx + 1) % segs
        v0 = wedge_rings[-1][s_idx].co
        v1 = wedge_rings[-1][nxt].co
        rad = 0.022 if v0.x < cx else 0.014
        add_strut(bm_slip, v0 + Vector((0, 0, 0.015)), v1 + Vector((0, 0, 0.015)), radius=rad, segs=6)

    # Front cutaway slip plane indicator band
    for i in range(22):
        fx0 = -2.85 + (i / 22) * 3.9
        fx1 = -2.85 + ((i + 1) / 22) * 3.9
        fy = -depth / 2 - 0.028
        norm0 = (fx0 - (-0.9)) / 1.9
        norm1 = (fx1 - (-0.9)) / 1.9
        fz0 = terrain_height(fx0, -depth / 2) - 0.22 - 0.62 * max(0.0, 1.0 - norm0 * norm0)
        fz1 = terrain_height(fx1, -depth / 2) - 0.22 - 0.62 * max(0.0, 1.0 - norm1 * norm1)
        sv1 = bm_slip.verts.new((fx0, fy, fz0 - 0.048))
        sv2 = bm_slip.verts.new((fx1, fy, fz1 - 0.048))
        sv3 = bm_slip.verts.new((fx1, fy, fz1 + 0.048))
        sv4 = bm_slip.verts.new((fx0, fy, fz0 + 0.048))
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
    wx_n, wy_n = 32, 26
    wt_verts = [[None] * wy_n for _ in range(wx_n)]
    for i in range(wx_n):
        x = -width / 2 + 0.06 + (i / (wx_n - 1)) * (width - 0.12)
        for j in range(wy_n):
            y = -depth / 2 + 0.06 + (j / (wy_n - 1)) * (depth - 0.12)
            surf_z = terrain_height(x, y)
            water_z = max(base_z + 0.42, surf_z - 0.90 + 0.10 * math.sin(x * 0.8 + y * 0.7))
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
        fy = -depth / 2 - 0.020
        wt_z0 = wt_verts[i][0].co.z
        wt_z1 = wt_verts[i + 1][0].co.z
        bot_z0 = max(base_z + 0.12, wt_z0 - 0.55)
        bot_z1 = max(base_z + 0.12, wt_z1 - 0.55)
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
    """Build detailed mountain highway with curbs, lane dashes, guardrails, streetlamps, tie-back retaining wall, and vehicles."""
    mesh_road = bpy.data.meshes.new("MountainRoadMesh")
    bm = bmesh.new()
    steps = 48
    half_w = 0.46
    depth = 8.0

    left_verts = []
    right_verts = []
    for j in range(steps):
        y = -depth / 2 + (j / (steps - 1)) * depth
        ny = y / 4.0
        rc = 2.45 + 0.18 * math.sin(ny * 1.5)
        rz = terrain_height(rc, y) + 0.025
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
        rc = 2.45 + 0.18 * math.sin((ym / 4.0) * 1.5)
        rz = terrain_height(rc, ym) + 0.032
        # Dashed center line
        if j % 2 == 0:
            add_box(bm_m, (rc, ym, rz), (0.032, (depth / steps) * 0.65, 0.008))
        # Outer guardrail posts & rail
        gx = rc + half_w - 0.04
        add_box(bm_m, (gx, ym, rz + 0.065), (0.022, (depth / steps) * 1.04, 0.035))
        if j % 3 == 0:
            add_cylinder(bm_m, (gx + 0.015, ym, rz + 0.04), 0.016, 0.016, 0.11, segs=6)
        # Roadway LED streetlamp poles every 10 steps
        if j in (6, 18, 30, 42):
            lx = rc + half_w + 0.06
            add_cylinder(bm_m, (lx, ym, rz + 0.28), 0.016, 0.012, 0.56, segs=8)
            add_box(bm_m, (lx - 0.08, ym, rz + 0.55), (0.18, 0.04, 0.025))

    bm_m.normal_update()
    bm_m.to_mesh(mesh_markings)
    bm_m.free()
    mark_obj = bpy.data.objects.new("RoadMarkings", mesh_markings)
    mark_obj.data.materials.append(mats["steel_housing"])
    link_obj(mark_obj, road_obj)

    # Uphill Tie-Back Anchored Retaining Wall with Buttress Pilasters & Rock Anchor Plates
    mesh_wall = bpy.data.meshes.new("RetainingWallMesh")
    bm_w = bmesh.new()
    for j in range(steps - 1):
        y0 = -depth / 2 + (j / (steps - 1)) * depth
        y1 = -depth / 2 + ((j + 1) / (steps - 1)) * depth
        rc0 = 2.45 + 0.18 * math.sin((y0 / 4.0) * 1.5) - half_w - 0.04
        rc1 = 2.45 + 0.18 * math.sin((y1 / 4.0) * 1.5) - half_w - 0.04
        z0 = terrain_height(rc0, y0)
        z1 = terrain_height(rc1, y1)
        h = 0.34
        v1 = bm_w.verts.new((rc0, y0, z0))
        v2 = bm_w.verts.new((rc1, y1, z1))
        v3 = bm_w.verts.new((rc1 - 0.08, y1, z1 + h))
        v4 = bm_w.verts.new((rc0 - 0.08, y0, z0 + h))
        bm_w.faces.new((v1, v2, v3, v4))
        # Concrete buttress pilaster + tie-back anchor head every 4 segments
        if j % 4 == 0:
            ym = 0.5 * (y0 + y1)
            rcm = 0.5 * (rc0 + rc1)
            zm = 0.5 * (z0 + z1)
            add_box(bm_w, (rcm - 0.03, ym, zm + h * 0.5), (0.10, 0.06, h), rot_euler=(0, -0.22, 0))
            add_cylinder(bm_w, (rcm + 0.01, ym, zm + h * 0.55), 0.035, 0.025, 0.04, segs=8, rot_euler=(0, math.pi / 2, 0))

    bm_w.normal_update()
    bm_w.to_mesh(mesh_wall)
    bm_w.free()

    wall_obj = bpy.data.objects.new("RetainingWall", mesh_wall)
    wall_obj.data.materials.append(mats["concrete"])
    link_obj(wall_obj, root)


def build_gnss_station(name: str, x: float, y: float, root, mats, is_base=False):
    """Build a detailed GNSS RTK field station with fenced concrete pad, lattice truss mast, solar array, NEMA cabinet, and choke-ring radome."""
    z = terrain_height(x, y)
    station_grp = bpy.data.objects.new(name, None)
    station_grp.empty_display_type = "PLAIN_AXES"
    station_grp.location = (x, y, z)
    link_obj(station_grp, root)

    # 1. Concrete Foundation Pad + Perimeter Safety Fence + Lattice Truss Mast + Telemetry Cabinet
    mesh_body = bpy.data.meshes.new(f"{name}_BodyMesh")
    bm = bmesh.new()
    # Stepped octagonal concrete plinth
    add_cylinder(bm, (0, 0, 0.04), 0.28, 0.25, 0.08, segs=8)
    add_cylinder(bm, (0, 0, 0.14), 0.14, 0.11, 0.14, segs=12)

    # 4 corner safety fence posts & horizontal safety rails around the pad
    fence_r = 0.23
    fence_pts = [(fence_r, fence_r), (-fence_r, fence_r), (-fence_r, -fence_r), (fence_r, -fence_r)]
    for fx, fy in fence_pts:
        add_cylinder(bm, (fx, fy, 0.16), 0.012, 0.012, 0.22, segs=6)
    for k in range(4):
        p0 = fence_pts[k]
        p1 = fence_pts[(k + 1) % 4]
        add_strut(bm, (p0[0], p0[1], 0.24), (p1[0], p1[1], 0.24), radius=0.008, segs=6)
        add_strut(bm, (p0[0], p0[1], 0.16), (p1[0], p1[1], 0.16), radius=0.007, segs=6)

    # Steel 3-leg lattice truss mast + central riser
    mast_h = 0.90 if not is_base else 1.12
    add_cylinder(bm, (0, 0, 0.20 + mast_h * 0.5), 0.024, 0.020, mast_h, segs=10)
    for leg_i in range(3):
        ang = leg_i * (math.pi * 2.0 / 3.0)
        lx, ly = math.cos(ang) * 0.055, math.sin(ang) * 0.055
        add_strut(bm, (lx, ly, 0.18), (lx * 0.45, ly * 0.45, 0.20 + mast_h), radius=0.009, segs=6)
        # Guy wires anchored to pad corners
        gx, gy = math.cos(ang + 0.5) * 0.22, math.sin(ang + 0.5) * 0.22
        add_strut(bm, (gx, gy, 0.08), (0, 0, 0.20 + mast_h * 0.72), radius=0.0045, segs=4)

    # NEMA Weatherproof Telemetry Enclosure + Heat Sink Fins + Dual RTU Whip Antennas
    add_box(bm, (0.095, 0.0, 0.52), (0.13, 0.17, 0.22))
    add_box(bm, (0.162, 0.0, 0.52), (0.015, 0.14, 0.18))
    add_cylinder(bm, (0.095, 0.06, 0.72), 0.006, 0.003, 0.22, segs=6)
    add_cylinder(bm, (0.095, -0.06, 0.70), 0.006, 0.003, 0.18, segs=6)

    # Cross-arm with meteorological mini-sensors
    top_z = 0.20 + mast_h
    add_box(bm, (0.0, 0.0, top_z - 0.12), (0.03, 0.34, 0.022))
    add_cylinder(bm, (0.0, 0.16, top_z - 0.08), 0.028, 0.028, 0.06, segs=10)
    add_cylinder(bm, (0.0, -0.16, top_z - 0.08), 0.022, 0.008, 0.07, segs=10)

    bm.normal_update()
    bm.to_mesh(mesh_body)
    bm.free()

    body_obj = bpy.data.objects.new(f"{name}_Body", mesh_body)
    body_obj.data.materials.append(mats["steel_housing"])
    link_obj(body_obj, station_grp)

    # 2. Framed Solar Panel Array with Mounting Strut
    mesh_solar = bpy.data.meshes.new(f"{name}_SolarMesh")
    bm_s = bmesh.new()
    add_box(bm_s, (-0.11, -0.03, 0.66), (0.32, 0.25, 0.022), rot_euler=(0.35, -0.42, 0.0))
    add_box(bm_s, (-0.11, -0.03, 0.672), (0.29, 0.22, 0.012), rot_euler=(0.35, -0.42, 0.0))
    bm_s.normal_update()
    bm_s.to_mesh(mesh_solar)
    bm_s.free()

    solar_obj = bpy.data.objects.new(f"{name}_Solar", mesh_solar)
    solar_obj.data.materials.append(mats["solar_panel"])
    link_obj(solar_obj, station_grp)

    # 3. High-Precision Choke-Ring GNSS Geodetic Radome Antenna
    mesh_dome = bpy.data.meshes.new(f"{name}_DomeMesh")
    bm_d = bmesh.new()
    add_cylinder(bm_d, (0, 0, top_z + 0.015), 0.15, 0.15, 0.025, segs=24)
    add_cylinder(bm_d, (0, 0, top_z + 0.042), 0.165, 0.155, 0.032, segs=24)
    add_cylinder(bm_d, (0, 0, top_z + 0.088), 0.135, 0.085, 0.065, segs=24)
    add_cylinder(bm_d, (0, 0, top_z + 0.132), 0.085, 0.025, 0.032, segs=24)
    bm_d.normal_update()
    bm_d.to_mesh(mesh_dome)
    bm_d.free()

    dome_obj = bpy.data.objects.new(f"{name}_Dome", mesh_dome)
    dome_obj.data.materials.append(mats["gnss_base_dome"] if is_base else mats["gnss_rover_dome"])
    link_obj(dome_obj, station_grp)

    # 4. Concentric Dual Ground Telemetry Rings
    mesh_ring = bpy.data.meshes.new(f"{name}_RingMesh")
    bm_r = bmesh.new()
    for r_rad, thick in ((0.38, 1.12), (0.52, 1.06)):
        c_geom = bmesh.ops.create_circle(bm_r, cap_ends=False, radius=r_rad, segments=32)
        c_verts = c_geom["verts"]
        c_edges = [e for e in bm_r.edges if e.verts[0] in c_verts and e.verts[1] in c_verts]
        ext = bmesh.ops.extrude_edge_only(bm_r, edges=c_edges)
        ext_verts = [ele for ele in ext["geom"] if isinstance(ele, bmesh.types.BMVert)]
        for v in ext_verts:
            v.co.x *= thick
            v.co.y *= thick
    for v in bm_r.verts:
        v.co.z += 0.028
    bm_r.normal_update()
    bm_r.to_mesh(mesh_ring)
    bm_r.free()

    ring_obj = bpy.data.objects.new(f"{name}_Ring", mesh_ring)
    ring_obj.data.materials.append(mats["ring_lime"] if is_base else mats["ring_teal"])
    link_obj(ring_obj, station_grp)

    return station_grp


def build_imu_borehole(root, mats):
    """Build deep borehole inclinometer casing + protective bollards + 5 subsurface MEMS IMU nodes + sleek displacement vector."""
    x, y = -1.08, -0.52
    z = terrain_height(x, y)
    grp = bpy.data.objects.new("IMU_Borehole_Assembly", None)
    grp.location = (x, y, z)
    link_obj(grp, root)

    mesh_casing = bpy.data.meshes.new("IMUCasingMesh")
    bm = bmesh.new()
    # Concrete collar + wellhead cap + 4 protective bollard posts + deep borehole guide pipe
    add_cylinder(bm, (0, 0, 0.03), 0.22, 0.20, 0.06, segs=12)
    add_cylinder(bm, (0, 0, -0.95), 0.046, 0.046, 2.18, segs=14)
    add_cylinder(bm, (0, 0, 0.16), 0.095, 0.085, 0.20, segs=14)
    add_box(bm, (-0.14, 0.0, 0.18), (0.12, 0.14, 0.18))
    for bx, by in ((0.16, 0.16), (-0.16, 0.16), (-0.16, -0.16), (0.16, -0.16)):
        add_cylinder(bm, (bx, by, 0.12), 0.016, 0.016, 0.22, segs=8)
    bm.normal_update()
    bm.to_mesh(mesh_casing)
    bm.free()

    casing_obj = bpy.data.objects.new("IMU_Casing", mesh_casing)
    casing_obj.data.materials.append(mats["imu_amber"])
    link_obj(casing_obj, grp)

    mesh_nodes = bpy.data.meshes.new("IMUNodesMesh")
    bm_n = bmesh.new()
    for depth_z in (-0.22, -0.52, -0.82, -1.15, -1.48):
        add_cylinder(bm_n, (0, 0, depth_z), 0.082, 0.082, 0.13, segs=16)
        add_cylinder(bm_n, (0, 0, depth_z), 0.105, 0.105, 0.035, segs=16)
    bm_n.normal_update()
    bm_n.to_mesh(mesh_nodes)
    bm_n.free()

    nodes_obj = bpy.data.objects.new("IMU_Subsurface_Nodes", mesh_nodes)
    nodes_obj.data.materials.append(mats["imu_glow"])
    link_obj(nodes_obj, grp)

    # Sleek Multi-Chevron 3D Displacement Vector Arrow pointing down-slope (+X)
    mesh_arrow = bpy.data.meshes.new("DisplacementArrowMesh")
    bm_a = bmesh.new()
    rot_y = Euler((0.0, math.pi / 2 + 0.24, 0.0), "XYZ").to_matrix().to_4x4()
    bmesh.ops.create_cone(
        bm_a, cap_ends=True, segments=14, radius1=0.022, radius2=0.022, depth=0.64,
        matrix=Matrix.Translation((0.36, 0.0, 0.28)) @ rot_y
    )
    for ch_idx, offset_x in enumerate((0.58, 0.72, 0.86)):
        rad = 0.068 + ch_idx * 0.012
        bmesh.ops.create_cone(
            bm_a, cap_ends=True, segments=14, radius1=rad, radius2=0.004, depth=0.16,
            matrix=Matrix.Translation((offset_x, 0.0, 0.23 - ch_idx * 0.035)) @ rot_y
        )
    bm_a.normal_update()
    bm_a.to_mesh(mesh_arrow)
    bm_a.free()

    arrow_obj = bpy.data.objects.new("DisplacementVectorArrow", mesh_arrow)
    arrow_obj.data.materials.append(mats["imu_glow"])
    link_obj(arrow_obj, grp)
    return grp


def build_rain_and_piezometer(root, mats):
    """Build Automatic Weather & Rain Gauge Station (with anemometer, wind vane, radiation shield) and Cutaway Piezometer Well."""
    rx, ry = -2.45, -1.55
    rz = terrain_height(rx, ry)
    rain_grp = bpy.data.objects.new("Rain_Gauge_Station", None)
    rain_grp.location = (rx, ry, rz)
    link_obj(rain_grp, root)

    mesh_rg_stand = bpy.data.meshes.new("RainGaugeStandMesh")
    bm_s = bmesh.new()
    add_cylinder(bm_s, (0, 0, 0.04), 0.22, 0.19, 0.08, segs=12)
    add_cylinder(bm_s, (0, 0, 0.36), 0.022, 0.018, 0.64, segs=10)
    # Tripod legs
    for k in range(3):
        ang = k * (math.pi * 2.0 / 3.0)
        add_strut(bm_s, (math.cos(ang) * 0.16, math.sin(ang) * 0.16, 0.06), (0, 0, 0.36), radius=0.010, segs=6)
    # Crossbar for anemometer & wind vane above collector
    add_box(bm_s, (0, 0, 0.66), (0.36, 0.022, 0.022))
    for cup_ang in (0, 2.09, 4.18):
        cx = -0.17 + math.cos(cup_ang) * 0.055
        cy = math.sin(cup_ang) * 0.055
        add_cylinder(bm_s, (cx, cy, 0.72), 0.018, 0.006, 0.025, segs=8)
    # Multi-plate radiation shield on right arm
    for sh_i in range(4):
        add_cylinder(bm_s, (0.16, 0, 0.56 + sh_i * 0.024), 0.036, 0.034, 0.014, segs=12)

    bm_s.normal_update()
    bm_s.to_mesh(mesh_rg_stand)
    bm_s.free()

    stand_obj = bpy.data.objects.new("RainGaugeStand", mesh_rg_stand)
    stand_obj.data.materials.append(mats["steel_housing"])
    link_obj(stand_obj, rain_grp)

    mesh_rg = bpy.data.meshes.new("RainGaugeMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, 0.46), 0.11, 0.11, 0.22, segs=20)
    add_cylinder(bm, (0, 0, 0.60), 0.11, 0.145, 0.07, segs=20)
    add_cylinder(bm, (0, 0, 0.645), 0.148, 0.148, 0.018, segs=20)
    bm.normal_update()
    bm.to_mesh(mesh_rg)
    bm.free()

    rg_obj = bpy.data.objects.new("RainGaugeCollector", mesh_rg)
    rg_obj.data.materials.append(mats["rain_cyan"])
    link_obj(rg_obj, rain_grp)

    # 2. Piezometer Groundwater Monitoring Well on the front cutaway edge
    px, py = -1.75, -3.72
    pz = terrain_height(px, py)
    piezo_grp = bpy.data.objects.new("Piezometer_Well_Assembly", None)
    piezo_grp.location = (px, py, pz)
    link_obj(piezo_grp, root)

    mesh_well = bpy.data.meshes.new("PiezometerCasingMesh")
    bm_w = bmesh.new()
    add_cylinder(bm_w, (0, 0, 0.04), 0.18, 0.16, 0.08, segs=14)
    add_cylinder(bm_w, (0, 0, 0.18), 0.11, 0.095, 0.24, segs=16)
    add_box(bm_w, (0.11, 0, 0.22), (0.09, 0.11, 0.14))
    add_cylinder(bm_w, (0, -0.18, -0.82), 0.068, 0.068, 1.88, segs=16)
    bm_w.normal_update()
    bm_w.to_mesh(mesh_well)
    bm_w.free()

    well_obj = bpy.data.objects.new("PiezometerCasing", mesh_well)
    well_obj.data.materials.append(mats["steel_housing"])
    link_obj(well_obj, piezo_grp)

    mesh_col = bpy.data.meshes.new("PiezometerWaterMesh")
    bm_c = bmesh.new()
    add_cylinder(bm_c, (0, -0.22, -1.02), 0.088, 0.088, 1.15, segs=18)
    for ring_z in (-1.35, -1.05, -0.75, -0.45):
        add_cylinder(bm_c, (0, -0.22, ring_z), 0.105, 0.105, 0.028, segs=18)
    bm_c.normal_update()
    bm_c.to_mesh(mesh_col)
    bm_c.free()

    col_obj = bpy.data.objects.new("PiezometerWaterColumn", mesh_col)
    col_obj.data.materials.append(mats["water_glow"])
    link_obj(col_obj, piezo_grp)


def build_operations_hub(root, mats):
    """Build the Regional Operations Command Compound with multi-wing facility, drone helipad, comms tower, and highway gantry."""
    ox, oy = 4.02, -0.80
    oz = terrain_height(ox, oy)
    ops_grp = bpy.data.objects.new("Operations_Command_Node", None)
    ops_grp.location = (ox, oy, oz)
    link_obj(ops_grp, root)

    mesh_base = bpy.data.meshes.new("OpsBaseMesh")
    bm = bmesh.new()
    # Multi-tiered fortified platform & helipad deck
    add_cylinder(bm, (0, 0, 0.06), 0.62, 0.56, 0.14, segs=12)
    add_cylinder(bm, (0, 0, 0.19), 0.46, 0.42, 0.14, segs=12)
    # Main architectural command building + side telemetry wing
    add_box(bm, (-0.06, 0.04, 0.34), (0.44, 0.36, 0.22))
    add_box(bm, (0.18, -0.14, 0.30), (0.28, 0.26, 0.16))
    # Lattice communications tower + microwave dish drums
    add_cylinder(bm, (-0.08, 0.06, 0.82), 0.042, 0.022, 0.88, segs=10)
    for t_leg in range(4):
        ang = t_leg * (math.pi / 2.0) + 0.78
        add_strut(
            bm,
            (-0.08 + math.cos(ang) * 0.11, 0.06 + math.sin(ang) * 0.11, 0.42),
            (-0.08 + math.cos(ang) * 0.03, 0.06 + math.sin(ang) * 0.03, 1.22),
            radius=0.010,
            segs=6,
        )
    add_cylinder(bm, (-0.02, 0.06, 0.88), 0.065, 0.055, 0.04, segs=12, rot_euler=(0, math.pi / 2, 0))
    add_cylinder(bm, (-0.14, 0.06, 1.04), 0.055, 0.045, 0.04, segs=12, rot_euler=(0, -math.pi / 2, 0.3))
    bm.normal_update()
    bm.to_mesh(mesh_base)
    bm.free()

    base_obj = bpy.data.objects.new("OpsCommandStructure", mesh_base)
    base_obj.data.materials.append(mats["steel_housing"])
    link_obj(base_obj, ops_grp)

    # Glowing Phased-Array Geodesic Radar Core + Control Room Panoramic Window Band + Helipad Ring
    mesh_beacon = bpy.data.meshes.new("OpsBeaconMesh")
    bm_b = bmesh.new()
    bmesh.ops.create_icosphere(bm_b, subdivisions=2, radius=0.18, matrix=Matrix.Translation((-0.08, 0.06, 1.32)))
    add_cylinder(bm_b, (-0.08, 0.06, 1.32), 0.26, 0.26, 0.022, segs=24, rot_euler=(0.35, -0.25, 0.0))
    add_box(bm_b, (-0.06, 0.04, 0.38), (0.46, 0.38, 0.055))
    add_cylinder(bm_b, (0.18, -0.14, 0.385), 0.10, 0.10, 0.012, segs=16)
    bm_b.normal_update()
    bm_b.to_mesh(mesh_beacon)
    bm_b.free()

    beacon_obj = bpy.data.objects.new("OpsBeaconCore", mesh_beacon)
    beacon_obj.data.materials.append(mats["gnss_base_dome"])
    link_obj(beacon_obj, ops_grp)

    # Highway Early Warning Gantry (Steel Truss Columns + Dark Sign Housing + Glowing LED Matrix & Beacons)
    gx_y = -1.35
    gx = 2.45 + 0.18 * math.sin((gx_y / 4.0) * 1.5)
    gz = terrain_height(gx, gx_y)

    mesh_gate_frame = bpy.data.meshes.new("HighwayGateFrameMesh")
    bm_gf = bmesh.new()
    for side_x in (-0.52, 0.52):
        add_cylinder(bm_gf, (side_x, 0, 0.04), 0.055, 0.045, 0.08, segs=8)
        add_cylinder(bm_gf, (side_x, 0, 0.34), 0.024, 0.020, 0.60, segs=10)
        add_cylinder(bm_gf, (side_x, -0.055, 0.34), 0.018, 0.016, 0.60, segs=8)
        for z_brace in (0.18, 0.34, 0.50):
            add_strut(bm_gf, (side_x, 0, z_brace), (side_x, -0.055, z_brace + 0.08), radius=0.008, segs=6)
    # Overhead steel truss chords
    add_box(bm_gf, (0, 0.02, 0.60), (1.08, 0.035, 0.035))
    add_box(bm_gf, (0, 0.02, 0.52), (1.08, 0.035, 0.035))
    # Boom barrier pivot pedestal on right lane
    add_box(bm_gf, (0.46, -0.22, 0.10), (0.07, 0.07, 0.20))
    bm_gf.normal_update()
    bm_gf.to_mesh(mesh_gate_frame)
    bm_gf.free()

    gate_frame_obj = bpy.data.objects.new("HighwayGateFrame", mesh_gate_frame)
    gate_frame_obj.data.materials.append(mats["steel_housing"])
    gate_frame_obj.location = (gx, gx_y, gz)
    link_obj(gate_frame_obj, root)

    # Glowing LED Matrix Display + Flashing Roof Beacons + Boom Barrier Arm
    mesh_gate = bpy.data.meshes.new("HighwayWarningGateMesh")
    bm_g = bmesh.new()
    add_box(bm_g, (0, -0.03, 0.56), (0.82, 0.04, 0.14))
    add_cylinder(bm_g, (-0.34, -0.03, 0.66), 0.028, 0.028, 0.04, segs=10)
    add_cylinder(bm_g, (0.34, -0.03, 0.66), 0.028, 0.028, 0.04, segs=10)
    add_box(bm_g, (0.16, -0.22, 0.18), (0.56, 0.018, 0.022), rot_euler=(0, -0.08, 0))
    bm_g.normal_update()
    bm_g.to_mesh(mesh_gate)
    bm_g.free()

    gate_obj = bpy.data.objects.new("HighwayWarningGate", mesh_gate)
    gate_obj.data.materials.append(mats["imu_glow"])
    gate_obj.location = (gx, gx_y, gz)
    link_obj(gate_obj, root)
    return ops_grp


def import_web_vehicles(root, mats):
    """Import multi-part 3D vehicles from frontend/assets/blender/models/cars_big_set.glb and place them along the mountain highway."""
    cars_glb = BLENDER_DIR / "models" / "cars_big_set.glb"
    if not cars_glb.exists():
        return

    before_names = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=str(cars_glb))
    imported_names = set(bpy.data.objects.keys()) - before_names

    # Tune the imported palette material so car paint, glass, rims & lights look crisp in EEVEE & Three.js
    for mat in bpy.data.materials:
        if "lospec" in mat.name.lower() or "material.001" in mat.name.lower():
            if mat.node_tree:
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    bsdf.inputs["Roughness"].default_value = 0.30
                    bsdf.inputs["Metallic"].default_value = 0.18

    def extract_vehicle_mesh(car_name: str, target_width=0.23):
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
        bpy.context.view_layer.objects.active = dup_parts[0]
        if len(dup_parts) > 1:
            bpy.ops.object.join()
        joined = bpy.context.view_layer.objects.active
        joined.parent = None
        joined.location = (0, 0, 0)
        joined.rotation_euler = (0, 0, 0)
        joined.scale = (1, 1, 1)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Normalize origin to bottom-center of wheels and scale to highway lane width
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

    # Placement list: (instance_name, source_car_name, road_y, lane_offset_x, flip_dir, target_w)
    vehicle_placements = [
        ("Vehicle_01_PoliceCruiser", "car_police", -1.76, 0.16, True, 0.25),
        ("Vehicle_02_RescueBoxTruck", "car_removals", -2.85, 0.17, True, 0.27),
        ("Vehicle_03_CivilianCharger", "car_charger", -2.26, -0.16, False, 0.24),
        ("Vehicle_04_GeoFieldPickup", "car_pickup", -0.58, 0.17, True, 0.25),
        ("Vehicle_05_TelemetryMinivan", "car_minivan", 1.28, 0.17, True, 0.25),
        ("Vehicle_06_EngineeringVan", "car_breadvan", 2.48, -0.16, False, 0.25),
        ("Vehicle_07_SedanDaily", "car_daily", -3.48, -0.16, False, 0.24),
        ("Vehicle_08_SportCoupe", "car_beemer", 3.22, 0.17, True, 0.24),
        ("Vehicle_09_AlpineTourer", "car_sports_skiis", 0.32, -0.16, False, 0.24),
        ("Vehicle_10_SurveyStriped", "car_sports_striped", -1.05, -0.16, False, 0.24),
    ]

    fleet_grp = bpy.data.objects.new("Highway_Vehicle_Fleet", None)
    link_obj(fleet_grp, root)

    for v_name, src_name, ry, lane_x, north, tw in vehicle_placements:
        v_obj = extract_vehicle_mesh(src_name, target_width=tw)
        if not v_obj:
            continue
        v_obj.name = v_name
        rc = 2.45 + 0.18 * math.sin((ry / 4.0) * 1.5)
        vx = rc + lane_x
        vz = terrain_height(rc, ry) + 0.028
        dx_dy = 0.18 * (1.5 / 4.0) * math.cos((ry / 4.0) * 1.5)
        yaw = -math.atan2(dx_dy, 1.0) + (math.pi if north else 0.0)
        if v_name == "Vehicle_01_PoliceCruiser":
            yaw += 0.22
        v_obj.location = (vx, ry, vz)
        v_obj.rotation_euler = (0.0, 0.0, yaw)
        if v_obj.name not in bpy.context.collection.objects:
            link_obj(v_obj, fleet_grp)
        else:
            v_obj.parent = fleet_grp

    # Also place a 4x4 utility mini-pickup parked at the Operations Command Compound apron
    ops_truck = extract_vehicle_mesh("car_mini-pickup", target_width=0.25)
    if ops_truck:
        ops_truck.name = "Vehicle_11_OpsUtilityPickup"
        ox, oy = 3.42, -1.22
        oz = terrain_height(ox, oy) + 0.015
        ops_truck.location = (ox, oy, oz)
        ops_truck.rotation_euler = (0.0, 0.0, 0.65)
        if ops_truck.name not in bpy.context.collection.objects:
            link_obj(ops_truck, fleet_grp)
        else:
            ops_truck.parent = fleet_grp

    # Remove original imported car scene objects
    for name in list(imported_names):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)


def import_nasa_satellites(sat_grp, mats):
    """Import real NASA 3D spacecraft models (EO-1 & DSCOVR) and deploy a 6-satellite orbital constellation."""
    templates = {}
    sat_files = {
        "eo1": ("nasa_eo1.glb", 0.08, 1.12),
        "dscovr": ("nasa_dscovr.glb", 0.09, 1.16),
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
            m.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        if len(meshes) > 1:
            bpy.ops.object.join()
        joined = bpy.context.view_layer.objects.active
        joined_name = joined.name
        joined.parent = None
        joined.location = (0, 0, 0)
        joined.rotation_euler = (0, 0, 0)
        joined.scale = (1, 1, 1)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Merge close vertices first so Decimate works across the whole spacecraft cleanly
        bm_clean = bmesh.new()
        bm_clean.from_mesh(joined.data)
        bmesh.ops.remove_doubles(bm_clean, verts=bm_clean.verts, dist=0.02)
        bm_clean.normal_update()
        bm_clean.to_mesh(joined.data)
        bm_clean.free()

        mod = joined.modifiers.new("DecimateSat", "DECIMATE")
        mod.ratio = dec_ratio
        bpy.ops.object.modifier_apply(modifier="DecimateSat")

        # Center and normalize size
        verts = [v.co for v in joined.data.vertices]
        min_v = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
        max_v = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
        center = 0.5 * (min_v + max_v)
        span = max(0.01, max(max_v - min_v))
        scale_f = target_span / span
        for v in joined.data.vertices:
            v.co = (v.co - center) * scale_f
        joined.data.update()

        # Enhance NASA spacecraft materials (gold thermal foil, solar panels, white/silver dish)
        for slot in joined.material_slots:
            m = slot.material
            if not m or not m.node_tree:
                continue
            bsdf = m.node_tree.nodes.get("Principled BSDF")
            if not bsdf:
                continue
            mname = m.name.lower()
            if any(k in mname for k in ("gold", "brass", "foil", "yellow", "layer10", "layer6")):
                bsdf.inputs["Base Color"].default_value = (0.96, 0.74, 0.18, 1.0)
                bsdf.inputs["Metallic"].default_value = 0.85
                bsdf.inputs["Roughness"].default_value = 0.22
                if "Emission Color" in bsdf.inputs:
                    bsdf.inputs["Emission Color"].default_value = (0.96, 0.72, 0.15, 1.0)
                    bsdf.inputs["Emission Strength"].default_value = 0.35
            elif any(k in mname for k in ("solar", "panel", "layer1", "shiny_panel", "tex_01")):
                bsdf.inputs["Base Color"].default_value = (0.06, 0.34, 0.58, 1.0)
                bsdf.inputs["Metallic"].default_value = 0.82
                bsdf.inputs["Roughness"].default_value = 0.16
                if "Emission Color" in bsdf.inputs:
                    bsdf.inputs["Emission Color"].default_value = (0.12, 0.52, 0.82, 1.0)
                    bsdf.inputs["Emission Strength"].default_value = 0.42
            else:
                bsdf.inputs["Base Color"].default_value = (0.84, 0.95, 0.92, 1.0)
                bsdf.inputs["Metallic"].default_value = 0.65
                bsdf.inputs["Roughness"].default_value = 0.24
                if "Emission Color" in bsdf.inputs:
                    bsdf.inputs["Emission Color"].default_value = (0.45, 0.92, 0.82, 1.0)
                    bsdf.inputs["Emission Strength"].default_value = 0.28

        templates[key] = joined
        for name in list(imp_names):
            if name != joined_name and name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)

    # Deploy 6 winged NASA Satellites (DSCOVR & EO-1) in the visible sky band well above the mountain crest
    sat_configs = [
        ("GNSS_Sat_01", "dscovr", (-2.25, 0.15, 0.12), (0.32, 0.22, -0.35), 0.88),
        ("GNSS_Sat_02", "eo1", (-0.75, 0.55, 0.28), (-0.28, 0.18, 0.45), 0.92),
        ("GNSS_Sat_03", "dscovr", (0.85, 0.25, 0.22), (0.30, -0.24, 0.28), 0.90),
        ("GNSS_Sat_04", "eo1", (2.35, -0.15, 0.08), (-0.22, -0.30, -0.42), 0.86),
        ("GNSS_Sat_05", "dscovr", (-1.55, 1.25, 0.34), (0.24, -0.28, 0.62), 0.82),
        ("GNSS_Sat_06", "eo1", (1.60, 0.95, 0.26), (0.35, 0.16, -0.25), 0.84),
    ]

    for s_name, t_key, loc, rot, sc in sat_configs:
        tmpl = templates.get(t_key)
        if not tmpl:
            continue
        sat_obj = bpy.data.objects.new(s_name, tmpl.data.copy())
        sat_obj.location = loc
        sat_obj.rotation_euler = rot
        sat_obj.scale = (sc, sc, sc)
        link_obj(sat_obj, sat_grp)

    for tmpl in list(templates.values()):
        if tmpl.name in bpy.data.objects:
            bpy.data.objects.remove(tmpl, do_unlink=True)


def build_satellites_and_trees(root, mats):
    """Build 6 real NASA satellites, 11 imported 3D highway vehicles, and 50+ multi-tier mountain trees & boulders."""
    sat_grp = bpy.data.objects.new("Satellite_Constellation", None)
    sat_grp.location = (-0.20, 0.25, 1.82)
    link_obj(sat_grp, root)

    import_nasa_satellites(sat_grp, mats)
    import_web_vehicles(root, mats)

    # Rich Multi-Layered Mountain Forest (Tree Trunks + Conifer Tiers + Broadleaf Canopies + Boulders)
    mesh_trees = bpy.data.meshes.new("MountainForestMesh")
    bm_t = bmesh.new()
    tree_col_layer = bm_t.loops.layers.color.new("Col")

    tree_spots = [
        (-4.9, 3.2), (-4.5, 2.7), (-4.1, 2.2), (-4.7, 1.5), (-4.3, 0.9),
        (-4.8, 0.2), (-4.4, -0.5), (-4.6, -1.2), (-3.8, 3.3), (-3.4, 2.8),
        (-2.9, 3.1), (-2.4, 2.6), (-2.1, 3.4), (-1.5, 3.1), (-0.9, 3.3),
        (-0.3, 2.9), (0.4, 3.2), (1.0, 2.8), (1.5, 3.3), (-3.6, 1.8),
        (-3.2, 2.1), (-2.7, 1.9), (-3.8, -0.8), (-3.5, -1.4), (-3.9, -2.5),
        (-3.3, -2.9), (-2.8, -2.7), (-0.6, -2.8), (0.2, -3.1), (0.9, -2.9),
        (1.4, -2.6), (3.4, 2.9), (3.8, 2.5), (4.3, 2.8), (4.7, 2.1),
        (4.5, 1.4), (4.8, 0.7), (3.6, 1.6), (4.6, -1.8), (4.2, -2.4),
        (4.7, -2.8), (3.7, -2.9), (-1.8, 2.1), (-1.2, 2.3), (0.5, 2.1),
        (1.2, 1.8), (-4.9, -2.1), (-4.2, -3.2), (3.5, 0.6), (4.9, -0.4),
    ]

    rng = random.Random(108)
    for idx, (tx, ty) in enumerate(tree_spots):
        tz = terrain_height(tx, ty)
        scale = 0.72 + (idx % 5) * 0.14
        tilt_x = rng.uniform(-0.06, 0.06)
        tilt_y = rng.uniform(-0.06, 0.06)

        # Tree trunk
        v_start = len(bm_t.verts)
        add_cylinder(bm_t, (tx, ty, tz + 0.08 * scale), 0.028 * scale, 0.018 * scale, 0.18 * scale, segs=6)
        trunk_verts = set(bm_t.verts[v_start:])

        # 3-tier stylized pine cones OR organic icosphere broadleaf crown
        v_fol_start = len(bm_t.verts)
        if idx % 4 != 0:
            add_cylinder(bm_t, (tx, ty, tz + 0.22 * scale), 0.16 * scale, 0.02 * scale, 0.24 * scale, segs=7, rot_euler=(tilt_x, tilt_y, 0.2))
            add_cylinder(bm_t, (tx, ty, tz + 0.36 * scale), 0.125 * scale, 0.015 * scale, 0.22 * scale, segs=7, rot_euler=(tilt_x, tilt_y, 0.7))
            add_cylinder(bm_t, (tx, ty, tz + 0.49 * scale), 0.085 * scale, 0.006 * scale, 0.18 * scale, segs=7, rot_euler=(tilt_x, tilt_y, 1.1))
        else:
            bmesh.ops.create_icosphere(
                bm_t, subdivisions=1, radius=0.14 * scale,
                matrix=Matrix.Translation((tx, ty, tz + 0.26 * scale)) @ Matrix.Diagonal((1.1, 1.0, 1.25, 1.0)),
            )
            bmesh.ops.create_icosphere(
                bm_t, subdivisions=1, radius=0.10 * scale,
                matrix=Matrix.Translation((tx + 0.05 * scale, ty - 0.04 * scale, tz + 0.34 * scale)),
            )
        fol_verts = set(bm_t.verts[v_fol_start:])

        # Colorize trunk vs varied foliage greens
        shade = rng.uniform(0.0, 1.0)
        c_fol = lerp_color((0.06, 0.38, 0.30, 1.0), (0.18, 0.58, 0.42, 1.0), shade)
        c_trunk = (0.24, 0.16, 0.11, 1.0)
        for f in bm_t.faces:
            if any(v in trunk_verts for v in f.verts):
                for loop in f.loops:
                    loop[tree_col_layer] = c_trunk
            elif any(v in fol_verts for v in f.verts):
                for loop in f.loops:
                    loop[tree_col_layer] = c_fol

    # Add scattered alpine boulders & landslide toe rockfall debris
    boulder_spots = [
        (-2.6, 0.2, 1.3), (-2.3, -0.9, 1.1), (0.8, -0.8, 1.2), (1.1, -0.2, 1.4),
        (1.3, 0.1, 0.9), (1.5, -0.5, 1.1), (-3.5, 0.4, 1.5), (-1.9, 1.4, 1.2),
        (0.2, 1.5, 1.1), (1.6, 1.2, 1.3), (3.3, -1.6, 1.4), (-0.4, -1.9, 1.0),
    ]
    for bx, by, bscale in boulder_spots:
        bz = terrain_height(bx, by)
        v_b_start = len(bm_t.verts)
        bmesh.ops.create_icosphere(
            bm_t,
            subdivisions=1,
            radius=0.095 * bscale,
            matrix=Matrix.Translation((bx, by, bz + 0.03))
            @ Euler((bx, by, 0.5), "XYZ").to_matrix().to_4x4()
            @ Matrix.Diagonal((1.35, 0.95, 0.72, 1.0)),
        )
        b_verts = set(bm_t.verts[v_b_start:])
        for f in bm_t.faces:
            if any(v in b_verts for v in f.verts):
                for loop in f.loops:
                    loop[tree_col_layer] = (0.32, 0.38, 0.38, 1.0)

    bm_t.normal_update()
    bm_t.to_mesh(mesh_trees)
    bm_t.free()

    trees_obj = bpy.data.objects.new("MountainForest", mesh_trees)
    trees_obj.data.materials.append(mats["forest_canopy"])
    link_obj(trees_obj, root)


def setup_lighting_and_render_previews():
    """Configure Blender EEVEE lighting & camera to render studio previews."""
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
        bg.inputs[1].default_value = 1.15

    key_data = bpy.data.lights.new(name="KeyLight", type="SUN")
    key_data.energy = 3.8
    key_data.color = (0.92, 1.0, 0.96)
    key_obj = bpy.data.objects.new(name="KeyLight", object_data=key_data)
    key_obj.rotation_euler = (0.65, 0.35, -0.55)
    link_obj(key_obj)

    rim_data = bpy.data.lights.new(name="RimLight", type="AREA")
    rim_data.energy = 210.0
    rim_data.size = 6.5
    rim_data.color = (0.35, 0.92, 0.83)
    rim_obj = bpy.data.objects.new(name="RimLight", object_data=rim_data)
    rim_obj.location = (-5.5, 4.5, 5.0)
    rim_obj.rotation_euler = (-0.75, -0.55, 0.4)
    link_obj(rim_obj)

    fill_data = bpy.data.lights.new(name="SlipFillLight", type="POINT")
    fill_data.energy = 115.0
    fill_data.color = (1.0, 0.68, 0.22)
    fill_obj = bpy.data.objects.new(name="SlipFillLight", object_data=fill_data)
    fill_obj.location = (-0.9, -2.5, 2.2)
    link_obj(fill_obj)

    cam_data = bpy.data.cameras.new(name="RenderCam")
    cam_data.lens = 38.0
    cam_obj = bpy.data.objects.new(name="RenderCam", object_data=cam_data)
    scene.camera = cam_obj
    link_obj(cam_obj)

    def look_at(cam, pos, target):
        cam.location = Vector(pos)
        direction = Vector(target) - Vector(pos)
        rot_quat = direction.to_track_quat("-Z", "Y")
        cam.rotation_euler = rot_quat.to_euler()

    look_at(cam_obj, (-2.4, -8.4, 4.3), (-0.3, -0.2, 0.05))
    hero_png = BLENDER_DIR / "hero_preview.png"
    scene.render.filepath = str(hero_png)
    bpy.ops.render.render(write_still=True)

    look_at(cam_obj, (1.2, -9.2, 4.8), (0.0, 0.0, -0.15))
    story_png = BLENDER_DIR / "story_preview.png"
    scene.render.filepath = str(story_png)
    bpy.ops.render.render(write_still=True)

    for obj in (key_obj, rim_obj, fill_obj, cam_obj):
        bpy.data.objects.remove(obj, do_unlink=True)


def main():
    BLENDER_DIR.mkdir(parents=True, exist_ok=True)
    clear_scene()

    mats = {
        "terrain_surface": make_material(
            "TerrainSurfaceMat",
            base_color=(0.07, 0.38, 0.33, 1.0),
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
            base_color=(0.14, 0.24, 0.22, 1.0),
            metallic=0.05,
            roughness=0.78,
        ),
        "bedrock_strata": make_material(
            "BedrockStrataMat",
            base_color=(0.04, 0.12, 0.14, 1.0),
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
            base_color=(0.14, 0.46, 0.38, 1.0),
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
            base_color=(0.06, 0.13, 0.15, 1.0),
            metallic=0.18,
            roughness=0.72,
        ),
        "concrete": make_material(
            "ConcreteWallMat",
            base_color=(0.48, 0.64, 0.62, 1.0),
            metallic=0.12,
            roughness=0.58,
        ),
        "steel_housing": make_material(
            "SteelHousingMat",
            base_color=(0.78, 0.92, 0.90, 1.0),
            metallic=0.68,
            roughness=0.26,
        ),
        "solar_panel": make_material(
            "SolarPanelMat",
            base_color=(0.04, 0.24, 0.38, 1.0),
            metallic=0.78,
            roughness=0.16,
            emission_color=(0.08, 0.48, 0.68),
            emission_strength=0.38,
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
        "forest_canopy": make_material(
            "ForestCanopyMat",
            base_color=(0.10, 0.48, 0.38, 1.0),
            roughness=0.68,
            use_vertex_color=True,
        ),
    }

    root = bpy.data.objects.new("LandslideDigitalTwin", None)
    link_obj(root)

    build_geological_block(root, mats)
    build_mountain_road_and_wall(root, mats)

    build_gnss_station("GNSS_Station_Crown", -3.15, 0.85, root, mats, is_base=False)
    build_gnss_station("GNSS_Station_Mid", -0.78, -0.35, root, mats, is_base=False)
    build_gnss_station("GNSS_Station_Toe", 1.25, 0.65, root, mats, is_base=False)
    build_gnss_station("GNSS_Base_CORS", -4.15, -1.95, root, mats, is_base=True)

    build_imu_borehole(root, mats)
    build_rain_and_piezometer(root, mats)
    build_operations_hub(root, mats)
    build_satellites_and_trees(root, mats)

    blend_path = BLENDER_DIR / "landslide_twin.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    setup_lighting_and_render_previews()

    glb_path = BLENDER_DIR / "landslide_twin.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        export_materials="EXPORT",
    )

    glb_bytes = glb_path.read_bytes()
    glb_b64 = base64.b64encode(glb_bytes).decode("ascii")

    def to_three(x, y, z=None):
        if z is None:
            z = terrain_height(x, y)
        return [round(x, 3), round(z, 3), round(-y, 3)]

    anchors = {
        "gnss_crown": to_three(-3.15, 0.85, terrain_height(-3.15, 0.85) + 1.32),
        "gnss_mid": to_three(-0.78, -0.35, terrain_height(-0.78, -0.35) + 1.32),
        "gnss_toe": to_three(1.25, 0.65, terrain_height(1.25, 0.65) + 1.32),
        "gnss_base": to_three(-4.15, -1.95, terrain_height(-4.15, -1.95) + 1.50),
        "imu_borehole": to_three(-1.08, -0.52, terrain_height(-1.08, -0.52) + 0.48),
        "rain_gauge": to_three(-2.45, -1.55, terrain_height(-2.45, -1.55) + 0.85),
        "piezometer": to_three(-1.75, -3.72, terrain_height(-1.75, -3.72) + 0.42),
        "ops_hub": to_three(4.02, -0.80, terrain_height(4.02, -0.80) + 1.42),
        "highway_gate": to_three(2.42, -1.35, terrain_height(2.42, -1.35) + 0.62),
    }

    js_content = f"""// Auto-generated by scripts/generate_blender_landing.py using Blender {bpy.app.version_string}
export const BLENDER_META = {json.dumps({"blenderVersion": bpy.app.version_string, "glbBytes": len(glb_bytes), "anchors": anchors}, indent=2)};

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
