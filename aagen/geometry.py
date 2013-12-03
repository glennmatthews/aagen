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
    elif hasattr(geometry, "geoms"):
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


def length(line):
    """Returns the Manhattan length of the given line segment.
    """
    (point1, point2) = list(line.boundary)
    return (math.fabs(point1.x - point2.x) + math.fabs(point1.y - point2.y))


def grid_aligned(line, direction):
    """Returns whether the given line's endpoints are properly grid-constrained.
    """
    if (Direction.normal_to(line) != direction and
        Direction.normal_to(line) != direction.rotate(180)):
        return False
    (p1, p2) = list(line.boundary)
    # Even in the case of 5-foot-wide passages and diagonal passages, at least
    # one endpoint must be constrained to the 10' grid to be valid
    if ((math.fmod(p1.x, 10) != 0 or math.fmod(p1.y, 10) != 0) and
        (math.fmod(p2.x, 10) != 0 or math.fmod(p2.y, 10) != 0)):
        return False
    if p1.x == p2.x or p1.y == p2.y:
        # Vertical or horizontal, promising...
        return (math.fmod(p1.x, 10) == 0 and math.fmod(p2.x, 10) == 0 and
                math.fmod(p1.y, 10) == 0 and math.fmod(p2.y, 10) == 0)
    elif math.fabs(p1.x - p2.x) == math.fabs(p1.y - p2.y):
        # 45-degree angle, promising...
        return (math.fmod(p1.x, 5) == 0 and math.fmod(p2.x, 5) == 0 and
                math.fmod(p1.y, 5) == 0 and math.fmod(p2.y, 5) == 0)
    return False


# Geometric manipulation

def translate(shape, dx_or_dir, dy_or_dist):
    """Translate the given shape by the given (dx, dy) or by
    the given (direction, distance) and return the
    resulting new shape.
    """
    if isinstance(dx_or_dir, Direction):
        dx = dx_or_dir.vector[0] * dy_or_dist
        dy = dx_or_dir.vector[1] * dy_or_dist
    else:
        dx = dx_or_dir
        dy = dy_or_dist
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
        return rotate(geometry, angle.degrees)

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

