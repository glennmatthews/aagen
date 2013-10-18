# aagen.geometry - module encapsulating interactions with the Shapely library.

import logging
import math
import re
import ast

from aagen.direction import Direction

from shapely.coords import CoordinateSequence
from shapely.geometry.point import Point
from shapely.geometry.linestring import LineString
from shapely.geometry.multilinestring import MultiLineString
from shapely.geometry.polygon import Polygon, LinearRing
from shapely.geometry.multipolygon import MultiPolygon
from shapely.geometry.collection import GeometryCollection
import shapely.affinity
from shapely.geometry import box
import shapely.ops
from shapely.validation import explain_validity


log = logging.getLogger(__name__)

def to_string(geometry):
    """Returns a brief (less precise) representation of a geometric object"""
    if geometry is None:
        return "<None>"
    elif hasattr(geometry, "is_empty") and geometry.is_empty:
        return "<{0} (empty)>".format(type(geometry).__name__)
    elif isinstance(geometry, Point):
        return "<Point ({0}, {1})>".format(numstr(geometry.x),
                                           numstr(geometry.y))
    elif isinstance(geometry, LineString):
        coords = geometry.coords
    elif isinstance(geometry, Polygon):
        coords = geometry.exterior.coords
    elif (isinstance(geometry, MultiLineString) or
          isinstance(geometry, MultiPolygon) or
          isinstance(geometry, GeometryCollection)):
        return "<{0} ({1})>".format(type(geometry).__name__,
                                    ", ".join([to_string(g) for
                                               g in geometry.geoms]))
    elif isinstance(geometry, CoordinateSequence):
        coords = list(geometry)
    elif type(geometry) is list or type(geometry) is tuple:
        coords = geometry
    else:
        raise RuntimeError("to_string: unknown object type {0}"
                           .format(geometry))

    str_list = []
    for (x, y) in coords:
        str_list.append("({0}, {1})".format(numstr(x), numstr(y)))
    return "<{0}: [{1}]>".format(type(geometry).__name__,
                              ", ".join(str_list))


def from_string(string):
    """Convert a string representation back to a list of coordinates"""
    string = string.lstrip("<").rstrip(">")
    (kind, coords_str) = string.split(":")
    coords = ast.literal_eval(coords_str.strip())
    return globals()[kind](coords)


def bounds_str(geometry):
    """Returns a brief representation of the bounding box of an object"""
    return ("({0})".format(", ".join([numstr(x) for x in geometry.bounds])))


def numstr(value):
    """Converts a number to a string with no trailing zeros"""
    return ('%0.2f' % value).rstrip('0').rstrip('.')



# Geometric manipulation

def translate(shape, dx, dy):
    """Translate the given shape by the given (dx, dy) and return the
    resulting new shape.
    """
    return shapely.affinity.translate(shape, dx, dy)


def rotate(geometry, angle):
    """Rotate the given geometry, vector, or list of points by the given angle,
    which can be given in degrees, as a Direction, or as a vector (where east
    or (1,0) is an angle of 0 degrees).
    """

    if type(geometry) is tuple:
        # (x, y) - box and unbox it as a list of one point
        return rotate([geometry], angle)[0]
    if isinstance(angle, Direction):
        return rotate(geometry, angle.vector)

    if type(angle) is tuple:
        radians = math.atan2(angle[1], angle[0])
        degrees = math.degrees(radians)
    else:
        degrees = angle
        radians = math.radians(degrees)

    if type(geometry) is list or type(geometry) is tuple:
        output = []
        for (x0, y0) in geometry:
            (x1, y1) = (x0 * math.cos(radians) - y0 * math.sin(radians),
                        x0 * math.sin(radians) + y0 * math.cos(radians))
            log.debug("({0}, {1}) rotated by {2} degrees is ({3}, {4})"
                      .format(x0, y0, degrees, x1, y1))
            output.append((x1, y1))
        return output
    else:
        return shapely.affinity.rotate(geometry, degrees)


# Geometric construction

