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
    scene = bpy.context.scene

    def crosses_calm(a, b):
        for t in (.1, .3, .5, .7, .9):
            s = world_to_camera_view(scene, camera, a.lerp(b, t))
            if interest(s.x, s.y, 0.0) < .14:
                return True
        return False

    edges = set()
    for i, (a, _) in enumerate(nodes):
        near = sorted(((a - b).length, j) for j, (b, _) in enumerate(nodes) if j != i)
        for distance, j in near[:rng.choice((2, 3, 3, 4))]:
            if distance < p['reach'] and not crosses_calm(a, nodes[j][0]):
                edges.add((min(i, j), max(i, j)))
    # Drop orphan fragments: linked groups too small to read as part of a network.
    parent = list(range(len(nodes)))

    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, j in edges:
        parent[root(i)] = root(j)
    sizes = {}
    for k in range(len(nodes)):
        sizes[root(k)] = sizes.get(root(k), 0) + 1
    keep = [k for k in range(len(nodes)) if sizes[root(k)] >= 8]
    remap = {old: new for new, old in enumerate(keep)}
    nodes = [nodes[k] for k in keep]
    edges = {(remap[i], remap[j]) for i, j in edges if i in remap and j in remap}

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
    if p['cross']:  # a second routing channel crossing the die, far enough to sit in the upper part
        j0, j1 = int((p['cross'] - channel * .7 - y_min) / cell), int((p['cross'] + channel * .7 - y_min) / cell)
        taken[:, j0:j1 + 1] = True

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
        w, d = rng.uniform(1.6, 4.8) * p['macro_scale'], rng.uniform(1.8, 6.5) * p['macro_scale']
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

    die = [plane, cells.build('standard cells', cell_material, bevel=.006),
           macros.build('memory macros', macro_material, bevel=.02),
           traces.build('metal routing', metal_material, bevel=.004),
           rails.build('power rails', metal_material, bevel=.01),
           vias.build('vias', via_material, bevel=.003),
           data_traces.build('signal lines', data_material)]
    # Layout variation: the whole die turns about a point ahead of the camera,
    # so the channel can run straight or diagonally across the frame.
    pivot = bpy.data.objects.new('die pivot', None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.location = (0, 9.0, 0)
    for obj in die:
        if obj:
            obj.parent = pivot
            obj.location = obj.location - Vector((0, 9.0, 0))
    pivot.rotation_euler = (0, 0, math.radians(p['layout_angle']))

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
    cluster = graph.math('SUBTRACT', graph.math('MULTIPLY', cluster_noise.outputs['Fac'], 6.0), 2.75, clamp=True)
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
    wires = graph.math('SUBTRACT', 1.0, graph.math('MULTIPLY', network.outputs['Distance'], 55.0), clamp=True)
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

    # Data links: thin arcs of light hopping between city clusters near the horizon.
    arcs = bpy.data.curves.new('data links', 'CURVE')
    arcs.dimensions = '3D'
    arcs.bevel_depth = .012
    arcs.bevel_resolution = 1
    forward = Vector((0, math.cos(pitch), 0)).normalized()
    hubs = []
    for _ in range(p['links'] * 2):
        distance = rng.uniform(15.0, 28.0)
        azimuth = rng.uniform(-.75, .75)
        direction = Vector((math.sin(azimuth), math.cos(azimuth), 0))
        ground = Vector((direction.x * distance, direction.y * distance, 0))
        hubs.append((ground + Vector((0, 0, radius + altitude))).normalized() * (radius + .02))
    for k in range(p['links']):
        a = hubs[k]
        b = min((h for h in hubs if h is not a), key=lambda h: (h - a).length)
        if not 2.0 < (a - b).length < 9.0:
            continue
        spline = arcs.splines.new('POLY')
        steps = 40
        spline.points.add(steps)
        peak = (a - b).length * rng.uniform(.025, .045)
        for i in range(steps + 1):
            t = i / steps
            point = a.lerp(b, t)
            point = point.normalized() * (radius + .02 + peak * 4 * t * (1 - t))
            spline.points[i].co = (point.x, point.y, point.z, 1)
    arcs.materials.append(emission_material('data link', pal['wire'], pal['link_strength']))
    link_object('data links', arcs)
    del forward

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
    return dict(dip_degrees=round(math.degrees(dip), 2), pitch_degrees=round(math.degrees(pitch), 2),
                links=len(arcs.splines))


def plain_world(colour, strength=1.0):
    world = bpy.data.worlds.new('plain')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = lin(colour)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = strength
    bpy.context.scene.world = world
    return world


def principled_material(name, colour, metallic=0.0, roughness=.4, **extra):
    material, graph, output = new_material(name)
    values = {'Base Color': lin(colour), 'Metallic': metallic, 'Roughness': roughness}
    values.update(extra)
    bsdf = principled(graph, **values)
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    return material


def random_emission_material(name, colour_a, colour_b, low, high):
    """Emission whose colour and strength vary per object (Object Info Random)."""
    material, graph, output = new_material(name)
    info = graph.new('ShaderNodeObjectInfo')
    colour = graph.ramp(info.outputs['Random'], [(0.0, lin(colour_a)), (1.0, lin(colour_b))])
    emission = graph.new('ShaderNodeEmission')
    graph.link(colour, emission.inputs['Color'])
    graph.link(graph.math('ADD', graph.math('MULTIPLY', info.outputs['Random'], high - low), low),
               emission.inputs['Strength'])
    graph.link(emission.outputs[0], output.inputs['Surface'])
    return material


def data_centre(p, rng):
    """An aisle between server racks in a dark hall: rows of status LEDs on the
    side thirds, light shafts in thin haze, a quiet ceiling over the aisle."""
    pal = p['palette']
    side = p['side']
    aisle = p['aisle']
    eye_z = p['eye_z']
    camera = make_camera((side * p['eye_x'], -1.5, eye_z), (side * p['look_x'], 30.0, eye_z + p['tilt']),
                         lens=p['lens'], roll=p['roll'])
    plain_world(pal['space'])
    length, rack_w, rack_h, depth = 44.0, .6, 2.25, 1.1
    bodies, panels, vents, leds_a, leds_b, strips, trays = (Boxes() for _ in range(7))
    for sgn in (-1, 1):
        y = -2.0 + rng.uniform(0, .3)
        while y < length:
            if rng.random() < p['gap_chance']:  # a cross aisle
                y += rng.uniform(1.6, 2.4)
                continue
            front, back = sgn * aisle, sgn * (aisle + depth)
            x0, x1 = min(front, back), max(front, back)
            bodies.add(x0, x1, y, y + rack_w - .015, 0, rack_h)
            z = .12
            while z < rack_h - .12:
                unit = rng.choice((1, 1, 1, 2, 2, 4)) * .0445
                if rng.random() < p['fill']:
                    proud = sgn * (aisle - .012), sgn * aisle
                    target = vents if unit > .09 else panels
                    target.add(min(proud), max(proud), y + .025, y + rack_w - .04, z + .003, z + unit - .003)
                    lx = sgn * (aisle - .016), sgn * (aisle - .011)
                    for _ in range(rng.randint(1, 4)):
                        ly = y + .05 + rng.random() * (rack_w - .14)
                        bank = leds_a if rng.random() < p['led_mix'] else leds_b
                        bank.add(min(lx), max(lx), ly, ly + .011, z + unit * .45, z + unit * .45 + .007)
                    if rng.random() < .06:
                        strips.add(min(lx), max(lx), y + .05, y + rack_w - .1, z + unit * .3, z + unit * .3 + .004)
                z += unit
            y += rack_w
        trays.add(sgn * (aisle + .25) - .2, sgn * (aisle + .25) + .2, -2, length, 2.62, 2.7)
        trays.add(sgn * (aisle + .75) - .12, sgn * (aisle + .75) + .12, -2, length, 2.85, 2.9)

    bodies.build('racks', principled_material('rack', pal['rack'], .55, .38), bevel=.006)
    panels.build('server faces', principled_material('server', pal['panel'], .4, .3), bevel=.002)
    vent_material, graph, output = new_material('vent')
    geometry = graph.new('ShaderNodeNewGeometry')
    holes = graph.new('ShaderNodeTexBrick', Scale=60.0, offset=.5, **{'Mortar Size': .35, 'Brick Width': .5,
                      'Row Height': .25})
    graph.link(geometry.outputs['Position'], holes.inputs['Vector'])
    colour = graph.ramp(holes.outputs['Fac'], [(0.0, lin(pal['panel'])), (1.0, lin('#020203'))])
    bsdf = principled(graph, Metallic=.5, Roughness=.35)
    graph.link(colour, bsdf.inputs['Base Color'])
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    vents.build('vented units', vent_material, bevel=.002)
    leds_a.build('leds a', emission_material('led a', pal['led_a'], pal['led_strength']))
    leds_b.build('leds b', emission_material('led b', pal['led_b'], pal['led_strength'] * .8))
    strips.build('status strips', emission_material('strip', pal['led_a'], pal['led_strength'] * .5))
    trays.build('cable trays', principled_material('tray', '#2A2E35', .8, .45), bevel=.01)

    floor_material, graph, output = new_material('floor')
    geometry = graph.new('ShaderNodeNewGeometry')
    tiles = graph.new('ShaderNodeTexBrick', Scale=1.66, offset=0.0, **{'Mortar Size': .01, 'Brick Width': 1.0,
                      'Row Height': .5, 'Color1': lin(pal['floor']), 'Color2': lin(pal['floor']),
                      'Mortar': lin('#050506')})
    graph.link(geometry.outputs['Position'], tiles.inputs['Vector'])
    bsdf = principled(graph, Metallic=.0, Roughness=p['floor_roughness'])
    graph.link(tiles.outputs['Color'], bsdf.inputs['Base Color'])
    graph.link(bsdf.outputs[0], output.inputs['Surface'])
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, length / 2, 0))
    floor = bpy.context.object
    floor.scale = (30, length + 8, 1)
    floor.data.materials.append(floor_material)
    ceiling = Boxes()
    ceiling.add(-15, 15, -4, length + 2, 3.2, 3.25)
    ceiling.add(-15, 15, length + 1.5, length + 2, 0, 3.2)  # end wall
    ceiling.build('ceiling', principled_material('ceiling', '#08090B', 0, .8))

    haze, graph, output = new_material('haze')
    volume = graph.new('ShaderNodeVolumePrincipled', Density=p['haze'], Anisotropy=.55)
    volume.inputs['Color'].default_value = lin(pal['haze'])
    graph.link(volume.outputs[0], output.inputs['Volume'])
    room = Boxes()
    room.add(-aisle - .02, aisle + .02, -3, length + 1, .01, 3.15)
    room.build('haze', haze)

    for k, y in enumerate(p['shafts']):
        data = bpy.data.lights.new(f'shaft {k}', 'SPOT')
        data.energy = p['shaft_energy']
        data.spot_size = math.radians(28)
        data.spot_blend = .6
        data.shadow_soft_size = .05
        data.color = lin(pal['shaft'])[:3]
        light = link_object(f'shaft {k}', data)
        light.location = (side * rng.uniform(-.3, .3), y, 3.1)
        light.rotation_euler = (0, 0, 0)
    area_light('far glow', (0, length + .5, 1.4), (0, 0, 1.2), p['shaft_energy'] * .25, 2.0, pal['shaft'])
    area_light('aisle fill', (0, -1.0, 2.9), (0, 8.0, 1.2), p['shaft_energy'] * .5, 2.5, pal['shaft'])

    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = p['focus']
    camera.data.dof.aperture_fstop = 1.0
    glow(threshold=1.0, size=7, mix=-.55)
    return dict(racks=len(bodies.verts) // 8, leds=(len(leds_a.verts) + len(leds_b.verts)) // 8)


def fibre_optics(p, rng):
    """Bundles of optical fibre sweeping up from out of frame and fanning out,
    each strand ending in a point of light, against a deep-space backdrop."""
    pal = p['palette']
    side = p['side']
    camera = make_camera((0, 0, 0), (0, 10, 0), lens=50, roll=p['roll'])
    space_world(p, star_amount=.35, nebula_amount=.6)
    curve = bpy.data.curves.new('fibres', 'CURVE')
    curve.dimensions = '3D'
    curve.bevel_depth = .0016
    curve.bevel_resolution = 1
    tips = []
    for b, (sgn, share) in enumerate(((side, 1.0), (-side, p['second_share']))):
        if share <= 0:
            continue
        base = screen_to_world(camera, .5 + sgn * p['base_u'], -.25, 7.0)
        centre_u, centre_v = .5 + sgn * p['fan_u'], p['fan_v']
        count = int(p['fibres'] * share)
        made = 0
        tries = 0
        while made < count and tries < count * 30:
            tries += 1
            u = centre_u + rng.gauss(0, p['spread'] * .9)
            v = centre_v + rng.gauss(0, p['spread'] * .7)
            if float(interest(u, v, 0.0)) < .2 or not (0 <= u <= 1 and v <= 1.04):
                continue
            depth = rng.uniform(5.0, 9.0)
            tip = screen_to_world(camera, u, v, depth)
            start = base + Vector((rng.gauss(0, .05), rng.gauss(0, .05), rng.gauss(0, .05)))
            c1 = start + Vector((0, 0, 1.0)) * (tip - start).length * .45 + Vector((0, rng.gauss(0, .1), 0))
            c2 = tip - (tip - start).normalized() * .6 + Vector((0, 0, -.8))
            spline = curve.splines.new('POLY')
            steps = 28
            spline.points.add(steps)
            for i in range(steps + 1):
                t = i / steps
                q = (1 - t) ** 3 * start + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * tip
                spline.points[i].co = (q.x, q.y, q.z, 1)
            tips.append((tip, (tip - c2).normalized()))
            made += 1
    material, graph, output = new_material('fibre')
    geometry = graph.new('ShaderNodeNewGeometry')
    height = graph.new('ShaderNodeSeparateXYZ')
    graph.link(geometry.outputs['Position'], height.inputs[0])
    top = max(t.z for t, _ in tips) if tips else 1.0
    bottom = min(t.z for t, _ in tips) - 4.0 if tips else -3.0
    rise = graph.new('ShaderNodeMapRange', **{'From Min': bottom, 'From Max': top, 'To Min': 0.0, 'To Max': 1.0})
    graph.link(height.outputs['Z'], rise.inputs['Value'])
    colour = graph.ramp(rise.outputs[0], [(0.0, lin(pal['fibre_low'])), (1.0, lin(pal['fibre_high']))])
    emission = graph.new('ShaderNodeEmission')
    graph.link(colour, emission.inputs['Color'])
    graph.link(graph.math('MULTIPLY', graph.math('POWER', rise.outputs[0], 3.0), pal['fibre_strength']),
               emission.inputs['Strength'])
    glass = principled(graph, **{'Base Color': lin('#0A0C12'), 'Roughness': .2, 'Metallic': .3})
    mix = graph.new('ShaderNodeAddShader')
    graph.link(emission.outputs[0], mix.inputs[0])
    graph.link(glass.outputs[0], mix.inputs[1])
    graph.link(mix.outputs[0], output.inputs['Surface'])
    curve.materials.append(material)
    link_object('fibres', curve)
    tip_mesh = sphere_mesh('tip', 12, 6)
    tip_mesh.materials.append(random_emission_material('tip', pal['tip_a'], pal['tip_b'], 6.0, 22.0))
    for k, (tip, _) in enumerate(tips):
        obj = link_object(f'tip {k}', tip_mesh)
        obj.location = tip
        obj.scale = (rng.uniform(.006, .011),) * 3
    area_light('rim', (side * 3, 12, 4), (0, 6, 0), 300, 4, pal['fibre_high'])
    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = p['focus']
    camera.data.dof.aperture_fstop = .55
    glow(threshold=.9, size=8, mix=-.4)
    return dict(fibres=len(tips))


def polytope_geometry(kind):
    """Vertices, edges and 2-faces of a regular 4D polytope."""
    import itertools
    phi = (1 + 5 ** .5) / 2
    if kind == '8-cell':
        verts = [Vector(v) for v in itertools.product((-1, 1), repeat=4)]
        faces = []
        for i, j in itertools.combinations(range(4), 2):
            others = [k for k in range(4) if k not in (i, j)]
            for fixed in itertools.product((-1, 1), repeat=2):
                corners = []
                for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                    v = [0] * 4
                    v[i], v[j], v[others[0]], v[others[1]] = a, b, fixed[0], fixed[1]
                    corners.append(verts.index(Vector(v)))
                faces.append(corners)
    else:
        points = set()
        if kind == '24-cell':
            for i, j in itertools.combinations(range(4), 2):
                for a, b in itertools.product((-1, 1), repeat=2):
                    v = [0.0] * 4
                    v[i], v[j] = a, b
                    points.add(tuple(v))
        elif kind == '600-cell':
            for i in range(4):
                for a in (-2.0, 2.0):
                    v = [0.0] * 4
                    v[i] = a
                    points.add(tuple(v))
            points.update(itertools.product((-1.0, 1.0), repeat=4))
            even = [q for q in itertools.permutations(range(4))
                    if sum(1 for x in range(4) for y in range(x + 1, 4) if q[x] > q[y]) % 2 == 0]
            for signs in itertools.product((-1, 1), repeat=3):
                base = (signs[0] * phi, signs[1] * 1.0, signs[2] / phi, 0.0)
                for q in even:
                    points.add(tuple(round(base[q[k]], 9) for k in range(4)))
        verts = [Vector(v) for v in sorted(points)]
        faces = None
    distances = sorted({round((a - b).length, 6) for a, b in itertools.combinations(verts, 2)})
    edge = distances[0]
    edges = [(i, j) for i, j in itertools.combinations(range(len(verts)), 2)
             if abs((verts[i] - verts[j]).length - edge) < 1e-4]
    if faces is None:
        adjacent = {i: set() for i in range(len(verts))}
        for i, j in edges:
            adjacent[i].add(j)
            adjacent[j].add(i)
        faces = [[i, j, k] for i, j in edges for k in adjacent[i] & adjacent[j] if k > j]
    radius = max(v.length for v in verts)
    return [v / radius for v in verts], edges, faces


def projected_polytope(p, rng):
    """A regular 4D polytope, turned in four dimensions and projected into 3D:
    chrome edges and thin iridescent panels, studio-lit against deep space."""
    pal = p['palette']
    side = p['side']
    camera = make_camera((0, 0, 0), (0, 10, 0), lens=40, roll=p['roll'])
    space_world(p, star_amount=.7, nebula_amount=.7)
    chrome = principled_material('chrome', pal['metal'], 1.0, .14)
    panel, graph, output = new_material('panel')
    film = principled(graph, **{'Base Color': lin(pal['panel']), 'Metallic': .0, 'Roughness': .08,
                                'Thin Film Thickness': pal['film'], 'Thin Film IOR': 1.33})
    clear = graph.new('ShaderNodeBsdfTransparent')
    mix = graph.new('ShaderNodeMixShader')
    mix.inputs['Fac'].default_value = p['panel_opacity']
    graph.link(clear.outputs[0], mix.inputs[1])
    graph.link(film.outputs[0], mix.inputs[2])
    graph.link(mix.outputs[0], output.inputs['Surface'])
    joint = sphere_mesh('joint', 16, 8)
    joint.materials.append(chrome)
    shapes = [(p['polytope'], .5 + side * p['place_u'], p['place_v'], p['size'], p['angles'])]
    if p['echo']:
        shapes.append((p['echo'], .5 - side * .36, .82, p['size'] * .42, p['echo_angles']))
    stats = {}
    for n, (kind, u, v, size, angles) in enumerate(shapes):
        verts, edges, faces = polytope_geometry(kind)
        planes = ((0, 3), (1, 3), (2, 3), (0, 1), (1, 2))
        turned = []
        for vert in verts:
            q = list(vert)
            for (a, b), angle in zip(planes, angles):
                c, s = math.cos(angle), math.sin(angle)
                q[a], q[b] = c * q[a] - s * q[b], s * q[a] + c * q[b]
            w_scale = 2.6 / (2.6 - q[3])
            turned.append(Vector((q[0], q[1], q[2])) * w_scale)
        reach = max(t.length for t in turned)
        centre = screen_to_world(camera, u, v, 12.0)
        points = [centre + t * (size / reach) for t in turned]
        tube = size * (.012 if kind == '600-cell' else .02)
        curve = bpy.data.curves.new(f'edges {n}', 'CURVE')
        curve.dimensions = '3D'
        curve.bevel_depth = tube
        curve.bevel_resolution = 3
        for i, j in edges:
            spline = curve.splines.new('POLY')
            spline.points.add(1)
            spline.points[0].co = tuple(points[i]) + (1,)
            spline.points[1].co = tuple(points[j]) + (1,)
        curve.materials.append(chrome)
        link_object(f'edges {n}', curve)
        mesh_object(f'panels {n}', [tuple(x) for x in points], faces, panel)
        for k, point in enumerate(points):
            obj = link_object(f'joint {n}.{k}', joint)
            obj.location = point
            obj.scale = (tube * 1.9,) * 3
        stats[kind] = dict(vertices=len(verts), edges=len(edges), faces=len(faces))
    target = screen_to_world(camera, .5 + side * p['place_u'], p['place_v'], 12.0)
    area_light('key', target + Vector((side * 6, -6, 6)), target, p['key_energy'], 5, pal['key'])
    area_light('rim', target + Vector((-side * 5, 8, 3)), target, p['key_energy'] * 1.4, 4, pal['rim'])
    area_light('under', target + Vector((0, -3, -7)), target, p['key_energy'] * .25, 6, pal['rim'])
    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = 12.0
    camera.data.dof.aperture_fstop = 1.4
    glow(threshold=1.1, size=7, mix=-.6)
    return stats


def value_noise(rng, shape, cells):
    """Smooth random field on a grid (bicubic-free: smoothstep-blended lattice)."""
    ny, nx = shape
    lattice = np.array([[rng.random() for _ in range(cells + 2)] for _ in range(cells + 2)])
    y = np.linspace(0, cells, ny)
    x = np.linspace(0, cells, nx)
    yy, xx = np.meshgrid(y, x, indexing='ij')
    y0, x0 = np.floor(yy).astype(int), np.floor(xx).astype(int)
    ty, tx = yy - y0, xx - x0
    ty, tx = ty * ty * (3 - 2 * ty), tx * tx * (3 - 2 * tx)
    a = lattice[y0, x0] * (1 - tx) + lattice[y0, x0 + 1] * tx
    b = lattice[y0 + 1, x0] * (1 - tx) + lattice[y0 + 1, x0 + 1] * tx
    return a * (1 - ty) + b * ty


def voxel_terrain(p, rng):
    """A landscape built from voxels: ridges of stacked cubes rise on the side
    thirds, a quiet valley runs to the horizon, data beacons glow on the peaks."""
    pal = p['palette']
    side = p['side']
    vox = .5
    nx, ny = 150, 130
    x_min, y_min = -nx * vox / 2, -4.0
    field = (value_noise(rng, (ny, nx), 6) * .6 + value_noise(rng, (ny, nx), 14) * .3
             + value_noise(rng, (ny, nx), 30) * .1)
    xs = x_min + (np.arange(nx) + .5) * vox
    ys = y_min + (np.arange(ny) + .5) * vox
    yy, xx = np.meshgrid(ys, xs, indexing='ij')
    lean = 1 + side * p['lean'] * np.tanh(xx / 12)
    valley = smoothstep(p['valley'], p['valley'] + 9, np.abs(xx - side * 1.5))
    near = smoothstep(-2, 16, yy)
    heights = (.4 + field ** 1.6 * p['relief'] * (.08 + .92 * valley) * lean * (.2 + .8 * near))
    levels = np.maximum(1, np.round(heights / vox)).astype(int)
    columns, beacons = Boxes(), Boxes()
    for j in range(ny):
        for i in range(nx):
            x0, y0 = x_min + i * vox, y_min + j * vox
            top = levels[j, i] * vox
            columns.add(x0, x0 + vox, y0, y0 + vox, 0, top)
            if levels[j, i] >= p['beacon_level'] and rng.random() < p['beacons']:
                beacons.add(x0 + .06, x0 + vox - .06, y0 + .06, y0 + vox - .06, top, top + vox * .9)
    eye = Vector((side * p['eye_x'], -6.0, p['eye_z']))
    camera = make_camera(eye, (side * p['look_x'], 36.0, p['look_z']), lens=30, roll=p['roll'])

    terrain, graph, output = new_material('voxels')
    geometry = graph.new('ShaderNodeNewGeometry')
    xyz = graph.new('ShaderNodeSeparateXYZ')
    graph.link(geometry.outputs['Position'], xyz.inputs[0])
    normal = graph.new('ShaderNodeSeparateXYZ')
    graph.link(geometry.outputs['Normal'], normal.inputs[0])
    seam = graph.math('LESS_THAN', graph.math('FRACT', graph.math('DIVIDE', xyz.outputs['Z'], vox)), .05)
    up = graph.math('GREATER_THAN', normal.outputs['Z'], .5)
    altitude = graph.new('ShaderNodeMapRange', **{'From Min': 0.0, 'From Max': p['relief'] + .5,
                                                  'To Min': 0.0, 'To Max': 1.0})
    graph.link(xyz.outputs['Z'], altitude.inputs['Value'])
    side_colour = graph.ramp(altitude.outputs[0], [(0.0, lin(pal['low'])), (1.0, lin(pal['high']))])
    top_colour = graph.ramp(altitude.outputs[0], [(0.0, lin(pal['top_low'])), (1.0, lin(pal['top_high']))])
    face = graph.new('ShaderNodeMix', data_type='RGBA')
    graph.link(up, face.inputs[0])
    graph.link(side_colour, face.inputs[6])
    graph.link(top_colour, face.inputs[7])
    seamed = graph.new('ShaderNodeMix', data_type='RGBA')
    graph.link(graph.math('MULTIPLY', seam, graph.math('SUBTRACT', 1.0, up)), seamed.inputs[0])
    graph.link(face.outputs[2], seamed.inputs[6])
    seamed.inputs[7].default_value = lin('#020203')
    bsdf = principled(graph, Roughness=.55, Metallic=.1)
    graph.link(seamed.outputs[2], bsdf.inputs['Base Color'])
    # Aerial perspective: surfaces fade into the haze colour with distance.
    distance = graph.new('ShaderNodeVectorMath', operation='DISTANCE')
    graph.link(geometry.outputs['Position'], distance.inputs[0])
    distance.inputs[1].default_value = eye
    fog = graph.math('SUBTRACT', 1.0, graph.math('EXPONENT', graph.math('MULTIPLY', distance.outputs['Value'],
                                                                        -1.0 / p['fog'])))
    haze = graph.new('ShaderNodeEmission', Color=lin(pal['fog']), Strength=pal['fog_strength'])
    mixed = graph.new('ShaderNodeMixShader')
    graph.link(fog, mixed.inputs['Fac'])
    graph.link(bsdf.outputs[0], mixed.inputs[1])
    graph.link(haze.outputs[0], mixed.inputs[2])
    graph.link(mixed.outputs[0], output.inputs['Surface'])
    columns.build('voxel columns', terrain, bevel=.025)
    beacons.build('beacons', emission_material('beacon', pal['beacon'], pal['beacon_strength']))

    world = bpy.data.worlds.new('dusk')
    world.use_nodes = True
    world.node_tree.nodes.clear()
    sky = Nodes(world.node_tree)
    out = sky.new('ShaderNodeOutputWorld')
    background = sky.new('ShaderNodeBackground', Strength=1.0)
    coords = sky.new('ShaderNodeTexCoord')
    window = sky.new('ShaderNodeSeparateXYZ')
    sky.link(coords.outputs['Window'], window.inputs[0])
    gradient = sky.ramp(window.outputs['Y'], [(p['horizon'] - .08, lin(pal['fog'])), (p['horizon'] + .12,
                        lin(pal['sky_mid'])), (1.0, lin(pal['space']))])
    sky.link(gradient, background.inputs['Color'])
    sky.link(background.outputs[0], out.inputs['Surface'])
    bpy.context.scene.world = world
    sun_data = bpy.data.lights.new('low sun', 'SUN')
    sun_data.energy = p['sun_energy']
    sun_data.angle = math.radians(2)
    sun_data.color = lin(pal['sun'])[:3]
    sun = link_object('low sun', sun_data)
    sun.rotation_euler = (-Vector((-side * .8, 1.0, .25))).to_track_quat('-Z', 'Y').to_euler()
    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = p['focus']
    camera.data.dof.aperture_fstop = .9
    glow(threshold=1.0, size=7, mix=-.6)
    return dict(columns=nx * ny, beacons=len(beacons.verts) // 8)


FAMILIES = {
    'neural-constellation': neural_constellation,
    'silicon-die': silicon_die,
    'orbital-horizon': orbital_horizon,
    'data-centre': data_centre,
    'fibre-optics': fibre_optics,
    'projected-polytope': projected_polytope,
    'voxel-terrain': voxel_terrain,
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