def construct_intersection(base_line, base_dir, exit_dir_list, exit_width=None):
    """Construct the polygon describing an intersection between two or more
    passages.

    If exit_width is unspecified it is assumed to be the same as the base line.
    If exit_width is specified it will be used for all exits EXCEPT any exit
    in the same direction as the base_dir (i.e., passage continuation).

    Returns (polygon, {dir1: line1, dir2: line2, ...})
    """

    # Input validation
    assert isinstance(base_dir, Direction)
    for exit_dir in exit_dir_list:
        assert isinstance(exit_dir, Direction)
    base_line = line(base_line) # just to be safe
    # Make sure the direction we were given matches the base line's orientation
    test_dir = Direction.normal_to(base_line)
    assert (test_dir.angle_from(base_dir) == 0 or
            test_dir.angle_from(base_dir) == 180)

    base_width = length(base_line)
    if exit_width is None:
        exit_width = base_width
    log.debug("base width: {0}, exit width: {1}".format(base_width, exit_width))

    # Categorize the exit directions by their relationship with the base dir
    exits_45 = []
    exits_90 = []
    exits_135 = []
    exit_fwd = None
    for exit_dir in exit_dir_list:
        if exit_dir.rotate(45) == base_dir or exit_dir.rotate(-45) == base_dir:
            exits_45.append(exit_dir)
        elif (exit_dir.rotate(90) == base_dir or
              exit_dir.rotate(-90) == base_dir):
            exits_90.append(exit_dir)
        elif (exit_dir.rotate(135) == base_dir or
              exit_dir.rotate(-135) == base_dir):
            exits_135.append(exit_dir)
        elif exit_dir == base_dir:
            exit_fwd = exit_dir
        else:
            raise RuntimeError("Unexpected angle between {0} and {1}?!"
                               .format(base_dir.name, exit_dir.name))

    new_polygon = base_line
    new_exits = {}

    # Do each in turn, if present
    for exit_135 in exits_135:
        # Calculate some related angles:
        dir_45_same = base_dir.rotate(45)
        if dir_45_same.angle_from(exit_135) == 90:
            dir_90_same = base_dir.rotate(90)
            dir_45_opp = base_dir.rotate(-45)
            dir_90_opp = base_dir.rotate(-90)
            dir_135_opp = base_dir.rotate(-135)
        else:
            dir_45_same = base_dir.rotate(-45)
            dir_90_same = base_dir.rotate(-90)
            dir_45_opp = base_dir.rotate(45)
            dir_90_opp = base_dir.rotate(90)
            dir_135_opp = base_dir.rotate(135)

        # Choose point that should be shared between baseline and this exit
        (shared_point, other_point) = endpoints_by_direction(base_line,
                                                             exit_135)

        # Construct the exit line
        new_exit_point = translate(shared_point, dir_45_same, exit_width)
        new_exits[exit_135] = line([shared_point, new_exit_point])

        base_ext_line = point_sweep(other_point, base_dir, 100)

        # If this passage has an opposing exit, construct it too
        if dir_45_opp in exits_45:
            exits_45.remove(dir_45_opp)

            # Locate the new exit points
            shared_ext_line = point_sweep(shared_point, dir_45_opp, 100)
            exit_ext_line = point_sweep(new_exit_point, dir_45_opp, 100)
            newer_exit_point1 = intersect(base_ext_line, exit_ext_line)
            inter_point = intersect(base_ext_line, shared_ext_line)
            newer_exit_point2 = translate(newer_exit_point1, dir_135_opp,
                                          exit_width)
            new_exits[dir_45_opp] = line([newer_exit_point1, newer_exit_point2])

            if base_dir in exit_dir_list:
                # Extend forward as well!
                newest_exit_point = translate(newer_exit_point1, dir_90_same,
                                              base_width)
                new_exits[base_dir] = line([newer_exit_point1,
                                            newest_exit_point])
                new_inter_point = intersect(exit_ext_line,
                                            line([shared_point,
                                                  newest_exit_point]))
                new_poly = polygon([other_point, shared_point, new_exit_point,
                                    new_inter_point, newest_exit_point,
                                    newer_exit_point1, newer_exit_point2,
                                    inter_point, other_point])
            else:
                # No passage continuation
                new_poly = polygon([other_point, shared_point, new_exit_point,
                                    newer_exit_point1, newer_exit_point2,
                                    inter_point, other_point])
        elif base_dir in exit_dir_list or (dir_45_same in exit_dir_list and not
                                           dir_135_opp in exit_dir_list):
            newer_exit_point1 = translate(new_exit_point, dir_45_opp,
                                          exit_width)
            newer_exit_point2 = translate(newer_exit_point1, dir_90_opp,
                                          base_width)
            if dir_45_same in exit_dir_list:
                exits_45.remove(dir_45_same)
                new_exits[dir_45_same] = line([new_exit_point,
                                               newer_exit_point1])
            # We may have already constructed the forward exit; if so,
            # do not overwrite it here
            if base_dir in exit_dir_list and not base_dir in new_exits.keys():
                new_exits[base_dir] = line([newer_exit_point1,
                                            newer_exit_point2])
            new_poly = polygon([other_point, shared_point, new_exit_point,
                                newer_exit_point1, newer_exit_point2,
                                other_point])
        else:
            # No other exits on this side
            # Construct the corner of the polygon
            corner_ext_line = point_sweep(new_exit_point, dir_90_opp, 100)
            corner_point = intersect(base_ext_line, corner_ext_line)
            new_poly = polygon([other_point, shared_point, new_exit_point,
                                corner_point, other_point])

        log.debug("new_poly: {0}".format(to_string(new_poly)))
        new_polygon = union(new_polygon, new_poly)

    # End handling of 135-degree turns

    for exit_90 in exits_90:
        # Easy peasy!
        (shared_point, other_point) = endpoints_by_direction(base_line, exit_90)
        exit_point = translate(shared_point, base_dir, exit_width)
        corner_point = translate(other_point, base_dir, exit_width)
        new_exits[exit_90] = line([shared_point, exit_point])
        if base_dir in exit_dir_list and not base_dir in new_exits.keys():
            new_exits[base_dir] = line([exit_point, corner_point])
        new_poly = polygon([other_point, shared_point, exit_point, corner_point,
                            other_point])
        log.debug("new_poly: {0}".format(to_string(new_poly)))
        new_polygon = union(new_polygon, new_poly)

    for exit_45 in exits_45:
        # Any 45-degree angles we didn't already handle...
        dir_45_opp = base_dir.rotate(45)
        if dir_45_opp == exit_45:
            dir_45_opp = base_dir.rotate(-45)
            dir_90_opp = base_dir.rotate(-90)
        else:
            dir_90_opp = base_dir.rotate(90)
        (shared_point, other_point) = endpoints_by_direction(base_line, exit_45)
        if base_dir in exit_dir_list:
            # Same polygon as above in exit_135:
            new_exit_point1 = translate(shared_point, exit_45, exit_width)
            new_exit_point2 = translate(new_exit_point1, dir_45_opp, exit_width)
            new_exit_point3 = translate(new_exit_point2, dir_90_opp, base_width)
            new_exits[exit_45] = line([new_exit_point1, new_exit_point2])
            if not base_dir in new_exits.keys():
                new_exits[base_dir] = line([new_exit_point2, new_exit_point3])
            new_poly = polygon([other_point, shared_point, new_exit_point1,
                                new_exit_point2, new_exit_point3])
        else:
            # Construct an initial point and some guiding lines
            new_exit_point = translate(shared_point, dir_45_opp, exit_width)
            exit_line = line([shared_point, new_exit_point])
            base_midline_ext = point_sweep(base_line.interpolate(base_width/2),
                                           base_dir, 100)
            base_diag_ext = point_sweep(base_line.interpolate(base_width/2),
                                        exit_45, 100)
            other_ext = point_sweep(other_point, base_dir, 100)
            if exit_line.touches(base_midline_ext):
                # The simplest case - just a triangle
                new_exits[exit_45] = exit_line
                new_poly = polygon([other_point, shared_point, new_exit_point])
            elif exit_line.crosses(base_midline_ext):
                if dir_45_opp in exit_dir_list or dir_90_opp in exit_dir_list:
                    # Sweep it until it no longer crosses the midline
                    temp_line = line([intersect(exit_line, base_midline_ext),
                                      new_exit_point])
                    overlap_len = length(temp_line)
                    log.debug("overlap of {0} over {1}: {2}"
                              .format(to_string(exit_line),
                                      to_string(base_midline_ext),
                                      overlap_len))
                elif exit_line.crosses(other_ext):
                    # Just sweep it until it no longer crosses the other side
                    temp_line = line([intersect(exit_line, other_ext),
                                      new_exit_point])
                    overlap_len = length(temp_line)
                    log.debug("overlap of {0} over {1}: {2}"
                              .format(to_string(exit_line),
                                      to_string(other_ext),
                                      overlap_len))
                else:
                    overlap_len = 0
                exit_line = translate(exit_line, exit_45, overlap_len)
                new_exits[exit_45] = exit_line
                # Construct the polygon
                (far_point, _) = endpoints_by_direction(exit_line, base_dir)
                far_ext = point_sweep(far_point, exit_45.rotate(180), 100)
                corner_point = intersect(other_ext, far_ext)
                new_poly = loft(line([corner_point, other_point, shared_point]),
                                exit_line)
            else:
                exit_line = translate(exit_line, base_dir,
                                      (base_width - exit_width))
                new_exits[exit_45] = exit_line
                new_poly = loft(base_line, exit_line)

        log.debug("new_poly: {0}".format(to_string(new_poly)))
        new_polygon = union(new_polygon, new_poly)


    log.info("polygon: {0}".format(to_string(new_polygon)))
    log.info("exits: {0}".format([(e_dir.name, to_string(e_line)) for
                                  (e_dir, e_line) in new_exits.items()]))

    return (new_polygon, new_exits)