def sweep(line, dir, distance, base_dir=None, width=None, fixup=False):
    """Sweep the given line in the given direction for the given distance.
    Returns the tuple (polygon, new_line) where polygon is the polygon defined
    by the swept line, and new_line is the final line position.

    If fixup is set to true, will do any intermediate work needed to fix the
    given line to the appropriate grid line before sweeping.
    """
    assert isinstance(dir, Direction)
    (dx, dy) = dir.vector

    # line can be a LineString object or simply a list of coords
    if isinstance(line, LineString):
        line1 = line
    else:
        line1 = LineString(line)

    poly1 = None
    if fixup:
        line_poly_list = sweep_corner(line1, base_dir, width, dir)
        (poly1, line1) = line_poly_list[0] # TODO

    line2 = shapely.affinity.translate(line1,
                                       round(dx * distance, -1),
                                       round(dy * distance, -1))

    poly2 = loft([line1, line2])
    if poly1 is not None:
        poly2 = poly2.union(poly1)

    log.debug("Swept polygon from {0} in {1} by {2}: {3}"
              .format(to_string(line1), (dx, dy), distance,
                      to_string(poly2)))
    return (poly2, line2)


def sweep_corner(line, old_dir, width, new_dir):
    """Constructs a polygon representing the work needing to be done to
    connect the given line, last swept in the given "old" direction, to a
    grid-constrained, cardinally-oriented line perpendicular to the given
    "new" direction. (If the new direction is a diagonal, then either of its
    cardinal components will be chosen as the target orientation).

    Can be used to fix up non-grid-constrained lines (such as an entrance/exit
    from an unusually-shaped room) as well as to construct corners and
    intersections.

    Returns a list of 1-2 (polygon, end_line) pairs.
    """
    assert (isinstance(old_dir, Direction) and
            isinstance(new_dir, Direction))

    log.info("Sweeping corner for {0} from {1} to {2}"
             .format(to_string(line), old_dir, new_dir))

    (x0, y0, x1, y1) = line.bounds

    new_lines = []
    if old_dir.name == new_dir.name:
        if old_dir.is_cardinal():
            # Sweeping from cardinal direction to same cardinal direction
            # Just fix up to the grid.
            if old_dir.name == "north":
                line1 = LineString([(x0, math.ceil(y1/10) * 10),
                                    (x1, math.ceil(y1/10) * 10)])
            elif old_dir.name == "west":
                line1 = LineString([(math.floor(x0/10) * 10, y0),
                                    (math.floor(x0/10) * 10, y1)])
            elif old_dir.name == "south":
                line1 = LineString([(x0, math.floor(y0/10) * 10),
                                    (x1, math.floor(y0/10) * 10)])
            elif old_dir.name == "east":
                line1 = LineString([(math.ceil(x1/10) * 10, y0),
                                    (math.ceil(x1/10) * 10, y1)])

            poly = loft([line, line1])
            log.info("Swept {0} from {1} to {2} resulting in {3}"
                     .format(to_string(line), old_dir, new_dir,
                             to_string(poly)))
            return [(poly, line1)]

        else:
            # Sweeping from diagonal direction to same diagonal direction.
            # In this case we are actually sweeping to either of the cardinal
            # components of this direction, so long as they have the correct
            # size:
            candidates = []
            for possible_dir in [new_dir.rotate(-45), new_dir.rotate(45)]:
                if (possible_dir.name == "west" or
                    possible_dir.name == "east"):
                    if (y1 - y0) >= (x1 - x0):
                        log.debug("Reorienting new_dir to {0}"
                                  .format(possible_dir))
                        candidates += sweep_corner(line, old_dir,
                                                   width, possible_dir)
                    else:
                        log.debug("Not sweeping to the {0}, height is too small"
                                  .format(possible_dir))
                else:
                    if (x1 - x0) >= (y1 - y0):
                        log.debug("Reorienting new_dir to {0}"
                                  .format(possible_dir))
                        candidates += sweep_corner(line, old_dir,
                                                   width, possible_dir)
                    else:
                        log.debug("Not sweeping to the {0}, width is too small"
                                  .format(possible_dir))
            return candidates
    elif old_dir.is_cardinal() and new_dir.angle_from(old_dir) <= 45:
        # Sweeping a diagonal from a component cardinal - stay cardinal
        log.debug("Reorienting new_dir to {0}".format(old_dir))
        return sweep_corner(line, old_dir, width, old_dir)
    elif new_dir.is_cardinal() and old_dir.angle_from(new_dir) <= 45:
        # Sweeping a component cardinal from a diagonal - become cardinal
        # Since the old direction was a diagonal, we need to check whether the
        # line itself was diagonal, or whether it had already been cardinally
        # oriented.
        (line_w, line_h) = (x1 - x0, y1 - y0)
        if ((new_dir.vector[0] == 0 and line_w > 0) or
            (new_dir.vector[1] == 0 and line_h > 0)):
            #  old = NE,
            #  new = E
            #  |            |
            #  |     ==>    |
            #  |            |
            #
            #  old = NE,
            #  new = E
            #  \         \--|
            #   \    ==>  \ |
            #    \         \|
            #
            # We're already semi-correctly oriented, so...
            log.debug("Reorienting old_dir to {0}".format(new_dir))
            return sweep_corner(line, new_dir, width, new_dir)
        else:
            #
            #  old = NE,
            #  new = E     /|
            #        ==>  / |
            #  ---        ---
            #
            log.debug("Need to pivot 90 degrees...")
            # Snap to grid if not already there...
            [(poly1, line1)] = sweep_corner(line, old_dir, width, old_dir)
            (new_x0, new_y0, new_x1, new_y1) = line1.bounds
            # The component by which the directions differ...
            different_component = old_dir.name.replace(new_dir.name, "")
            if new_dir.name == "east":
                new_x0 = new_x1
            elif new_dir.name == "west":
                new_x1 = new_x0
            elif different_component == "east":
                new_x0 = new_x1
                new_x1 = new_x0 + width
            elif different_component == "west":
                new_x1 = new_x0
                new_x0 = new_x1 - width

            if new_dir.name == "north":
                new_y0 = new_y1
            elif new_dir.name == "south":
                new_y1 = new_y0
            elif different_component == "north":
                new_y0 = new_y1
                new_y1 = new_y0 + width
            elif different_component == "south":
                new_y1 = new_y0
                new_y0 = new_y1 - width

            new_line = LineString([(new_x0, new_y0), (new_x1, new_y1)])
            poly = loft([line1, new_line])
            return [(poly1.union(poly), new_line)]
    else:
        # The two directions are at least 90 degrees apart.
        # We'll need to sweep more than once...
        if old_dir.is_cardinal():
            # Snap to grid
            [(poly1, line1)] = sweep_corner(line, old_dir, width, old_dir)
            # Extrude to form the corner
            (poly2, throwaway) = sweep(line1, old_dir, width)
            (x0, y0, x1, y1) = poly2.bounds
            if (re.search("north", new_dir.name) and
                old_dir.name != "south"):
                line2 = LineString(((x0, y1), (x1, y1)))
            elif (re.search("west", new_dir.name) and
                  old_dir.name != "east"):
                line2 = LineString(((x0, y0), (x0, y1)))
            elif (re.search("south", new_dir.name) and
                  old_dir.name != "north"):
                line2 = LineString(((x0, y0), (x1, y0)))
            elif (re.search("east", new_dir.name) and
                  old_dir.name != "west"):
                line2 = LineString(((x1, y0), (x1, y1)))
            else:
                raise RuntimeError("Don't know how to sweep {0} from {1}"
                                   .format(new_dir, old_dir))
        else:
            (left, right) = (old_dir.rotate(45), old_dir.rotate(-45))
            log.info("Deciding whether to sweep from {0} to {1} or {2}"
                     .format(old_dir, left, right))
            if left.angle_from(new_dir) < right.angle_from(new_dir):
                mid_dir = left
            else:
                mid_dir = right
            [(poly1, line1)] = sweep_corner(line, old_dir, width, mid_dir)
            [(poly2, line2)] = sweep_corner(line1, mid_dir, width, new_dir)

        log.info("line1 {0}, poly1 {1}, line2 {2}, poly2 {3}"
                 .format(to_string(line1), to_string(poly1),
                         to_string(line2), to_string(poly2)))
        return [(poly2.union(poly1), line2)]


