"""
Generate 3D Geotechnical Landslide Monitoring Digital Twin assets using Blender 5.2 LTS.

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
):
    mat = bpy.data.materials.new(name=name)
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = base_color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
        if emission_color and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (*emission_color[:3], 1.0)
            bsdf.inputs["Emission Strength"].default_value = emission_strength
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

    # Multi-fractal geological ridge detail
    n1 = noise.noise(Vector((x * 0.42 + 3.1, y * 0.42 + 1.7, 0.5)))
    n2 = noise.noise(Vector((x * 0.92 - 2.4, y * 0.92 + 4.2, 1.3))) * 0.32
    road_damp = min(1.0, max(0.06, (dist_road - 0.36) / 0.55))
    detail = (n1 * 0.46 + n2) * road_damp

    raw_h = slope + detail
    terrace = math.sin(raw_h * 5.0) * 0.04 * road_damp
    return raw_h + terrace


def link_obj(obj, parent=None):
    bpy.context.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def add_cylinder(bm, center, r_bot, r_top, height, segs=14, rot_euler=(0.0, 0.0, 0.0)):
    mat = (
        Matrix.Translation(center)
        @ Euler(rot_euler, "XYZ").to_matrix().to_4x4()
    )
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
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


def build_geological_block(root, mats):
    """Build the sculpted mountain terrain surface, 3-layer cutaway walls, smooth radial slip surface, and groundwater table."""
    nx, ny = 50, 38
    width, depth = 11.0, 8.0
    base_z = -2.35

    # 1. Top Terrain Surface Mesh
    mesh_top = bpy.data.meshes.new("TerrainSurfaceMesh")
    bm = bmesh.new()

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
    bm.to_mesh(mesh_top)
    bm.free()

    terrain_obj = bpy.data.objects.new("TerrainSurface", mesh_top)
    terrain_obj.data.materials.append(mats["terrain_surface"])
    link_obj(terrain_obj, root)

    # 2. Cutaway Side Walls (Upper Weathered Soil Layer & Deep Bedrock Layer)
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
            z_mid0 = max(base_z + 0.4, z_top0 - 0.85 - 0.14 * math.sin(x0 * 0.9))
            z_mid1 = max(base_z + 0.4, z_top1 - 0.85 - 0.14 * math.sin(x1 * 0.9))

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

    b1 = bm_rock.verts.new((-width / 2, -depth / 2, base_z))
    b2 = bm_rock.verts.new((-width / 2, depth / 2, base_z))
    b3 = bm_rock.verts.new((width / 2, depth / 2, base_z))
    b4 = bm_rock.verts.new((width / 2, -depth / 2, base_z))
    bm_rock.faces.new((b1, b2, b3, b4))

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

    # 3. Smooth Elliptical Radial Landslide Slip Surface (Mặt trượt địa chất)
    # Using radial rings so the boundary is a smooth organic curve with zero jagged steps!
    cx, cy = -0.82, -0.25
    rx, ry = 2.15, 1.85
    rings, segs = 12, 36

    mesh_slip = bpy.data.meshes.new("SlipSurfaceMesh")
    bm_slip = bmesh.new()
    mesh_wedge = bpy.data.meshes.new("UnstableWedgeMesh")
    bm_wedge = bmesh.new()

    slip_center_z = terrain_height(cx, cy) - 0.88
    wedge_center_z = terrain_height(cx, cy) + 0.028
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
            # Slight organic distortion so the landslide zone looks natural
            organic = 1.0 + 0.08 * math.sin(theta * 3.0 + 0.5) + 0.05 * math.cos(theta * 2.0)
            px = cx + math.cos(theta) * rx * r_frac * organic
            py = cy + math.sin(theta) * ry * r_frac * organic
            surf_z = terrain_height(px, py)
            bowl_depth = 0.88 * (1.0 - (r_frac ** 1.6))
            s_ring.append(bm_slip.verts.new((px, py, surf_z - bowl_depth - 0.02)))
            w_ring.append(bm_wedge.verts.new((px, py, surf_z + 0.025 * (1.0 - 0.4 * r_frac))))
        slip_rings.append(s_ring)
        wedge_rings.append(w_ring)

    # Connect center fan and radial rings
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

    # Add a 3D glowing Crown Scarp Perimeter Tube around the unstable wedge + Front Cutaway Slip Arc
    for s_idx in range(segs):
        nxt = (s_idx + 1) % segs
        v0 = wedge_rings[-1][s_idx].co
        v1 = wedge_rings[-1][nxt].co
        mid = (v0 + v1) * 0.5
        diff = v1 - v0
        rot_q = diff.to_track_quat("Z", "Y")
        bmesh.ops.create_cone(
            bm_slip,
            cap_ends=True,
            segments=8,
            radius1=0.028,
            radius2=0.028,
            depth=diff.length * 1.05,
            matrix=Matrix.Translation(mid + Vector((0, 0, 0.02))) @ rot_q.to_matrix().to_4x4(),
        )

    # Front cutaway slip plane indicator band (so the slip plane is also visible on the front geological wall)
    for i in range(18):
        fx0 = -2.8 + (i / 18) * 3.8
        fx1 = -2.8 + ((i + 1) / 18) * 3.8
        fy = -depth / 2 - 0.025
        norm0 = (fx0 - (-0.9)) / 1.9
        norm1 = (fx1 - (-0.9)) / 1.9
        fz0 = terrain_height(fx0, -depth / 2) - 0.22 - 0.62 * max(0.0, 1.0 - norm0 * norm0)
        fz1 = terrain_height(fx1, -depth / 2) - 0.22 - 0.62 * max(0.0, 1.0 - norm1 * norm1)
        sv1 = bm_slip.verts.new((fx0, fy, fz0 - 0.045))
        sv2 = bm_slip.verts.new((fx1, fy, fz1 - 0.045))
        sv3 = bm_slip.verts.new((fx1, fy, fz1 + 0.045))
        sv4 = bm_slip.verts.new((fx0, fy, fz0 + 0.045))
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

    # 4. Subsurface Groundwater Table Mesh (Mực nước ngầm) + Front Cutaway Aquifer Band
    mesh_water = bpy.data.meshes.new("GroundwaterTableMesh")
    bm_water = bmesh.new()
    wx_n, wy_n = 28, 22
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

    # Front cutaway aquifer layer slightly proud of the front wall (-Y - 0.018) so it glows when groundwater rises
    for i in range(wx_n - 1):
        x0 = wt_verts[i][0].co.x
        x1 = wt_verts[i + 1][0].co.x
        fy = -depth / 2 - 0.018
        wt_z0 = wt_verts[i][0].co.z
        wt_z1 = wt_verts[i + 1][0].co.z
        bot_z0 = max(base_z + 0.12, wt_z0 - 0.52)
        bot_z1 = max(base_z + 0.12, wt_z1 - 0.52)
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
    """Build the winding highway at the toe of the slope, retaining wall, and warning gantry."""
    mesh_road = bpy.data.meshes.new("MountainRoadMesh")
    bm = bmesh.new()
    steps = 38
    half_w = 0.44
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

    # Retaining wall along uphill side of road
    mesh_wall = bpy.data.meshes.new("RetainingWallMesh")
    bm_w = bmesh.new()
    for j in range(steps - 1):
        y0 = -depth / 2 + (j / (steps - 1)) * depth
        y1 = -depth / 2 + ((j + 1) / (steps - 1)) * depth
        rc0 = 2.45 + 0.18 * math.sin((y0 / 4.0) * 1.5) - half_w - 0.04
        rc1 = 2.45 + 0.18 * math.sin((y1 / 4.0) * 1.5) - half_w - 0.04
        z0 = terrain_height(rc0, y0)
        z1 = terrain_height(rc1, y1)
        h = 0.28
        v1 = bm_w.verts.new((rc0, y0, z0))
        v2 = bm_w.verts.new((rc1, y1, z1))
        v3 = bm_w.verts.new((rc1 - 0.06, y1, z1 + h))
        v4 = bm_w.verts.new((rc0 - 0.06, y0, z0 + h))
        bm_w.faces.new((v1, v2, v3, v4))
    bm_w.normal_update()
    bm_w.to_mesh(mesh_wall)
    bm_w.free()

    wall_obj = bpy.data.objects.new("RetainingWall", mesh_wall)
    wall_obj.data.materials.append(mats["concrete"])
    link_obj(wall_obj, root)


def build_gnss_station(name: str, x: float, y: float, root, mats, is_base=False):
    """Build a proportional, detailed GNSS RTK field station monument."""
    z = terrain_height(x, y)
    station_grp = bpy.data.objects.new(name, None)
    station_grp.empty_display_type = "PLAIN_AXES"
    station_grp.location = (x, y, z)
    link_obj(station_grp, root)

    # 1. Concrete Foundation & Stainless Mast & Telemetry Box
    mesh_body = bpy.data.meshes.new(f"{name}_BodyMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, 0.06), 0.20, 0.17, 0.12, segs=12)
    add_cylinder(bm, (0, 0, 0.24), 0.095, 0.08, 0.26, segs=12)
    mast_h = 0.86 if not is_base else 1.05
    add_cylinder(bm, (0, 0, 0.37 + mast_h * 0.5), 0.028, 0.024, mast_h, segs=10)
    add_box(bm, (0.075, 0.0, 0.50), (0.12, 0.15, 0.19))
    add_box(bm, (0.0, 0.0, 0.37 + mast_h - 0.12), (0.035, 0.30, 0.025))
    bm.normal_update()
    bm.to_mesh(mesh_body)
    bm.free()

    body_obj = bpy.data.objects.new(f"{name}_Body", mesh_body)
    body_obj.data.materials.append(mats["steel_housing"])
    link_obj(body_obj, station_grp)

    # 2. Solar Panel Array
    mesh_solar = bpy.data.meshes.new(f"{name}_SolarMesh")
    bm_s = bmesh.new()
    add_box(bm_s, (-0.09, -0.03, 0.64), (0.28, 0.22, 0.02), rot_euler=(0.35, -0.42, 0.0))
    bm_s.normal_update()
    bm_s.to_mesh(mesh_solar)
    bm_s.free()

    solar_obj = bpy.data.objects.new(f"{name}_Solar", mesh_solar)
    solar_obj.data.materials.append(mats["solar_panel"])
    link_obj(solar_obj, station_grp)

    # 3. Choke-Ring GNSS Dome Antenna
    mesh_dome = bpy.data.meshes.new(f"{name}_DomeMesh")
    bm_d = bmesh.new()
    top_z = 0.37 + mast_h
    add_cylinder(bm_d, (0, 0, top_z + 0.025), 0.13, 0.14, 0.05, segs=18)
    add_cylinder(bm_d, (0, 0, top_z + 0.075), 0.115, 0.05, 0.075, segs=18)
    bm_d.normal_update()
    bm_d.to_mesh(mesh_dome)
    bm_d.free()

    dome_obj = bpy.data.objects.new(f"{name}_Dome", mesh_dome)
    dome_obj.data.materials.append(mats["gnss_base_dome"] if is_base else mats["gnss_rover_dome"])
    link_obj(dome_obj, station_grp)

    # 4. Ground Telemetry Ring
    mesh_ring = bpy.data.meshes.new(f"{name}_RingMesh")
    bm_r = bmesh.new()
    bmesh.ops.create_circle(bm_r, cap_ends=False, radius=0.36, segments=28)
    bmesh.ops.extrude_edge_only(bm_r, edges=bm_r.edges)
    for v in bm_r.verts:
        if v.co.length > 0.35:
            v.co *= 1.14
        v.co.z += 0.025
    bm_r.normal_update()
    bm_r.to_mesh(mesh_ring)
    bm_r.free()

    ring_obj = bpy.data.objects.new(f"{name}_Ring", mesh_ring)
    ring_obj.data.materials.append(mats["ring_lime"] if is_base else mats["ring_teal"])
    link_obj(ring_obj, station_grp)

    return station_grp


def build_imu_borehole(root, mats):
    """Build the deep borehole inclinometer casing + 3 subsurface MEMS IMU nodes + surface displacement vector."""
    x, y = -1.08, -0.52
    z = terrain_height(x, y)
    grp = bpy.data.objects.new("IMU_Borehole_Assembly", None)
    grp.location = (x, y, z)
    link_obj(grp, root)

    mesh_casing = bpy.data.meshes.new("IMUCasingMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, -0.95), 0.048, 0.048, 2.15, segs=12)
    add_box(bm, (0, 0, 0.16), (0.22, 0.19, 0.13))
    bm.normal_update()
    bm.to_mesh(mesh_casing)
    bm.free()

    casing_obj = bpy.data.objects.new("IMU_Casing", mesh_casing)
    casing_obj.data.materials.append(mats["imu_amber"])
    link_obj(casing_obj, grp)

    mesh_nodes = bpy.data.meshes.new("IMUNodesMesh")
    bm_n = bmesh.new()
    for depth_z in (-0.32, -0.78, -1.35):
        add_cylinder(bm_n, (0, 0, depth_z), 0.085, 0.085, 0.16, segs=14)
    bm_n.normal_update()
    bm_n.to_mesh(mesh_nodes)
    bm_n.free()

    nodes_obj = bpy.data.objects.new("IMU_Subsurface_Nodes", mesh_nodes)
    nodes_obj.data.materials.append(mats["imu_glow"])
    link_obj(nodes_obj, grp)

    # Sleek 3D Displacement Vector Arrow at IMU head pointing down-slope (+X)
    mesh_arrow = bpy.data.meshes.new("DisplacementArrowMesh")
    bm_a = bmesh.new()
    rot_y = Euler((0.0, math.pi / 2 + 0.24, 0.0), "XYZ").to_matrix().to_4x4()
    bmesh.ops.create_cone(
        bm_a, cap_ends=True, segments=12, radius1=0.026, radius2=0.026, depth=0.68,
        matrix=Matrix.Translation((0.38, 0.0, 0.28)) @ rot_y
    )
    bmesh.ops.create_cone(
        bm_a, cap_ends=True, segments=12, radius1=0.085, radius2=0.004, depth=0.22,
        matrix=Matrix.Translation((0.76, 0.0, 0.19)) @ rot_y
    )
    bm_a.normal_update()
    bm_a.to_mesh(mesh_arrow)
    bm_a.free()

    arrow_obj = bpy.data.objects.new("DisplacementVectorArrow", mesh_arrow)
    arrow_obj.data.materials.append(mats["imu_glow"])
    link_obj(arrow_obj, grp)
    return grp


def build_rain_and_piezometer(root, mats):
    """Build sleek Tipping-Bucket Rain Gauge station and Cutaway Piezometer Groundwater Well."""
    # 1. Proportional Rain Gauge Weather Station on upper ridge
    rx, ry = -2.45, -1.55
    rz = terrain_height(rx, ry)
    rain_grp = bpy.data.objects.new("Rain_Gauge_Station", None)
    rain_grp.location = (rx, ry, rz)
    link_obj(rain_grp, root)

    mesh_rg_stand = bpy.data.meshes.new("RainGaugeStandMesh")
    bm_s = bmesh.new()
    add_cylinder(bm_s, (0, 0, 0.05), 0.16, 0.13, 0.10, segs=12)
    add_cylinder(bm_s, (0, 0, 0.28), 0.024, 0.024, 0.42, segs=10)
    bm_s.normal_update()
    bm_s.to_mesh(mesh_rg_stand)
    bm_s.free()

    stand_obj = bpy.data.objects.new("RainGaugeStand", mesh_rg_stand)
    stand_obj.data.materials.append(mats["steel_housing"])
    link_obj(stand_obj, rain_grp)

    mesh_rg = bpy.data.meshes.new("RainGaugeMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, 0.56), 0.115, 0.115, 0.22, segs=18)
    add_cylinder(bm, (0, 0, 0.70), 0.115, 0.145, 0.08, segs=18)
    bm.normal_update()
    bm.to_mesh(mesh_rg)
    bm.free()

    rg_obj = bpy.data.objects.new("RainGaugeCollector", mesh_rg)
    rg_obj.data.materials.append(mats["rain_cyan"])
    link_obj(rg_obj, rain_grp)

    # 2. Piezometer Well right on the front cutaway edge so both wellhead and subsurface water column are visible
    px, py = -1.75, -3.72
    pz = terrain_height(px, py)
    piezo_grp = bpy.data.objects.new("Piezometer_Well_Assembly", None)
    piezo_grp.location = (px, py, pz)
    link_obj(piezo_grp, root)

    mesh_well = bpy.data.meshes.new("PiezometerCasingMesh")
    bm_w = bmesh.new()
    add_cylinder(bm_w, (0, 0, 0.12), 0.13, 0.11, 0.24, segs=16)
    add_cylinder(bm_w, (0, -0.18, -0.82), 0.075, 0.075, 1.85, segs=16)
    bm_w.normal_update()
    bm_w.to_mesh(mesh_well)
    bm_w.free()

    well_obj = bpy.data.objects.new("PiezometerCasing", mesh_well)
    well_obj.data.materials.append(mats["steel_housing"])
    link_obj(well_obj, piezo_grp)

    mesh_col = bpy.data.meshes.new("PiezometerWaterMesh")
    bm_c = bmesh.new()
    add_cylinder(bm_c, (0, -0.22, -1.02), 0.095, 0.095, 1.15, segs=16)
    bm_c.normal_update()
    bm_c.to_mesh(mesh_col)
    bm_c.free()

    col_obj = bpy.data.objects.new("PiezometerWaterColumn", mesh_col)
    col_obj.data.materials.append(mats["water_glow"])
    link_obj(col_obj, piezo_grp)


def build_operations_hub(root, mats):
    """Build the Regional Operations & Early Warning Command Hub on the safe counter-ridge."""
    ox, oy = 4.02, -0.80
    oz = terrain_height(ox, oy)
    ops_grp = bpy.data.objects.new("Operations_Command_Node", None)
    ops_grp.location = (ox, oy, oz)
    link_obj(ops_grp, root)

    mesh_base = bpy.data.meshes.new("OpsBaseMesh")
    bm = bmesh.new()
    add_cylinder(bm, (0, 0, 0.08), 0.48, 0.44, 0.16, segs=8)
    add_cylinder(bm, (0, 0, 0.26), 0.32, 0.28, 0.22, segs=8)
    add_cylinder(bm, (0, 0, 0.76), 0.045, 0.025, 0.86, segs=8)
    bm.normal_update()
    bm.to_mesh(mesh_base)
    bm.free()

    base_obj = bpy.data.objects.new("OpsCommandStructure", mesh_base)
    base_obj.data.materials.append(mats["steel_housing"])
    link_obj(base_obj, ops_grp)

    mesh_beacon = bpy.data.meshes.new("OpsBeaconMesh")
    bm_b = bmesh.new()
    bmesh.ops.create_icosphere(bm_b, subdivisions=2, radius=0.19, matrix=Matrix.Translation((0, 0, 1.28)))
    bm_b.normal_update()
    bm_b.to_mesh(mesh_beacon)
    bm_b.free()

    beacon_obj = bpy.data.objects.new("OpsBeaconCore", mesh_beacon)
    beacon_obj.data.materials.append(mats["gnss_base_dome"])
    link_obj(beacon_obj, ops_grp)

    # Highway Early Warning Gantry across the road below
    gx, gy = 2.42, -1.35
    gz = terrain_height(gx, gy)
    mesh_gate = bpy.data.meshes.new("HighwayWarningGateMesh")
    bm_g = bmesh.new()
    add_cylinder(bm_g, (-0.48, 0, 0.28), 0.025, 0.025, 0.56, segs=8)
    add_cylinder(bm_g, (0.48, 0, 0.28), 0.025, 0.025, 0.56, segs=8)
    add_box(bm_g, (0, 0, 0.54), (1.02, 0.06, 0.13))
    bm_g.normal_update()
    bm_g.to_mesh(mesh_gate)
    bm_g.free()

    gate_obj = bpy.data.objects.new("HighwayWarningGate", mesh_gate)
    gate_obj.data.materials.append(mats["ring_lime"])
    gate_obj.location = (gx, gy, gz)
    link_obj(gate_obj, root)
    return ops_grp


def build_satellites_and_trees(root, mats):
    """Build 3 orbiting GNSS satellites and stylized mountain conifers."""
    sat_grp = bpy.data.objects.new("Satellite_Constellation", None)
    sat_grp.location = (-0.5, 0.0, 4.1)
    link_obj(sat_grp, root)

    sat_coords = [
        ("GNSS_Sat_01", (-2.5, -1.1, 0.35), (0.2, 0.35, -0.4)),
        ("GNSS_Sat_02", (0.35, 1.5, 0.72), (-0.25, 0.15, 0.6)),
        ("GNSS_Sat_03", (2.4, -0.85, 0.28), (0.3, -0.3, 0.2)),
    ]
    for s_name, loc, rot in sat_coords:
        mesh_sat = bpy.data.meshes.new(f"{s_name}_Mesh")
        bm = bmesh.new()
        add_box(bm, (0, 0, 0), (0.20, 0.20, 0.25))
        add_box(bm, (-0.38, 0, 0), (0.46, 0.16, 0.018))
        add_box(bm, (0.38, 0, 0), (0.46, 0.16, 0.018))
        add_cylinder(bm, (0, 0, -0.16), 0.07, 0.025, 0.09, segs=10)
        bm.normal_update()
        bm.to_mesh(mesh_sat)
        bm.free()

        sat_obj = bpy.data.objects.new(s_name, mesh_sat)
        sat_obj.location = loc
        sat_obj.rotation_euler = rot
        sat_obj.data.materials.append(mats["gnss_base_dome"])
        link_obj(sat_obj, sat_grp)

    mesh_trees = bpy.data.meshes.new("MountainForestMesh")
    bm_t = bmesh.new()
    tree_spots = [
        (-4.6, 2.8), (-4.2, 1.9), (-4.8, 0.6), (-4.5, -1.1), (-3.8, 3.1),
        (-2.2, 3.2), (-0.8, 3.3), (0.9, 3.1), (4.5, 2.2), (4.7, 0.9),
        (4.3, -2.5), (-3.9, -2.9), (0.4, -3.2)
    ]
    for idx, (tx, ty) in enumerate(tree_spots):
        tz = terrain_height(tx, ty)
        scale = 0.82 + (idx % 4) * 0.12
        add_cylinder(bm_t, (tx, ty, tz + 0.16 * scale), 0.14 * scale, 0.01, 0.32 * scale, segs=7)
        add_cylinder(bm_t, (tx, ty, tz + 0.34 * scale), 0.11 * scale, 0.01, 0.26 * scale, segs=7)
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
    key_data.energy = 3.5
    key_data.color = (0.88, 1.0, 0.96)
    key_obj = bpy.data.objects.new(name="KeyLight", object_data=key_data)
    key_obj.rotation_euler = (0.65, 0.35, -0.55)
    link_obj(key_obj)

    rim_data = bpy.data.lights.new(name="RimLight", type="AREA")
    rim_data.energy = 180.0
    rim_data.size = 6.0
    rim_data.color = (0.35, 0.92, 0.83)
    rim_obj = bpy.data.objects.new(name="RimLight", object_data=rim_data)
    rim_obj.location = (-5.5, 4.5, 5.0)
    rim_obj.rotation_euler = (-0.75, -0.55, 0.4)
    link_obj(rim_obj)

    fill_data = bpy.data.lights.new(name="SlipFillLight", type="POINT")
    fill_data.energy = 95.0
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

    look_at(cam_obj, (-2.6, -8.6, 4.4), (-0.4, -0.2, 0.1))
    hero_png = BLENDER_DIR / "hero_preview.png"
    scene.render.filepath = str(hero_png)
    bpy.ops.render.render(write_still=True)

    look_at(cam_obj, (1.2, -9.4, 5.0), (0.0, 0.0, -0.15))
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
            base_color=(0.05, 0.36, 0.33, 1.0),
            metallic=0.08,
            roughness=0.72,
            emission_color=(0.03, 0.20, 0.19),
            emission_strength=0.16,
        ),
        "soil_strata": make_material(
            "SoilStrataMat",
            base_color=(0.04, 0.24, 0.23, 1.0),
            metallic=0.05,
            roughness=0.82,
        ),
        "bedrock_strata": make_material(
            "BedrockStrataMat",
            base_color=(0.02, 0.13, 0.14, 1.0),
            metallic=0.18,
            roughness=0.88,
        ),
        "slip_surface": make_material(
            "SlipSurfaceMat",
            base_color=(1.0, 0.52, 0.08, 1.0),
            metallic=0.15,
            roughness=0.32,
            emission_color=(1.0, 0.45, 0.05),
            emission_strength=1.45,
            alpha=0.78,
        ),
        "unstable_wedge": make_material(
            "UnstableWedgeMat",
            base_color=(0.09, 0.48, 0.43, 1.0),
            metallic=0.10,
            roughness=0.58,
            emission_color=(0.14, 0.62, 0.54),
            emission_strength=0.22,
        ),
        "groundwater": make_material(
            "GroundwaterMat",
            base_color=(0.12, 0.68, 0.96, 1.0),
            metallic=0.1,
            roughness=0.22,
            emission_color=(0.14, 0.65, 0.95),
            emission_strength=0.72,
            alpha=0.62,
        ),
        "asphalt": make_material(
            "AsphaltRoadMat",
            base_color=(0.05, 0.15, 0.16, 1.0),
            metallic=0.15,
            roughness=0.78,
        ),
        "concrete": make_material(
            "ConcreteWallMat",
            base_color=(0.45, 0.62, 0.60, 1.0),
            metallic=0.1,
            roughness=0.65,
        ),
        "steel_housing": make_material(
            "SteelHousingMat",
            base_color=(0.76, 0.92, 0.89, 1.0),
            metallic=0.65,
            roughness=0.28,
        ),
        "solar_panel": make_material(
            "SolarPanelMat",
            base_color=(0.04, 0.22, 0.34, 1.0),
            metallic=0.75,
            roughness=0.18,
            emission_color=(0.08, 0.45, 0.62),
            emission_strength=0.35,
        ),
        "gnss_rover_dome": make_material(
            "GNSSRoverDomeMat",
            base_color=(0.36, 0.96, 0.86, 1.0),
            metallic=0.2,
            roughness=0.2,
            emission_color=(0.36, 0.92, 0.83),
            emission_strength=1.6,
        ),
        "gnss_base_dome": make_material(
            "GNSSBaseDomeMat",
            base_color=(0.84, 0.94, 0.45, 1.0),
            metallic=0.25,
            roughness=0.2,
            emission_color=(0.84, 0.94, 0.45),
            emission_strength=1.8,
        ),
        "ring_teal": make_material(
            "RingTealMat",
            base_color=(0.36, 0.92, 0.83, 1.0),
            emission_color=(0.36, 0.92, 0.83),
            emission_strength=1.4,
            alpha=0.75,
        ),
        "ring_lime": make_material(
            "RingLimeMat",
            base_color=(0.84, 0.94, 0.45, 1.0),
            emission_color=(0.84, 0.94, 0.45),
            emission_strength=1.5,
            alpha=0.82,
        ),
        "imu_amber": make_material(
            "IMUAmberMat",
            base_color=(0.95, 0.55, 0.12, 1.0),
            metallic=0.45,
            roughness=0.32,
            emission_color=(1.0, 0.55, 0.08),
            emission_strength=0.85,
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
            metallic=0.35,
            roughness=0.22,
            emission_color=(0.48, 0.83, 0.98),
            emission_strength=1.1,
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
            base_color=(0.08, 0.48, 0.42, 1.0),
            roughness=0.75,
            emission_color=(0.05, 0.25, 0.22),
            emission_strength=0.15,
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