def cardinal_to_diagonal(base_line, new_orientation):
    """Convert a cardinal line segment of length X to a diagonal line of
    length sqrt(2)/2 * x.
    """
    assert isinstance(new_orientation, Direction)
    base_line = line(base_line)
    base_dir = Direction.normal_to(base_line)
    if base_dir.angle_from(new_orientation) > 90:
        base_dir = base_dir.rotate(180)
    assert base_dir.is_cardinal() and not new_orientation.is_cardinal()

    log.debug("Changing base line {0} from {1} to {2}"
              .format(to_string(base_line), base_dir, new_orientation))

    (x0, y0, x1, y1) = base_line.bounds

    # Find the endpoint the new line shares with the base line
    if new_orientation.vector[0] > 0:
        xa = x1
    else:
        xa = x0
    if new_orientation.vector[1] > 0:
        ya = y1
    else:
        ya = y0
    log.debug("shared point: {0}, {1}".format(xa, ya))

    # Construct the new endpoint
    xb = (x1 - x0)/2 + (base_dir.vector[0] * (y1 - y0)/2)
    yb = (y1 - y0)/2 + (base_dir.vector[1] * (x1 - x0)/2)
    log.debug("new point: {0}, {1}".format(xb, yb))

    new_line = line([(xa, ya), (xb, yb)])
    log.debug("new line is {0}".format(to_string(new_line)))
    return new_line