def loft(lines):
    """Construct a polygon from the given linear cross-sections.
       ----               ----_
      /                  /     -_
                  --->   \       -
          -----           \  -----
         /                 \/
    """
    line1 = lines.pop(0)
    assert line1.length > 0
    poly_set = set()
    while len(lines) > 0:
        line2 = lines.pop(0)
        assert line2.length > 0
        if line1.crosses(line2):
            raise RuntimeError("line1 {0} crosses line2 {1} at {2}, "
                               "unable to loft!"
                               .format(to_string(line1), to_string(line2),
                                       to_string(line1.intersection(line2))))
        log.debug("Constructing a polygon between {0} and {1}"
                  .format(to_string(line1), to_string(line2)))
        poly = None
        # Degenerate cases first
        if line1.contains(line2):
            poly = line1
        elif line2.contains(line1):
            poly = line2
        elif line1.boundary.intersects(line2.boundary):
            log.debug("The two lines share an endpoint - merging them")
            poly1 = Polygon(shapely.ops.linemerge([line1, line2]))
            if poly1.is_valid:
                poly = poly1

        if poly is None:
            poly1 = (Polygon(list(line1.coords) + list(reversed(line2.coords))))
            if poly1.is_valid:
                poly = poly1

        if poly is None:
            poly1 = (Polygon(list(line1.coords) + list(line2.coords)))
            if poly1.is_valid:
                poly = poly1

        if poly is None:
            log.warning("Unable to loft intuitively between {0} and {1}"
                        .format(to_string(line1), to_string(line2)))
            poly1 = line1.union(line2).convex_hull
            if poly1.is_valid:
                poly = poly1

        log.debug("Constructed {0}".format(to_string(poly)))
        if poly is not None:
            poly_set.add(poly)
        line1 = line2

    return shapely.ops.cascaded_union(poly_set)


