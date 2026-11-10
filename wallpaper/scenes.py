"""Blender side of the Halcyon daily background.

Run by daily.py, never by hand:
    blender --background --factory-startup --python scenes.py -- <params.json> <out.png> <result.json>

Each family builds its own geometry, materials, light and camera. Composition
is driven by one screen-space interest map: the top-centre band (search box)
and the lower half (news cards) stay calm, the upper side thirds carry detail.
"""
import json
import math
import random
import sys
import time

import bpy
import numpy as np
from mathutils import Vector


# ---------------------------------------------------------------- helpers

def lin(hex_colour, alpha=1.0):
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb) + (alpha,)


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def interest(u, v, bias):
    """Where detail may live, in screen space (u right, v up, both 0..1)."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    calm_top = np.exp(-((u - .5) / .2) ** 2) * smoothstep(.45, .68, v)
    upper = smoothstep(.30, .64, v)
    side = .25 + .75 * smoothstep(.10, .38, np.abs(u - .5))
    lean = 1 + bias * (u - .5) * 2
    return np.clip(upper * side * (1 - .92 * calm_top) * lean, 0, None) / (1 + abs(bias))


def star_mask(u, v):
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    calm_top = np.exp(-((u - .5) / .2) ** 2) * smoothstep(.45, .68, v)
    return np.clip(1 - .75 * calm_top - .45 * (1 - smoothstep(.25, .6, v)), 0, 1)


def mask_image(bias, width=320, height=180):
    u = (np.arange(width) + .5) / width
    v = (np.arange(height) + .5) / height
    uu, vv = np.meshgrid(u, v)  # row 0 is the bottom row, as Blender stores pixels
    rgba = np.zeros((height, width, 4), dtype=np.float32)
    rgba[..., 0] = interest(uu, vv, bias)
    rgba[..., 1] = star_mask(uu, vv)
    rgba[..., 3] = 1
    image = bpy.data.images.new('composition-mask', width, height, float_buffer=True)
    image.colorspace_settings.name = 'Non-Color'
    image.pixels.foreach_set(rgba.ravel())
    return image


class Nodes:
    """Tiny wrapper so node graphs read top to bottom."""

    def __init__(self, tree):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links

    def new(self, kind, **values):
        node = self.nodes.new(kind)
        for key, value in values.items():
            if key in node.inputs:
                node.inputs[key].default_value = value
            else:
                setattr(node, key, value)
        return node

    def link(self, out, inp):
        self.links.new(out, inp)

    def math(self, op, a, b=None, clamp=False):
        node = self.new('ShaderNodeMath', operation=op, use_clamp=clamp)
        self._feed(node.inputs[0], a)
        if b is not None:
            self._feed(node.inputs[1], b)
        return node.outputs[0]

    def ramp(self, fac, stops):
        node = self.new('ShaderNodeValToRGB')
        elements = node.color_ramp.elements
        while len(elements) < len(stops):
            elements.new(0.5)
        for element, (position, colour) in zip(elements, stops):
            element.position = position
            element.color = colour if len(colour) == 4 else tuple(colour) + (1,)
        self._feed(node.inputs['Fac'], fac)
        return node.outputs['Color']

    def scale(self, vector, factor):
        node = self.new('ShaderNodeVectorMath', operation='SCALE')
        self._feed(node.inputs[0], vector)
        self._feed(node.inputs['Scale'], factor)
        return node.outputs[0]

    def add(self, a, b):
        node = self.new('ShaderNodeVectorMath', operation='ADD')
        self._feed(node.inputs[0], a)
        self._feed(node.inputs[1], b)
        return node.outputs[0]

    def _feed(self, socket, value):
        if hasattr(value, 'is_output'):
            self.link(value, socket)
        else:
            socket.default_value = value


def new_material(name):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.node_tree.nodes.clear()
    graph = Nodes(material.node_tree)
    output = graph.new('ShaderNodeOutputMaterial')
    return material, graph, output


def emission_material(name, colour, strength):
    material, graph, output = new_material(name)
    emission = graph.new('ShaderNodeEmission', Color=lin(colour), Strength=strength)
    graph.link(emission.outputs[0], output.inputs['Surface'])
    return material


def principled(graph, **values):
    node = graph.new('ShaderNodeBsdfPrincipled')
    for key, value in values.items():
        if key in node.inputs:
            node.inputs[key].default_value = value
    return node


def link_object(name, data):
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def mesh_object(name, verts, faces, material=None, smooth=False):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if smooth:
        mesh.shade_smooth()
    if material:
        mesh.materials.append(material)
    return link_object(name, mesh)


class Boxes:
    """Collects axis-aligned boxes into one mesh."""

    def __init__(self):
        self.verts, self.faces = [], []

    def add(self, x0, x1, y0, y1, z0, z1):
        b = len(self.verts)
        self.verts += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                       (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        self.faces += [(b, b + 3, b + 2, b + 1), (b + 4, b + 5, b + 6, b + 7),
                       (b, b + 1, b + 5, b + 4), (b + 1, b + 2, b + 6, b + 5),
                       (b + 2, b + 3, b + 7, b + 6), (b + 3, b, b + 4, b + 7)]

    def build(self, name, material, bevel=0.0):
        if not self.verts:
            return None
        obj = mesh_object(name, self.verts, self.faces, material)
        if bevel:
            modifier = obj.modifiers.new('edge highlight', 'BEVEL')
            modifier.width = bevel
            modifier.segments = 2
            modifier.limit_method = 'NONE'
            modifier.harden_normals = True
        return obj


def sphere_mesh(name, segments=24, rings=12):
    verts, faces = [], []
    for r in range(1, rings):
        theta = math.pi * r / rings
        for s in range(segments):
            phi = 2 * math.pi * s / segments
            verts.append((math.sin(theta) * math.cos(phi), math.sin(theta) * math.sin(phi), math.cos(theta)))
    top, bottom = len(verts), len(verts) + 1
    verts += [(0, 0, 1), (0, 0, -1)]
    for r in range(rings - 2):
        for s in range(segments):
            a, b = r * segments + s, r * segments + (s + 1) % segments
            faces.append((a, b, b + segments, a + segments))
    for s in range(segments):
        faces.append((top, (s + 1) % segments, s))
        last = (rings - 2) * segments
        faces.append((bottom, last + s, last + (s + 1) % segments))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.shade_smooth()
    return mesh


def make_camera(location, target, lens, roll=0.0):
    data = bpy.data.cameras.new('camera')
    data.lens = lens
    data.sensor_width = 36
    data.sensor_fit = 'HORIZONTAL'
    data.clip_start = .05
    data.clip_end = 2000
    camera = link_object('camera', data)
    camera.location = location
    direction = Vector(target) - Vector(location)
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    camera.rotation_euler.rotate_axis('Z', math.radians(roll))
    bpy.context.scene.camera = camera
    bpy.context.view_layer.update()
    return camera


def screen_to_world(camera, u, v, depth):
    """Point at planar depth in front of the camera at screen position (u, v)."""
    data = camera.data
    scene = bpy.context.scene
    tan_h = data.sensor_width / 2 / data.lens
    tan_v = tan_h * scene.render.resolution_y / scene.render.resolution_x
    local = Vector(((u - .5) * 2 * tan_h * depth, (v - .5) * 2 * tan_v * depth, -depth))
    return camera.matrix_world @ local


def area_light(name, location, target, energy, size, colour):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = energy
    data.shape = 'DISK'
    data.size = size
    data.color = lin(colour)[:3]
    obj = link_object(name, data)
    obj.location = location
    obj.rotation_euler = (Vector(target) - Vector(location)).to_track_quat('-Z', 'Y').to_euler()
    return obj


def space_world(p, star_amount=1.0, nebula_amount=1.0):
    """Star field and nebula in screen space, shaped by the composition mask."""
    world = bpy.data.worlds.new('space')
    world.use_nodes = True
    world.node_tree.nodes.clear()
    graph = Nodes(world.node_tree)
    output = graph.new('ShaderNodeOutputWorld')
    background = graph.new('ShaderNodeBackground', Strength=1.0)
    coords = graph.new('ShaderNodeTexCoord')
    window = coords.outputs['Window']
    mask = graph.new('ShaderNodeTexImage', interpolation='Cubic', extension='EXTEND')
    mask.image = mask_image(p['bias'])
    graph.link(window, mask.inputs['Vector'])
    separate = graph.new('ShaderNodeSeparateColor')
    graph.link(mask.outputs['Color'], separate.inputs['Color'])
    interest_mask, stars_mask = separate.outputs['Red'], separate.outputs['Green']

    aspect = bpy.context.scene.render.resolution_x / bpy.context.scene.render.resolution_y
    stars_total = None
    for scale, ramp_edge, power, weight in ((110, .11, 7, 3.2), (260, .09, 9, 1.6)):
        mapping = graph.new('ShaderNodeMapping')
        mapping.inputs['Scale'].default_value = (scale * aspect, scale, 1)
        mapping.inputs['Location'].default_value = (p['seed_offset'], p['seed_offset'] * .7, 0)
        graph.link(window, mapping.inputs['Vector'])
        voronoi = graph.new('ShaderNodeTexVoronoi', Randomness=.9)
        graph.link(mapping.outputs[0], voronoi.inputs['Vector'])
        core = graph.ramp(voronoi.outputs['Distance'], [(0.0, (1, 1, 1)), (ramp_edge, (0, 0, 0))])
        twinkle = graph.math('POWER', graph.new('ShaderNodeSeparateColor').outputs[0], power)
        separate_random = twinkle.node.inputs[0].links[0].from_node
        graph.link(voronoi.outputs['Color'], separate_random.inputs['Color'])
        brightness = graph.math('MULTIPLY', graph.math('MULTIPLY', twinkle, weight * star_amount), stars_mask)
        layer = graph.scale(core, brightness)
        stars_total = layer if stars_total is None else graph.add(stars_total, layer)

    mapping = graph.new('ShaderNodeMapping')
    mapping.inputs['Scale'].default_value = (2.4 * aspect, 2.4, 1)
    mapping.inputs['Location'].default_value = (p['seed_offset'] * .13, 0, 0)
    graph.link(window, mapping.inputs['Vector'])
    noise = graph.new('ShaderNodeTexNoise', noise_dimensions='4D', Scale=1.0, Detail=12.0, Roughness=.62,
                      Distortion=.35, W=p['seed_offset'] % 50)
    graph.link(mapping.outputs[0], noise.inputs['Vector'])
    pal = p['palette']
    cloud = graph.ramp(noise.outputs['Fac'], [(0.32, lin('#000000')), (0.50, lin(pal['nebula_a'])),
                                               (0.64, lin(pal['nebula_b'])), (0.80, lin(pal['nebula_c']))])
    nebula = graph.scale(cloud, graph.math('MULTIPLY', interest_mask, nebula_amount * pal['nebula_strength']))
    base = graph.scale(lin(pal['space'])[:3], 1.0)
    total = graph.add(graph.add(base, nebula), stars_total)
    graph.link(total, background.inputs['Color'])
    graph.link(background.outputs[0], output.inputs['Surface'])
    bpy.context.scene.world = world
    return world


def glow(threshold, size, mix=-.55):
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new('CompositorNodeRLayers')
    glare = tree.nodes.new('CompositorNodeGlare')
    glare.glare_type = 'FOG_GLOW'
    glare.quality = 'HIGH'
    glare.threshold = threshold
    glare.size = size
    glare.mix = mix
    composite = tree.nodes.new('CompositorNodeComposite')
    tree.links.new(layers.outputs['Image'], glare.inputs['Image'])
    tree.links.new(glare.outputs['Image'], composite.inputs['Image'])


# ---------------------------------------------------------------- families

def neural_constellation(p, rng):
    """A neural network of glowing nodes and synapses suspended in deep space."""
    pal = p['palette']
    camera = make_camera((0, 0, 0), (0, 10, p['pitch']), lens=34, roll=p['roll'])
    space_world(p, star_amount=1.0, nebula_amount=1.0)

    nodes = []
    tries = 0
    while len(nodes) < p['count'] and tries < 60000:
        tries += 1
        u, v = rng.random(), rng.random()
        depth = rng.uniform(7.0, 30.0)
        weight = float(interest(u, v, p['bias'])) ** 1.25
        if rng.random() > weight * .97 + .012:
            continue
        point = screen_to_world(camera, u, v, depth)
        if all((point - q).length > .75 for q, _ in nodes):
            nodes.append((point, depth))

    # Synapses: each node links to its nearest neighbours; long jumps are dropped.
    from bpy_extras.object_utils import world_to_camera_view
    edges = set()
    for i, (a, _) in enumerate(nodes):
        near = sorted(((a - b).length, j) for j, (b, _) in enumerate(nodes) if j != i)
        for distance, j in near[:rng.choice((2, 3, 3, 4))]:
            middle = world_to_camera_view(bpy.context.scene, camera, (a + nodes[j][0]) / 2)
            if distance < p['reach'] and interest(middle.x, middle.y, 0.0) > .12:  # keep links out of calm zones
                edges.add((min(i, j), max(i, j)))

    curve = bpy.data.curves.new('synapses', 'CURVE')
    curve.dimensions = '3D'
    curve.bevel_depth = .011
    curve.bevel_resolution = 2
    pulses = []
    for i, j in sorted(edges):
        a, b = nodes[i][0], nodes[j][0]
        sag = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * (a - b).length * .08
        spline = curve.splines.new('POLY')
        steps = 12
        spline.points.add(steps)
        for k in range(steps + 1):
            t = k / steps
            point = a.lerp(b, t) + sag * 4 * t * (1 - t)
            spline.points[k].co = (point.x, point.y, point.z, 1)
        if rng.random() < .3:
            t = rng.uniform(.2, .8)
            pulses.append(a.lerp(b, t) + sag * 4 * t * (1 - t))
    synapse_material, graph, output = new_material('synapse')
    info = graph.new('ShaderNodeObjectInfo')
    geometry = graph.new('ShaderNodeNewGeometry')
    flicker = graph.new('ShaderNodeTexNoise', Scale=.35, Detail=2.0)
    graph.link(geometry.outputs['Position'], flicker.inputs['Vector'])
    colour = graph.ramp(flicker.outputs['Fac'], [(0.35, lin(pal['link_a'])), (0.65, lin(pal['link_b']))])
    emission = graph.new('ShaderNodeEmission')
    graph.link(colour, emission.inputs['Color'])
    graph.link(graph.math('MULTIPLY', graph.math('POWER', flicker.outputs['Fac'], 2.2), 9.0), emission.inputs['Strength'])
    graph.link(emission.outputs[0], output.inputs['Surface'])
    del info
    curve.materials.append(synapse_material)
    link_object('synapses', curve)

    node_material, graph, output = new_material('neuron')
    info = graph.new('ShaderNodeObjectInfo')
    colour = graph.ramp(info.outputs['Random'], [(0.0, lin(pal['node_a'])), (0.55, lin(pal['node_b'])),
                                                  (1.0, lin(pal['node_c']))])
    emission = graph.new('ShaderNodeEmission')
    graph.link(colour, emission.inputs['Color'])
    graph.link(graph.math('ADD', graph.math('MULTIPLY', info.outputs['Random'], 3.5), 1.6), emission.inputs['Strength'])
    graph.link(emission.outputs[0], output.inputs['Surface'])
    sphere = sphere_mesh('neuron', 20, 10)
    sphere.materials.append(node_material)

    cage_material = emission_material('cage', pal['link_a'], .9)
    hubs = sorted(range(len(nodes)), key=lambda k: -sum(1 for e in edges if k in e))[:p['hubs']]
    for k, (point, depth) in enumerate(nodes):
        obj = link_object(f'neuron {k}', sphere)
        radius = rng.uniform(.03, .06) * (1 + depth / 30)
        if k in hubs:
            radius *= 1.7
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=radius * 2.6, location=point)
            cage = bpy.context.object
            cage.rotation_euler = (rng.uniform(0, 3), rng.uniform(0, 3), rng.uniform(0, 3))
            cage.data.materials.append(cage_material)
            wire = cage.modifiers.new('cage', 'WIREFRAME')
            wire.thickness = radius * .08
        obj.location = point
        obj.scale = (radius,) * 3
    pulse_material = emission_material('pulse', '#FFFFFF', 18.0)
    pulse_sphere = sphere_mesh('pulse', 12, 6)
    pulse_sphere.materials.append(pulse_material)
    for k, point in enumerate(pulses):
        obj = link_object(f'pulse {k}', pulse_sphere)
        obj.location = point
        obj.scale = (.028,) * 3

    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = 12.0
    camera.data.dof.aperture_fstop = .4
    glow(threshold=.9, size=8, mix=-.45)
    return dict(nodes=len(nodes), synapses=len(edges), pulses=len(pulses))


def silicon_die(p, rng):
    """A macro view across a chip die: memory macros and standard-cell rows either
    side of a polished routing channel, lit low so every metal edge catches light."""
    pal = p['palette']
    side = p['side']
    height = p['camera_height']
    look_y = 5.5
    camera = make_camera((p['camera_x'], -2.0, height), (p['camera_x'] * .3 + side * .6, look_y, 0.0),
                         lens=30, roll=p['roll'])

    world = bpy.data.worlds.new('dark')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = lin(pal['space'])
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
    bpy.context.scene.world = world

    channel = p['channel']
    x_max, y_min, y_max = 30.0, -6.0, 46.0
    cell = .25
    nx, ny = int(2 * x_max / cell), int((y_max - y_min) / cell)
    taken = np.zeros((nx, ny), dtype=bool)

    def index(x, y):
        return int((x + x_max) / cell), int((y - y_min) / cell)

    def region_free(x0, x1, y0, y1):
        i0, j0 = index(x0, y0)
        i1, j1 = index(x1, y1)
        if i0 < 0 or j0 < 0 or i1 >= nx or j1 >= ny:
            return False
        return not taken[i0:i1 + 1, j0:j1 + 1].any()

    def take(x0, x1, y0, y1):
        i0, j0 = index(x0, y0)
        i1, j1 = index(x1, y1)
        taken[i0:i1 + 1, j0:j1 + 1] = True

    macros, cells, traces, data_traces, vias, rails = Boxes(), Boxes(), Boxes(), Boxes(), Boxes(), Boxes()
    # Memory macros first, largest blocks, kept off the channel.
    placed = 0
    for _ in range(4000):
        if placed >= p['macros']:
            break
        w, d = rng.uniform(1.6, 4.8), rng.uniform(1.8, 6.5)
        sgn = rng.choice((-1, 1)) if rng.random() > .25 else side
        x0 = sgn * rng.uniform(channel + .5, 16.0)
        x0, x1 = (x0, x0 + sgn * w) if sgn > 0 else (x0 - w, x0)
        x0, x1 = min(x0, x1), max(x0, x1)
        y0 = rng.uniform(-2.0, 34.0)
        y1 = y0 + d
        if region_free(x0 - .3, x1 + .3, y0 - .3, y1 + .3):
            take(x0 - .15, x1 + .15, y0 - .15, y1 + .15)
            macros.add(x0, x1, y0, y1, 0, rng.uniform(.14, .26))
            placed += 1
    # Standard-cell rows fill the rest of each side.
    row = .32
    y = y_min
    while y < y_max - row:
        for sgn in (-1, 1):
            x = channel + .35
            while x < x_max - 1:
                w = rng.uniform(.07, .45)
                gap = rng.choice((.02, .02, .03, .06))
                xa, xb = sgn * x, sgn * (x + w)
                xa, xb = min(xa, xb), max(xa, xb)
                if region_free(xa, xb, y + .02, y + row - .02):
                    cells.add(xa, xb, y + .03, y + row - .03, 0, rng.uniform(.035, .085))
                x += w + gap
        y += row
    # Routing on top of the cell rows, never through a macro.
    for _ in range(p['traces']):
        sgn = rng.choice((-1, 1))
        if rng.random() < .62:  # along the channel
            x = sgn * (channel + .4 + round(rng.uniform(0, 14) / .16) * .16)
            y0 = rng.uniform(y_min, y_max - 2)
            y1 = y0 + rng.uniform(.8, 9.0)
            w = rng.choice((.035, .045, .06))
            if region_free(min(x - w, x + w), max(x - w, x + w), y0, y1):
                target = data_traces if rng.random() < p['data_share'] else traces
                z = .1 if target is traces else .102
                target.add(x - w, x + w, y0, y1, z - .018, z)
                vias.add(x - w * 1.5, x + w * 1.5, y0, y0 + w * 3, 0, z + .012)
                vias.add(x - w * 1.5, x + w * 1.5, y1 - w * 3, y1, 0, z + .012)
        else:  # across, on a higher metal layer
            y = round(rng.uniform(y_min, y_max) / .32) * .32 + .16
            xa = sgn * (channel + .4 + rng.uniform(0, 10))
            xb = xa + sgn * rng.uniform(.6, 5.0)
            x0, x1 = min(xa, xb), max(xa, xb)
            if region_free(x0, x1, y - .05, y + .05):
                traces.add(x0, x1, y - .03, y + .03, .118, .132)
    for sgn in (-1, 1):
        rails.add(sgn * channel - .09, sgn * channel + .09, y_min, y_max, 0, .03)

    substrate_material, graph, output = new_material('substrate')
    coords = graph.new('ShaderNodeTexCoord')
    grain = graph.new('ShaderNodeTexNoise', Scale=3.0, Detail=6.0)
    graph.link(coords.outputs['Object'], grain.inputs['Vector'])
    bsdf = principled(graph, **{'Base Color': lin(pal['substrate']), 'Metallic': .55})
    graph.link(graph.math('ADD', graph.math('MULTIPLY', grain.outputs['Fac'], .14), .2), bsdf.inputs['Roughness'])
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, (y_min + y_max) / 2, 0))
    plane = bpy.context.object
    plane.scale = (2 * x_max, y_max - y_min, 1)
    plane.data.materials.append(substrate_material)

    cell_material, graph, output = new_material('cells')
    info = graph.new('ShaderNodeObjectInfo')
    geometry = graph.new('ShaderNodeNewGeometry')
    tint = graph.new('ShaderNodeTexNoise', Scale=.6, Detail=1.0)
    graph.link(geometry.outputs['Position'], tint.inputs['Vector'])
    colour = graph.ramp(tint.outputs['Fac'], [(0.3, lin(pal['cell_a'])), (0.7, lin(pal['cell_b']))])
    bsdf = principled(graph, **{'Metallic': .35, 'Roughness': .28, 'Thin Film Thickness': pal['film'],
                                'Thin Film IOR': 1.45})
    graph.link(colour, bsdf.inputs['Base Color'])
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    del info

    macro_material, graph, output = new_material('macro')
    geometry = graph.new('ShaderNodeNewGeometry')
    bricks = graph.new('ShaderNodeTexBrick', Scale=7.0, offset=0.0, squash=1.0, **{'Mortar Size': .04,
                       'Brick Width': .5, 'Row Height': .25, 'Mortar Smooth': .1})
    graph.link(geometry.outputs['Position'], bricks.inputs['Vector'])
    colour = graph.ramp(bricks.outputs['Fac'], [(0.0, lin(pal['macro'])), (1.0, lin(pal['metal']))])
    bsdf = principled(graph, **{'Roughness': .34, 'Thin Film Thickness': pal['film'] * .7, 'Thin Film IOR': 1.4})
    graph.link(colour, bsdf.inputs['Base Color'])
    graph.link(bricks.outputs['Fac'], bsdf.inputs['Metallic'])
    graph.link(bsdf.outputs[0], output.inputs['Surface'])

    metal_material, graph, output = new_material('metal')
    bsdf = principled(graph, **{'Base Color': lin(pal['metal']), 'Metallic': 1.0, 'Roughness': .2})
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    via_material, graph, output = new_material('via')
    bsdf = principled(graph, **{'Base Color': lin(pal['via']), 'Metallic': 1.0, 'Roughness': .16})
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    data_material = emission_material('data', pal['data'], pal['data_strength'])

    cells.build('standard cells', cell_material, bevel=.006)
    macros.build('memory macros', macro_material, bevel=.02)
    traces.build('metal routing', metal_material, bevel=.004)
    rails.build('power rails', metal_material, bevel=.01)
    vias.build('vias', via_material, bevel=.003)
    data_traces.build('signal lines', data_material)

    # Raking light from the side catches block edges without mirroring into flat tops.
    area_light('raking key', (side * 22.0, 14.0, 1.6), (0.0, 12.0, 0.0), p['key_energy'], 6.0, pal['key'])
    area_light('far rim', (-side * 14.0, 52.0, 6.0), (0.0, 14.0, 0.0), p['key_energy'] * .12, 10.0, pal['key'])
    area_light('cool fill', (-side * 10.0, -4.0, 6.0), (0.0, 8.0, 0.0), p['key_energy'] * .06, 12.0, pal['fill'])

    # Focus on the upper side thirds; the foreground and the far channel fall soft.
    data = camera.data
    tan_v = 18 / data.lens * 9 / 16
    pitch = math.atan2(height, look_y + 2.0)
    angle = pitch - math.atan((.70 - .5) * 2 * tan_v)
    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = height / math.sin(angle) * math.cos(math.atan((.70 - .5) * 2 * tan_v))
    camera.data.dof.aperture_fstop = p['fstop']
    glow(threshold=1.0, size=7, mix=-.6)
    return dict(macros=placed, cells=len(cells.verts) // 8, traces=len(traces.verts) // 8,
                signal_lines=len(data_traces.verts) // 8)


def orbital_horizon(p, rng):
    """The night side of a planet seen from low orbit: city grids wired by a
    faint data network, a thin atmosphere lit by a sun about to rise."""
    pal = p['palette']
    radius = 100.0
    altitude = p['altitude']
    side = p['side']
    dip = math.acos((radius + p['air'] * .25) / (radius + altitude))  # the visible glow edge, not the bare limb
    tan_v = 18 / 35 * 9 / 16
    pitch = dip - math.atan((.5 - p['horizon']) * 2 * tan_v)
    eye = Vector((0, 0, radius + altitude))
    target = eye + Vector((0, math.cos(pitch), -math.sin(pitch))) * 10
    camera = make_camera(eye, target, lens=35, roll=p['roll'])
    space_world(p, star_amount=1.0, nebula_amount=.85)

    sun = Vector((side * p['sun_azimuth'], 1.0, -p['sun_depth'])).normalized()

    def facing_sun(graph):
        geometry = graph.new('ShaderNodeNewGeometry')
        dot = graph.new('ShaderNodeVectorMath', operation='DOT_PRODUCT')
        graph.link(geometry.outputs['Normal'], dot.inputs[0])
        dot.inputs[1].default_value = sun
        return dot.outputs['Value']

    planet_material, graph, output = new_material('planet')
    coords = graph.new('ShaderNodeTexCoord')
    obj_coords = coords.outputs['Object']
    land_noise = graph.new('ShaderNodeTexNoise', noise_dimensions='4D', Scale=.045, Detail=9.0, Roughness=.58,
                           W=p['seed_offset'] % 40)
    graph.link(obj_coords, land_noise.inputs['Vector'])
    land = graph.math('SUBTRACT', graph.math('MULTIPLY', land_noise.outputs['Fac'], 9.0), 4.5, clamp=True)
    cluster_noise = graph.new('ShaderNodeTexNoise', Scale=.22, Detail=4.0, Roughness=.5)
    graph.link(obj_coords, cluster_noise.inputs['Vector'])
    cluster = graph.math('SUBTRACT', graph.math('MULTIPLY', cluster_noise.outputs['Fac'], 6.0), 3.1, clamp=True)
    populated = graph.math('MULTIPLY', land, graph.math('POWER', cluster, 2.0))
    sunlit = facing_sun(graph)
    night = graph.math('SUBTRACT', 1.0, graph.math('MULTIPLY', graph.math('ADD', sunlit, .06), 9.0, clamp=True),
                       clamp=True)
    cities = graph.new('ShaderNodeTexVoronoi', Scale=.55, Randomness=1.0)
    graph.link(obj_coords, cities.inputs['Vector'])
    city_core = graph.ramp(cities.outputs['Distance'], [(0.0, (1, 1, 1)), (0.06, (0, 0, 0))])
    city_size = graph.new('ShaderNodeSeparateColor')
    graph.link(cities.outputs['Color'], city_size.inputs['Color'])
    city = graph.math('MULTIPLY', graph.new('ShaderNodeSeparateColor').outputs[0], 1.0)
    graph.link(city_core, city.node.inputs[0].links[0].from_node.inputs['Color'])
    city = graph.math('MULTIPLY', city, graph.math('POWER', city_size.outputs['Red'], 2.0))
    network = graph.new('ShaderNodeTexVoronoi', feature='DISTANCE_TO_EDGE', Scale=.9, Randomness=.85)
    graph.link(obj_coords, network.inputs['Vector'])
    wires = graph.math('SUBTRACT', 1.0, graph.math('MULTIPLY', network.outputs['Distance'], 110.0), clamp=True)
    city_light = graph.scale(lin(pal['city'])[:3], graph.math('MULTIPLY', city, pal['city_strength']))
    wire_light = graph.scale(lin(pal['wire'])[:3], graph.math('MULTIPLY', wires, pal['wire_strength']))
    # Lights fade toward the camera so the lower half (under the news cards) stays quiet.
    to_eye = graph.new('ShaderNodeVectorMath', operation='DISTANCE')
    graph.link(graph.new('ShaderNodeNewGeometry').outputs['Position'], to_eye.inputs[0])
    to_eye.inputs[1].default_value = eye
    fade = graph.new('ShaderNodeMapRange', **{'From Min': 6.0, 'From Max': 26.0, 'To Min': .0, 'To Max': 1.0})
    graph.link(to_eye.outputs['Value'], fade.inputs['Value'])
    lights = graph.scale(graph.add(city_light, wire_light),
                         graph.math('MULTIPLY', graph.math('MULTIPLY', populated, night), fade.outputs[0]))
    surface = graph.ramp(land, [(0.0, lin(pal['ocean'])), (1.0, lin(pal['land']))])
    bsdf = principled(graph, **{'Emission Strength': 1.0})
    graph.link(surface, bsdf.inputs['Base Color'])
    graph.link(graph.math('ADD', graph.math('MULTIPLY', land, .3), .55), bsdf.inputs['Roughness'])
    graph.link(lights, bsdf.inputs['Emission Color'])
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=768, ring_count=384, radius=radius, location=(0, 0, 0))
    planet = bpy.context.object
    planet.data.shade_smooth()
    planet.data.materials.append(planet_material)

    # Atmosphere as an emissive volume: glow integrates along the ray, so the limb,
    # where the path through the air is longest, is bright and the ground below stays dark.
    air_material, graph, output = new_material('atmosphere')
    geometry = graph.new('ShaderNodeNewGeometry')
    length = graph.new('ShaderNodeVectorMath', operation='LENGTH')
    graph.link(geometry.outputs['Position'], length.inputs[0])
    height_above = graph.math('SUBTRACT', length.outputs['Value'], radius)
    density = graph.math('EXPONENT', graph.math('MULTIPLY', height_above, -1.0 / p['scale_height']))
    unit = graph.new('ShaderNodeVectorMath', operation='NORMALIZE')
    graph.link(geometry.outputs['Position'], unit.inputs[0])
    dot = graph.new('ShaderNodeVectorMath', operation='DOT_PRODUCT')
    graph.link(unit.outputs[0], dot.inputs[0])
    dot.inputs[1].default_value = sun
    toward = graph.math('ADD', graph.math('MULTIPLY', dot.outputs['Value'], 2.2), .45, clamp=True)
    colour = graph.ramp(toward, [(0.0, lin(pal['air_far'])), (0.5, lin(pal['air_mid'])),
                                 (0.9, lin(pal['air_sun'])), (1.0, lin('#FFF1DC'))])
    sun_boost = graph.math('ADD', graph.math('MULTIPLY', graph.math('POWER', toward, 4.0), pal['sun_glow']), .25)
    strength = graph.math('MULTIPLY', graph.math('MULTIPLY', density, sun_boost), p['air_glow'])
    emission = graph.new('ShaderNodeEmission')
    graph.link(colour, emission.inputs['Color'])
    graph.link(strength, emission.inputs['Strength'])
    graph.link(emission.outputs[0], output.inputs['Volume'])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=768, ring_count=384, radius=radius + p['air'], location=(0, 0, 0))
    air = bpy.context.object
    air.data.shade_smooth()
    air.data.materials.append(air_material)

    sun_data = bpy.data.lights.new('sun', 'SUN')
    sun_data.energy = 3.5
    sun_data.angle = math.radians(.6)
    sun_data.color = lin(pal['sunlight'])[:3]
    sun_obj = link_object('sun', sun_data)
    sun_obj.rotation_euler = (-sun).to_track_quat('-Z', 'Y').to_euler()

    # A satellite train crossing the upper side third: a short, straight line of lights.
    train_material = emission_material('satellites', '#F2F6FF', 9.0)
    dot = sphere_mesh('satellite', 10, 5)
    dot.materials.append(train_material)
    u0 = .5 + side * rng.uniform(.26, .36)
    v0 = rng.uniform(.74, .86)
    du, dv = -side * .0085, rng.uniform(-.006, -.002)
    for k in range(p['satellites']):
        obj = link_object(f'satellite {k}', dot)
        obj.location = screen_to_world(camera, u0 + du * k, v0 + dv * k + .0004 * k * k * .1, 60.0)
        obj.scale = (.032 * (1 - k / (p['satellites'] * 1.6)),) * 3
    glow(threshold=.85, size=8, mix=-.5)
    return dict(dip_degrees=round(math.degrees(dip), 2), pitch_degrees=round(math.degrees(pitch), 2))


FAMILIES = {
    'neural-constellation': neural_constellation,
    'silicon-die': silicon_die,
    'orbital-horizon': orbital_horizon,
}


# ---------------------------------------------------------------- render

def configure_device(scene):
    preferences = bpy.context.preferences.addons['cycles'].preferences
    for backend in ('OPTIX', 'CUDA'):
        try:
            preferences.compute_device_type = backend
            preferences.get_devices()
            devices = [d for d in preferences.devices if d.type == backend]
            if devices:
                for d in preferences.devices:
                    d.use = d.type == backend
                scene.cycles.device = 'GPU'
                return dict(backend=backend, devices=[d.name for d in devices])
        except Exception as exc:  # noqa: BLE001 - report and try the next backend
            print(f'Device {backend} unavailable: {exc}', flush=True)
    scene.cycles.device = 'CPU'
    return dict(backend='CPU', devices=['CPU'])


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    params_path, out_path, result_path = argv[:3]
    with open(params_path, encoding='utf-8') as handle:
        p = json.load(handle)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    device = configure_device(scene)
    scene.render.resolution_x = p['width']
    scene.render.resolution_y = p['height']
    scene.render.resolution_percentage = 100
    scene.cycles.samples = p['samples']
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = .02
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = 'OPTIX' if device['backend'] == 'OPTIX' else 'OPENIMAGEDENOISE'
    scene.cycles.max_bounces = 6
    scene.cycles.glossy_bounces = 4
    scene.cycles.transparent_max_bounces = 8
    scene.cycles.seed = p['seed'] % 2147483647
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = p['look']
    scene.view_settings.exposure = p['exposure']
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.compression = 40
    scene.render.filepath = out_path

    rng = random.Random(p['seed'])
    started = time.perf_counter()
    stats = FAMILIES[p['family']](p, rng)
    build_seconds = time.perf_counter() - started
    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    render_seconds = time.perf_counter() - started
    result = dict(device=device, render_seconds=round(render_seconds, 2), build_seconds=round(build_seconds, 2),
                  blender=bpy.app.version_string, scene_stats=stats)
    with open(result_path, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print('SCENE_RESULT ' + json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