def diagonal_to_cardinal(base_line, new_orientation):
    """Convert a diagonal line of length sqrt(2)/2 * X to a cardinal line
    of length X
    """
    assert isinstance(new_orientation, Direction)
    base_line = line(base_line)
    base_dir = Direction.normal_to(base_line)
    if base_dir.angle_from(new_orientation) > 90:
        base_dir = base_dir.rotate(180)
    assert not base_dir.is_cardinal() and  new_orientation.is_cardinal()

    log.debug("Changing base line {0} from {1} to {2}"
              .format(to_string(base_line), base_dir, new_orientation))

    (x0, y0, x1, y1) = base_line.bounds

    # Construct the first endpoint
    if base_dir.vector[0] > 0:
        if new_orientation.vector[0] > 0:
            xa = math.ceil(x1/10) * 10
        else:
            xa = math.ceil(x0/10) * 10
    else:
        if new_orientation.vector[0] < 0:
            xa = math.floor(x0/10) * 10
        else:
            xa = math.floor(x1/10) * 10
    if base_dir.vector[1] > 0:
        if new_orientation.vector[1] > 0:
            ya = math.ceil(y1/10) * 10
        else:
            ya = math.ceil(y0/10) * 10
    else:
        if new_orientation.vector[1] < 0:
            ya = math.floor(y0/10) * 10
        else:
            ya = math.floor(y1/10) * 10
    log.debug("first point: {0}, {1}".format(xa, ya))

    new_width = 2 * (x1 - x0) # or y1 - y0

    # Construct the second endpoint
    xb = xa + new_orientation.vector[1] * (2 * (y1 - y0))
    yb = ya + new_orientation.vector[0] * (2 * (x1 - x0))
    log.debug("second point: {0}, {1}".format(xb, yb))
    new_line = line([(xa, ya), (xb, yb)])
    log.info("new line is {0}".format(to_string(new_line)))
    return new_line