def trim(shape, trimmer, adjacent_shape):
    """Trims the given 'shape' until it is a single continuous region that
    does not overlap 'trimmer'. If a simple difference operation between 'shape'
    and 'trimmer' would result in multiple disconnected fragments, keep
    the fragment (if any) that will remain adjacent to 'adjacent_shape'.
    """
    if not (isinstance(shape, Polygon) or
            isinstance(shape, MultiPolygon) or
            isinstance(shape, GeometryCollection)):
        raise TypeError("shape is {0}".format(type(shape)))

    log.debug("Trimming {0} with {1}, adjacent to {2}"
              .format(to_string(shape), to_string(trimmer),
                      to_string(adjacent_shape)))

    difference = differ(shape, trimmer)
    log.debug("Difference is {0}".format(to_string(difference)))

    match = None
    # Handle the case where the polygon was split by existing geometry:
    if (type(difference) is GeometryCollection or
        type(difference) is MultiPolygon):
        log.debug("Trimming shape split it into {0} pieces"
                  .format(len(difference.geoms)))
        for geom in difference.geoms:
            if type(geom) is Polygon:
                if geom.intersects(adjacent_shape):
                    match = geom
                    break
    elif type(difference) is Polygon:
        if difference.intersects(adjacent_shape):
            match = difference

    if match is not None:
        log.debug("Trimmed shape to fit")
        # TODO? force all coordinates in match to snap to 1' grid
    else:
        log.debug("After trimming, shape is nonexistent")

    return match