def endpoints_by_direction(line, dir):
    """Return the (closer, farther) endpoints of the given line relative
    to the given direction.
    """
    (point1, point2) = list(line.boundary)

    weight = ((point1.x - point2.x) * dir.vector[0] +
              (point1.y - point2.y) * dir.vector[1])
    if weight > 0:
        return (point1, point2)
    elif weight < 0:
        return (point2, point1)
    else:
        raise RuntimeError("Unable to decide between {0} and {1} in {2}"
                           .format(to_string(point1), to_string(point2),
                                   dir.name))


def point_sweep(point, dx_or_dir, dy_or_dist):
    """Moves the given point and constructs a line segment between the two.
    Returns the constructed line
    """
    point2 = translate(point, dx_or_dir, dy_or_dist)
    new_line = line([point, point2])
    return new_line


def sweep(base_line, dir, distance, base_dir=None, width=None):
    """Sweep the given line in the given direction for the given distance.
    Returns the tuple (polygon, new_line) where polygon is the polygon defined
    by the swept line, and new_line is the final line position.
    """
    assert isinstance(dir, Direction)

    # line can be a LineString object or simply a list of coords
    line1 = line(base_line)

    line2 = translate(line1, dir, distance)

    poly2 = loft(line1, line2)

    log.debug("Swept polygon from {0} in {1} by {2}: {3}"
              .format(to_string(line1), dir.name, distance,
                      to_string(poly2)))
    return (poly2, line2)


def loft(*args):
    """Construct a polygon from the given linear cross-sections.
       ----               ----_
      /                  /     -_
                  --->   \       -
          -----           \  -----
         /                 \/
    """
    lines = list(args)
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
            poly1 = union(line1, line2).convex_hull
            if poly1.is_valid:
                poly = poly1

        log.debug("Constructed {0}".format(to_string(poly)))
        if poly is not None:
            poly_set.add(poly)
        line1 = line2

    return shapely.ops.cascaded_union(poly_set)


def loft_to_grid(base_line, dir, width):
    """Construct the resulting shape needed to connect the given line to
    the appropriate grid points in the given direction.

    Returns the tuple (aligned_line, lofted_polygon).
    In some cases there may be more than one plausible way to do this lofting;
    if so, the one chosen will be the lofted_polygon with the least area.
    """
    assert isinstance(dir, Direction)
    base_line = line(base_line)

    print("Lofting {0} to the {1} to align to the grid"
          .format(to_string(base_line), dir))
    (p1, p2) = base_line.boundary
    if dir.is_cardinal():
        divisor = 10
    else:
        divisor = 5

    (p1, p2) = endpoints_by_direction(base_line, dir.rotate(90))

    if dir.vector[0] < 0:
        x1 = math.floor(p1.x / divisor) * divisor
        x2 = math.floor(p2.x / divisor) * divisor
    elif dir.vector[0] > 0:
        x1 = math.ceil(p1.x / divisor) * divisor
        x2 = math.ceil(p2.x / divisor) * divisor
    else:
        x1 = round(p1.x / divisor) * divisor
        x2 = round(p2.x / divisor) * divisor
    if dir.vector[1] < 0:
        y1 = math.floor(p1.y / divisor) * divisor
        y2 = math.floor(p2.y / divisor) * divisor
    elif dir.vector[1] > 0:
        y1 = math.ceil(p1.y / divisor) * divisor
        y2 = math.ceil(p2.y / divisor) * divisor
    else:
        y1 = round(p1.y / divisor) * divisor
        y2 = round(p2.y / divisor) * divisor
    p1 = point(x1, y1)
    p2 = point(x2, y2)

    candidate_1 = point_sweep(p1, dir.rotate(-90), width)
    candidate_2 = point_sweep(p2, dir.rotate(90), width)
    # TODO - intermediate possibilities?
    while sweep(candidate_1, dir, 50)[0].crosses(base_line):
        candidate_1 = translate(candidate_1, dir, 10)
    while sweep(candidate_2, dir, 50)[0].crosses(base_line):
        candidate_2 = translate(candidate_2, dir, 10)
    poly1 = loft(base_line, candidate_1)
    poly2 = loft(base_line, candidate_2)

    print("First candidate: {0}, {1}".format(to_string(candidate_1), poly1.area))
    print("Second candidate: {0}, {1}".format(to_string(candidate_2), poly2.area))

    if (poly1.area < poly2.area or (poly1.area == poly2.area and
                                    poly1.length < poly2.length)):
        candidate_line = candidate_1
        poly = poly1
    else:
        candidate_line = candidate_2
        poly = poly2

    print("New line is {0}".format(to_string(candidate_line)))
    return (candidate_line, poly)


    # Default guesses:
    x1 = round(p1.x / divisor) * divisor
    x2 = round(p2.x / divisor) * divisor
    y1 = round(p1.y / divisor) * divisor
    y2 = round(p2.y / divisor) * divisor

    if dir == Direction.W:
        x1 = x2 = math.floor(min(p1.x, p2.x) / divisor) * divisor
    elif dir == Direction.E:
        x1 = x2 = math.ceil(max(p1.x, p2.x) / divisor) * divisor
    elif dir == Direction.S:
        y1 = y2 = math.floor(min(p1.y, p2.y) / divisor) * divisor
    elif dir == Direction.N:
        y1 = y2 = math.ceil(max(p1.y, p2.y) / divisor) * divisor
    elif dir == Direction.NW:
        x1 = math.floor(min(p1.x, p2.x) / divisor) * divisor
        x2 = math.floor(max(p1.x, p2.x) / divisor) * divisor
        y1 = math.ceil(min(p1.y, p2.y) / divisor) * divisor
        y2 = math.ceil(max(p1.y, p2.y) / divisor) * divisor
    elif dir == Direction.NE:
        x1 = math.ceil(min(p1.x, p2.x) / divisor) * divisor
        x2 = math.ceil(max(p1.x, p2.x) / divisor) * divisor
        y1 = math.ceil(max(p1.y, p2.y) / divisor) * divisor
        y2 = math.ceil(min(p1.y, p2.y) / divisor) * divisor
    elif dir == Direction.SW:
        x1 = math.floor(min(p1.x, p2.x) / divisor) * divisor
        x2 = math.floor(max(p1.x, p2.x) / divisor) * divisor
        y1 = math.floor(max(p1.y, p2.y) / divisor) * divisor
        y2 = math.floor(min(p1.y, p2.y) / divisor) * divisor
    elif dir == Direction.SE:
        x1 = math.ceil(min(p1.x, p2.x) / divisor) * divisor
        x2 = math.ceil(max(p1.x, p2.x) / divisor) * divisor
        y1 = math.floor(min(p1.y, p2.y) / divisor) * divisor
        y2 = math.floor(max(p1.y, p2.y) / divisor) * divisor

    candidate_line = line([(x1, y1), (x2, y2)])
    while candidate_line.crosses(base_line):
        candidate_line = translate(candidate_line, dir, 10)

    # Sanity check
    if not grid_aligned(candidate_line, dir):
        raise RuntimeError("Final line {0} is not grid-aligned to the {1}"
                           .format(to_string(candidate_line), dir.name))
    print("New line is {0}".format(to_string(candidate_line)))
    return (candidate_line, loft(base_line, candidate_line))