def minimize_line(base_line, validator):
    """Trim the given line from both ends to the minimal line(s) that
    satisfy the given validator function. Returns a set of 1 or 2
    lines that satisfy this criteria.

    For example:

    Given the line below and a validator that enforces a minimum width of 3:
      .--              ---
      |
      |        --->
      '--              ---

    Given the same line and a validator that enforces a minimum height of 4:
      .--              |
      |                |
      |        --->    |
      '--              |
    """

    # First line: delete from end, then from beginning
    coords = list(base_line.coords)
    while (len(coords) > 2):
        tmp_line = line(coords[:-1])
        if not validator(tmp_line):
            break
        coords = coords[:-1]
    while (len(coords) > 2):
        tmp_line = line(coords[1:])
        if not validator(tmp_line):
            break
        coords = coords[1:]
    line1 = line(coords)

    # Second line: delete from beginning, then from end
    coords = list(base_line.coords)
    while (len(coords) > 2):
        tmp_line = line(coords[1:])
        if not validator(tmp_line):
            break
        coords = coords[1:]
    while (len(coords) > 2):
        tmp_line = line(coords[:-1])
        if not validator(tmp_line):
            break
        coords = coords[:-1]
    line2 = line(coords)

    log.debug("Minimized line {0} to {1} and {2}"
              .format(to_string(base_line), to_string(line1), to_string(line2)))
    return [line1, line2]


# Polygon construction functions

def point(x, y):
    """Represent a point"""
    return Point(x, y)


def line(coords):
    """Construct a line segment from the given coordinate sequence.
    """
    if isinstance(coords, LineString):
        line = coords
    else:
        line = LineString(coords)
    assert line.is_valid
    return line


def line_loop(coords):
    """Constructs a linear loop from the given coordinate sequence
    (implicitly connecting end and start if needed).
    """
    loop = LinearRing(coords)
    assert loop.is_valid
    return loop


def polygon(coords):
    """Construct a polygon from the given coordinate sequence.
    """
    if isinstance(coords, Polygon):
        poly = coords
    else:
        poly = Polygon(coords)
    assert poly.is_valid
    return poly


def lines_to_coords(lines):
    """Convert the given line or group of lines to a list of
    lists of coordinates.
    """
    coords_list = []
    if lines.is_empty:
        log.info("No points in lines {0}".format(to_string(lines)))
    elif isinstance(lines, LineString):
        coords_list.append(list(lines.coords))
    elif isinstance(lines, MultiLineString):
        for geom in lines.geoms:
            coords_list.append(list(geom.coords))
    else:
        raise RuntimeError("Unexpected shape {0}".format(to_string(lines)))
    log.debug("{0} has coords: {1}".format(to_string(lines), coords_list))
    return coords_list


def box(xmin, ymin, xmax, ymax):
    """Construct a rectangle within the given bounds"""
    return shapely.geometry.box(xmin, ymin, xmax, ymax)


def rectangle_list(width, height):
    """Construct a list of 2 (for rectangles) or 1 (for squares) rectangles
    constrained to the grid with the given width and height.
    """

    rect = polygon([(0, 0), (width, 0), (width, height), (0, height)])
    rect_list = [rect]
    if width != height:
        rect = shapely.affinity.rotate(rect, 90, origin=(0,0))
        rect_list.append(rect)

    return rect_list


def circle(area):
    """Construct an approximately circular polygon constrained to the grid
    but with approximately the requested area.
    """
    radius = math.sqrt(area / math.pi)
    log.info("Exact radius would be {0}".format(radius))
    # Round to the nearest multiple of 5 feet
    radius = 5 * round(radius/5, 0)
    log.info("Rounded radius to {0}".format(radius))
    if radius % 10 == 0:
        # For even radius, center around a grid intersection
        circle = Point(0, 0).buffer(radius - 0.1)
    else:
        # For odd radius, center around a grid square
        circle = Point(5, 5).buffer(radius - 0.1)

    return circle


def circle_list(area):
    return [circle(area)]


def isosceles_right_triangle(area):
    """Construct an isosceles right triangle constrained to the grid but
    with approximately the requested area.
    """
    ideal_size = math.sqrt(area * 2)
    log.info("Ideal size would be {0}".format(ideal_size))
    size = round(ideal_size, -1)
    log.info("Rounded size to {0}".format(size))

    return polygon([(0, 0), (size, 0), (0, size)])


def triangle_list(area):
    """Returns the list of possible right triangles (each orientation)
    with approximately the requested area.
    """

    triangle = isosceles_right_triangle(area)
    return [triangle,
            shapely.affinity.rotate(triangle, 90),
            shapely.affinity.rotate(triangle, 180),
            shapely.affinity.rotate(triangle, 270)]