def find_edge_segments(poly, width, direction):
    """Find grid-constrained line segments along the border of the given polygon
    in the given direction with the given width.
    Returns a list of zero or more line segments.
    """

    log.info("Finding line segments (width {0}) along the {1} edge of {2}"
             .format(width, direction, to_string(poly)))

    assert isinstance(direction, Direction)

    border = line_loop(poly.exterior.coords)

    (xmin, ymin, xmax, ymax) = poly.bounds

    if direction == Direction.N or direction == Direction.S:
        inter_box = box(math.floor(xmin/10)*10, ymin,
                        math.floor(xmin/10)*10 + width, ymax)
        offset = Direction.E
        def check_width(intersection):
            w = intersection.bounds[2] - intersection.bounds[0]
            return w == width
        def check_size(intersection, size):
            # Make sure width matches "size" and height not too much
            w = intersection.bounds[2] - intersection.bounds[0]
            h = intersection.bounds[3] - intersection.bounds[1]
            return (math.fabs(w - size) < 0.1 and h <= size)
        if direction[1] > 0: #north
            def prefer(option_a, option_b):
                return (option_a.bounds[1] > option_b.bounds[1])
        else: # south
            def prefer(option_a, option_b):
                return (option_a.bounds[3] < option_b.bounds[3])
    elif direction == Direction.W or direction == Direction.E:
        inter_box = box(xmin, math.floor(ymin/10)*10,
                        xmax, math.floor(ymin/10)*10 + width)
        offset = Direction.N
        def check_width(intersection):
            h = intersection.bounds[3] - intersection.bounds[1]
            return h == width
        def check_size(intersection, size):
            # Make sure height matches "size" and width not too much
            w = intersection.bounds[2] - intersection.bounds[0]
            h = intersection.bounds[3] - intersection.bounds[1]
            return (math.fabs(h - size) < 0.1 and w <= size)
        if direction[0] < 0: #west
            def prefer(option_a, option_b):
                return (option_a.bounds[0] < option_b.bounds[0])
        else: # east
            def prefer(option_a, option_b):
                return (option_a.bounds[2] > option_b.bounds[2])
    elif direction == Direction.NW or direction == Direction.SE:
        line1 = point_sweep(point(math.floor(xmin/10) * 10,
                                  math.ceil(ymax/10) * 10), Direction.NE, 200)
        line2 = point_sweep(point(math.ceil(xmax/10) *10,
                                  math.floor(ymin/10) * 10), Direction.NE, 200)
        line3 = point_sweep(point(math.ceil(xmax/10) * 10,
                                  math.ceil(ymax/10) * 10), Direction.NW, 200)
        line4 = point_sweep(point(math.ceil(xmax/10) * 10,
                                  math.ceil(ymax/10) * 10), Direction.SE, 200)
        point1 = intersect(line1, line3)
        point2 = intersect(line2, line4)
        assert isinstance(point1, Point) and isinstance(point2, Point)
        point3 = translate(point2, Direction.SW, width)
        point4 = translate(point1, Direction.SW, width)
        inter_box = polygon([point1, point2, point3, point4])
        offset = Direction.SW
        def check_width(intersection):
            l = ((intersection.bounds[2] - intersection.bounds[0]) +
                 (intersection.bounds[3] - intersection.bounds[1]))
            return l == width
        def check_size(intersection, size):
            w = intersection.bounds[2] - intersection.bounds[0]
            h = intersection.bounds[3] - intersection.bounds[1]
            return (math.fabs(w + h - size) < 0.1)
        if direction[1] > 0: #north
            def prefer(option_a, option_b):
                return (option_a.bounds[1] > option_b.bounds[1])
        else: # south
            def prefer(option_a, option_b):
                return (option_a.bounds[3] < option_b.bounds[3])
    elif direction == Direction.NE or direction == Direction.SW:
        line1 = point_sweep(point(math.floor(xmin/10) * 10,
                                  math.floor(ymin/10) * 10), Direction.NW, 200)
        line2 = point_sweep(point(math.ceil(xmax/10) * 10,
                                  math.ceil(ymax/10) * 10), Direction.NW, 200)
        line3 = point_sweep(point(math.floor(xmin/10) * 10,
                                  math.ceil(ymax/10) * 10), Direction.SW, 200)
        line4 = point_sweep(point(math.floor(xmin/10) * 10,
                                  math.ceil(ymax/10) * 10), Direction.NE, 200)
        point1 = intersect(line1, line3)
        point2 = intersect(line2, line4)
        assert isinstance(point1, Point) and isinstance(point2, Point)
        point3 = translate(point2, Direction.SE, width)
        point4 = translate(point1, Direction.SE, width)
        inter_box = polygon([point1, point2, point3, point4])
        offset = Direction.SE
        def check_width(intersection):
            l = ((intersection.bounds[2] - intersection.bounds[0]) +
                 (intersection.bounds[3] - intersection.bounds[1]))
            return l == width
        def check_size(intersection, size):
            w = intersection.bounds[2] - intersection.bounds[0]
            h = intersection.bounds[3] - intersection.bounds[1]
            return (math.fabs(w + h - size) < 0.1)
        if direction[1] > 0: #north
            def prefer(option_a, option_b):
                return (option_a.bounds[1] > option_b.bounds[1])
        else: # south
            def prefer(option_a, option_b):
                return (option_a.bounds[3] < option_b.bounds[3])

    print("box: {0}, offset: {1}".format(to_string(inter_box), offset))
    candidates = []

    first_hit = False

    while True:
        intersection = intersect(inter_box, border)
        log.debug("intersection: {0}".format(to_string(intersection)))
        if intersection.length == 0:
            if not first_hit:
                # We're not there yet - just move closer
                inter_box = translate(inter_box, offset, 10)
                continue
            else:
                # We've crossed the shape and exited the other side
                break
        best = None
        first_hit = True
        if not hasattr(intersection, "geoms"):
            intersection = [intersection]

        segments = []
        for segment in intersection:
            segments += minimize_line(segment, check_width)
        intersection = segments

        for linestring in intersection:
            if check_size(linestring, width):
                if best is None or prefer(linestring, best):
                    best = linestring

        inter_box = translate(inter_box, offset, 10)

        if best is None:
            continue

        print("Found section: {0}".format(to_string(best)))
        candidates.append(best)

    log.info("Found {0} candidate edges: {1}"
             .format(len(candidates), [bounds_str(c) for c in candidates]))
    return candidates


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
        else:
            print("{0} does not intersect {1}"
                  .format(to_string(difference), to_string(adjacent_shape)))

    if match is not None:
        log.debug("Trimmed shape to fit")
        # TODO? force all coordinates in match to snap to 1' grid
    else:
        log.debug("After trimming, shape is nonexistent")

    return match


def minimize_line(base_line, validator):
    """Trim the given line from both ends to the minimal line(s) that
    satisfy the given validator function. Returns a list of 1 or 2
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
    elif isinstance(coords, CoordinateSequence) or type(coords) is list:
        if isinstance(coords[0], Point):
            coords = [(point.x, point.y) for point in coords]
        line = LineString(coords)
    else:
        raise RuntimeError("Don't know how to construct a line segment from {0}"
                           .format(coords))
    assert line.is_valid
    return line


def line_loop(coords):
    """Constructs a linear loop from the given coordinate sequence
    (implicitly connecting end and start if needed).
    """
    loop = LinearRing(coords)
    assert loop.is_valid
    return loop


def polygon(coords=None):
    """Construct a polygon from the given coordinate sequence or list of points.
    """
    if isinstance(coords, Polygon):
        poly = coords
    elif coords is None:
        poly = Polygon()
    elif type(coords) is list:
        if isinstance(coords[0], Point):
            coords = [(point.x, point.y) for point in coords]
        poly = Polygon(coords)
    else:
        raise RuntimeError("Not sure how to create Polygon from {0}"
                           .format(coords))
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
    if len(args) == 1:
        args = args[0]
    union = shapely.ops.cascaded_union(args)
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