def trapezoid_list(area):
    """Returns a list of possible trapezoids (various height/width ratios,
    various orientations) with approximately the requested area.

    We support two kinds of trapezoids:
    |---\            /--\
    |    \    and   /    \
    |-----\        /------\
    both with nice 45 degree angles.

    In theory, these can vary widely in their aspect ratio:
    w=10         h=10
    |-\          |----\
    |  \     vs. |-----\
    |   \
    |----\

    To keep the number of permutations reasonable, we will only consider
    variants where the ratio of width to height is "pleasing".
    This ratio is very much arbitrary and hand-tuned.
    """

    trapezoids = []
    for h in range(int(10 * math.ceil(math.sqrt(area/2) / 10)),
                   int(10 * math.ceil(math.sqrt(area * 3/2) / 10)), 10):
        w1 = round((area / h) - (h / 2), -1)
        w2 = round((area / h) - h, -1)
        log.info("Candidates: one-sided {w1} x {h}, two-sided {w2} x {h}"
                 .format(w1=w1, w2=w2, h=h))
        # w1 is larger than w2, so if it's too small we know we're done
        if w1 < 10:
            break
        if w1 >= 10:
            # one-sided trapezoid - 8 possible orientations
            trapezoid = polygon([(0, 0), (w1, 0), (w1 + h, h), (0, h)])
            trapezoids.append(trapezoid)
            trapezoids.append(shapely.affinity.rotate(trapezoid, 90,
                                                      origin=(0, 0)))
            trapezoids.append(shapely.affinity.rotate(trapezoid, 180,
                                                      origin=(0, 0)))
            trapezoids.append(shapely.affinity.rotate(trapezoid, 270,
                                                      origin=(0, 0)))
            trapezoid = shapely.affinity.scale(trapezoid, xfact=-1.0)
            trapezoids.append(trapezoid)
            trapezoids.append(shapely.affinity.rotate(trapezoid, 90,
                                                      origin=(0, 0)))
            trapezoids.append(shapely.affinity.rotate(trapezoid, 180,
                                                      origin=(0, 0)))
            trapezoids.append(shapely.affinity.rotate(trapezoid, 270,
                                                      origin=(0, 0)))
        if w2 >= 10:
            # two-sided trapezoid - 4 possible orientations
            trapezoid = polygon([(0, 0), (h + w2 + h, 0), (h + w2, h), (h, h)])
            trapezoids.append(trapezoid)
            trapezoids.append(shapely.affinity.rotate(trapezoid, 90,
                                                      origin=(0, 0)))
            trapezoids.append(shapely.affinity.rotate(trapezoid, 180,
                                                      origin=(0, 0)))
            trapezoids.append(shapely.affinity.rotate(trapezoid, 270,
                                                      origin=(0, 0)))

    return trapezoids


def oval_list(area):
    """Construct a list of ovals (actually, capsule shapes) that are
    grid-constrained but have approximately the requested area.
    """
    # Ovals are a pain to calculate and not likely to fit nicely into
    # a map in any case. Instead, we'll construct a capsule-shaped room:
    #  -------
    # /       \
    #|         |
    # \       /
    #  -------
    #
    # The area of such a room is w * h + pi * (h/2)^2
    # or area = h * (w + (pi/4 * h))
    #    area ~= h * (w + 0.75h)
    #    area / h ~= w + 0.75h
    #    w ~= area / h - 0.75h
    #
    # For w = h, area = 5/4 pi * h^2 ~= 4 h^2
    # For h = 10, w ~= area/10 - 10
    # For w = 10, area ~= a circle
    ovals = []
    for h in range(int(10 * math.ceil(math.sqrt(area/4) / 10)),
                   int(10 * math.ceil(math.sqrt(area) / 10)),
                   10):
        w = round(area / h - ((math.pi / 4) * h), -1)
        log.info("Candidate: {w} x {h}".format(w=w, h=h))
        if h % 20 == 0:
            offset = 0
        else:
            offset = 5
        line = LineString([(offset, offset), (offset, w + offset)])
        oval = line.buffer(h/2)
        ovals.append(oval)
        ovals.append(shapely.affinity.rotate(oval, 90, origin=(0,0)))

    return ovals


def hexagon_list(area):
    """Construct a list of hexagons that are grid-constrained but have
    approximately the requested area.

    Note that these "hexagons" have 45-degree angles only, and may vary in their
    width-to-height ratio:
     ---        ------          /\
    /   \      /      \        |  |
    \   /      \      /        |  |
     ---        ------          \/

    The range of w/h ratios generated is arbitrary and hand-tuned
    to generate visually pleasing results.
    """
    # We start with a rectangle of size w*h then add triangles of size
    # h/2*h to either side, so the overall area is (w*h + 2 (1/2 * h * h/2))
    # = w * h + h^2/2. Just like the "one-sided" trapezoid above...
    hexagons = []
    for h in range(int(10 * math.ceil(math.sqrt(area * 2/3) / 10)),
                   int(10 * math.ceil(math.sqrt(area * 3/2) / 10)), 10):
        w = round((area / h) - (h / 2), -1)
        log.debug("Constructing hexagon with width {w} and height {h}"
                  .format(w=w, h=h))
        if w < 10:
            break
        if h % 20 == 0:
            offset = 0
        else:
            offset = 5
        hexagon = polygon([(h/2 + offset, 0), (offset, h/2),
                           (h/2 + offset, h), (h/2 + w + offset, h),
                           (h + w + offset, h/2), (h/2 + w + offset, 0)])
        hexagons.append(hexagon)
        hexagons.append(shapely.affinity.rotate(hexagon, 90, origin=(0, 0)))

    return hexagons


def octagon_list(area):
    """Construct a list of octagons that are grid-constrained but have
    approximately the requested area.

    An "octagon" can potentially vary anywhere from:
    /---\        /-\
    |   |       /   \
    |   |   to  |   |
    |   |       \   /
    \---/        \-/
    For now we try to construct a reasonably "ideal" octagon
    only, but we could consider more variants later... TODO?
    """
    sq_area = area * 9 / 7
    sq_size = math.sqrt(sq_area)
    size = round(sq_size, -1)
    log.info("Ideal size would be {0}, rounded to {1}"
             .format(sq_size, size))
    corner_offset = 10 * math.floor(size / 30)
    octagon = polygon([(0, corner_offset), (0, size - corner_offset),
                       (corner_offset, size), (size - corner_offset, size),
                       (size, size - corner_offset), (size, corner_offset),
                       (size - corner_offset, 0), (corner_offset, 0)])

    return [octagon]


# Geometric interaction

def union(*args):
    """Union the provided shapes and clean up the result as needed.
    """
    union = shapely.ops.cascaded_union(*args)
    # TODO, any cleanup?
    return union

def intersect(geometry_1, geometry_2):
    """Intersect the two given shapes and clean up the result as needed.
    """

    intersection = geometry_1.intersection(geometry_2)
    log.debug("Naive intersection is {0}".format(to_string(intersection)))

    if intersection.area == 0 and intersection.length > 0:
        # Intersection is a line segment(s)
        # These are sometimes fragmented unnecessarily into multiple
        # pieces (points and/or linestrings). Try to reunite them
        # using linemerge()
        if hasattr(intersection, "geoms"):
            line_list = []
            for geom in intersection.geoms:
                # Linemerge doesn't like points, so only try to
                # merge line segments
                if geom.length > 0:
                    line_list.append(geom)
            intersection = shapely.ops.linemerge(line_list)
    log.debug("Cleaned up intersection is {0}".format(to_string(intersection)))
    return intersection


def differ(geometry_1, geometry_2):
    """Take the difference of the two given shapes and clean up
    the result as needed.
    """

    difference = geometry_1.difference(geometry_2)
    log.debug("Naive difference is {0}".format(to_string(difference)))

    if difference.area > 0 and not difference.is_valid:
        # The resulting polygon may be overly complex - simplify it
        # if we can.
        difference = difference.buffer(0)

    log.debug("Cleaned up difference is {0}".format(to_string(difference)))
    assert difference.is_valid
    return difference
