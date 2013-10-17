#!/usr/bin/env python
# DungeonMap - the Model for our dungeon generator
#
# Represented as a collection of Regions and Connections.
# Each Region owns a single polygon that does not overlap any other Regions.
# Each Connection straddles the border between two Regions.
# The DungeonMap handles collision detection between Regions and so forth.
# A Region may have one or more Decorations which are items placed on the map
# that do not have any direct implications for the map geometry.
#
# In order to ensure reproducibility (i.e., using the same random seed will
# always generate the same dungeon map), the DungeonMap can use sets internally
# but all access through get_foo() functions must return consistently sorted
# lists.

import logging
import math
import re
from itertools import count

import aagen.geometry
from aagen.geometry import to_string
from aagen.direction import Direction

log = logging.getLogger(__name__)

class SortedSet:
    """A container class for a set of objects that is always ordered by
    object's self-declared ID. Needed for consistent random dungeon generation.
    """

    def __init__(self, contents=None):
        self.set = set()
        if contents is not None:
            for item in contents:
                self.add(item)


    def __len__(self):
        return len(self.set)


    def __contains__(self, item):
        return item in self.set


    def __iter__(self):
        return iter(sorted(self.set, key=lambda item: item.id))


    def __repr__(self):
        return "<SortedSet: {0}>".format([item for item in self])


    def add(self, item):
        assert hasattr(item, 'id')
        self.set.add(item)


    def remove(self, item):
        self.set.remove(item)


class DungeonMap:
    """Master model class. Stores a collection of Regions and Connections"""

    _ids = count(0)

    def __init__(self):
        """Initialize a new empty DungeonMap"""
        self.regions = SortedSet()
        self.connections = SortedSet()
        self.decorations = SortedSet()
        self.conglomerate_polygon = None
        self.id = self._ids.next()
        log.debug("Initialized {0}".format(self))


    def __repr__(self):
        return ("<DungeonMap {4}: {0} regions, "
                "{1} connections ({2} incomplete), "
                "{5} decorations, "
                "total {3} square feet>"
                .format(len(self.regions), len(self.connections),
                        len(self.get_incomplete_connections()),
                        (self.conglomerate_polygon.area if
                         self.conglomerate_polygon is not None else 0),
                        self.id,
                        len(self.decorations)))


    def __getattr__(self, name):
        if name == "bounds":
            return self.get_bounds()
        raise AttributeError("'{0}' object has no attribute '{1}'"
                             .format(self.__class__, name))


    def object_at(self, (x, y)):
        """Get the Connection or Region at the clicked location"""
        point = aagen.geometry.point(x, y)
        for dec in self.decorations:
            if dec.polygon.contains(point):
                return dec
        for conn in self.connections:
            if conn.polygon.contains(point):
                return conn
        for reg in self.regions:
            if reg.polygon.contains(point):
                return reg
        return self


    def get_bounds(self):
        """Returns (x0, y0, x1, y1) describing the extent of the map"""
        if self.conglomerate_polygon is None:
            log.warning("{0}: no conglomerate polygon?".format(self))
            return (0, 0, 0, 0)
        return self.conglomerate_polygon.bounds


    def add_region(self, region):
        assert isinstance(region, Region)
        if not region in self.regions:
            log.info("Adding Region ({0}) to {1}".format(region, self))
            self.regions.add(region)
            polygons = set([r.polygon for r in self.regions])
            self.conglomerate_polygon = aagen.geometry.union(polygons)
            for decoration in region.decorations:
                self.add_decoration(decoration)
            for connection in region.connections:
                self.add_connection(connection)
            # Look for any existing connections to fix up
            for connection in self.get_incomplete_connections():
                log.debug("Checking {0} for intersection with {1}"
                         .format(connection, region))
                if (connection.polygon.intersects(region.polygon) and
                    not connection.polygon.touches(region.polygon)):
                    # TODO fix up any funky edges
                    connection.add_region(region)
                    self.add_connection(connection)

    def add_decoration(self, dec):
        assert isinstance(dec, Decoration)
        if not dec in self.decorations:
            log.info("Adding {0} to {1}".format(dec, self))
            self.decorations.add(dec)


    def add_connection(self, connection):
        assert isinstance(connection, Connection)
        if not connection in self.connections:
            log.info("Adding {0} to {1}".format(connection, self))
            self.connections.add(connection)
            for region in connection.regions:
                self.add_region(region)
            # Look for any existing regions to fix up
            for region in self.regions:
                log.debug("Checking {0} for intersection with {1}"
                          .format(connection, region))
                if (region.polygon.intersection(connection.line).equals(connection.line) or
                    (connection.polygon.intersects(region.polygon) and
                     not connection.polygon.touches(region.polygon))):
                    # TODO fix up any funky edges
                    region.add_connection(connection)


    def remove_connection(self, connection):
        assert isinstance(connection, Connection)
        if connection in self.connections:
            log.info("Removing {0} from {1}".format(connection, self))
            self.connections.remove(connection)
            for region in connection.regions:
                region.remove_connection(connection)


    def get_incomplete_connections(self):
        return [item for item in self.connections if item.is_incomplete()]


    def find_adjacency_options(self, old_shape, new_shape, direction):
        """Given the two shapes and a direction, figure out how to position
        new shape so that it is adjacent to old shape in the given direction.

        Returns ((x0, y0), (pos_x, pos_y), (shift_x, shift_y)) where:
        (x0, y0) is the initial offset to apply to new_shape
        (pos_x, pos_y) is successive offsets to apply to new_shape to determine
            candidate positions for intersection (if desired)
        (shift_x, shift_y) is offsets to apply to each position to adjust the
            intersection

        An example:

        Given:
           OO           NNNN
           OO     ,     NNNN    ,     direction (1, 0)
           OO
        will return (x0, y0) to apply to the new shape so that:
         NNNN
         NNNN      is the starting position, and:
           OO      (pos_x, pos_y) will be ---->
           OO      (shift_x, shift_y) will be |
           OO                                 V

        If new were narrower than old, the starting position would instead be:
           NN
           NN
           OOOO
           OOOO

        Clear as mud?
        """

        assert isinstance(direction, Direction)

        (old_x0, old_y0, old_x1, old_y1) = old_shape.bounds
        (new_x0, new_y0, new_x1, new_y1) = new_shape.bounds
        (dir_x, dir_y) = direction

        if dir_y < 0 and dir_x == 0: # North
            # Position new so its south edge touches the north edge of old
            # and its east edge overlaps the west edge of old
            (x0, y0) = (min(old_x0 - new_x0, old_x1 - new_x1),
                        old_y0 - new_y1)
            # Snap to grid
            (x0, y0) = (10 * math.ceil(x0 / 10),
                        10 * math.ceil(y0 / 10))
            # Try possible positions every 10' to the east
            (pos_x, pos_y) = (10, 0)
            # For each position, if it doesn't intersect, shift it 10' south
            # until it does
            (shift_x, shift_y) = (0, 10)
        elif dir_x < 0 and dir_y == 0: # west
            # Position new so its east edge touches the west edge of old
            # and its south edge overlaps the north edge of old
            (x0, y0) = (old_x0 - new_x1,
                        min(old_y0 - new_y0, old_y1 - new_y1))
            # Snap to grid
            (x0, y0) = (10 * math.ceil(x0 / 10),
                        10 * math.ceil(y0 / 10))
            # Try possible positions every 10' to the south
            (pos_x, pos_y) = (0, 10)
            # For each position, if it doesn't intersect, shift it 10' east
            # until it does
            (shift_x, shift_y) = (10, 0)
        elif dir_y > 0 and dir_x == 0: # south
            # Position new so its north edge touches the south edge of old
            # and its east edge overlaps the west edge of old
            (x0, y0) = (min(old_x0 - new_x0, old_x1 - new_x1),
                        old_y1 - new_y0)
            # Snap to grid
            (x0, y0) = (10 * math.ceil(x0 / 10),
                        10 * math.floor(y0 / 10))
            # Try possible positions every 10' to the east
            (pos_x, pos_y) = (10, 0)
            # For each position, if it doesn't intersect, shift it 10' north
            # until it does
            (shift_x, shift_y) = (0, -10)
        elif dir_x > 0 and dir_y == 0: # east
            # Position new so its west edge touches the east edge of old
            # and its south edge overlaps the north edge of old
            (x0, y0) = (old_x1 - new_x0,
                        min(old_y0 - new_y0, old_y1 - new_y1))
            # Snap to grid
            (x0, y0) = (10 * math.floor(x0 / 10),
                        10 * math.ceil(y0 / 10))
            # Try possible positions every 10' to the south
            (pos_x, pos_y) = (0, 10)
            # For each position, if it doesn't intersect, shift it 10' west
            # until it does
            (shift_x, shift_y) = (-10, 0)
        else:
            raise ValueError("Only cardinal directions are supported - not {0}"
                             .format(direction))

        # Snap initial delta to grid
        log.info("Rounding off ({x}, {y})".format(x=x0, y=y0))
        (x0, y0) = (round(x0, -1), round(y0, -1))

        log.info("Base offset is ({x}, {y})".format(x=x0, y=y0))
        return ((x0, y0), (pos_x, pos_y), (shift_x, shift_y))


    def find_options_for_connection(self, width, region, direction,
                                    new_only=True):
        """Find valid positional options (if any) for placing a Connection
        of the given size along the given edge of the given region).
        If new_only is set then only positions leading to new (unmapped) space
        will be considered as valid.
        Returns a list of line segments."""

        log.info("Finding options for a connection (width {0}) adjacent to "
                 "{1} in {2}".format(width, region, direction))

        assert isinstance(region, Region) and isinstance(direction, Direction)

        # We find connection options by looking at the walls of the region
        full_walls = aagen.geometry.line_loop(region.coords)
        log.debug("full_walls: {0}".format(to_string(full_walls)))

        (xmin, ymin, xmax, ymax) = full_walls.bounds
        log.debug("bounds: {0}".format(aagen.geometry.bounds_str(full_walls)))

        if math.fabs(direction[1]) > 0.01: # north/south
            box = aagen.geometry.box(xmin, ymin, xmin + width, ymax)
            offset = (10, 0)
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
        elif math.fabs(direction[0]) > 0.01: # east/west
            box = aagen.geometry.box(xmin, ymin, xmax, ymin + width)
            offset = (0, 10)
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

        log.debug("box: {0}, offset: {1}".format(to_string(box), offset))
        candidates = []
        i = 0
        while aagen.geometry.intersect(box, full_walls).length > 0:
            log.debug("box: {0}".format(aagen.geometry.bounds_str(box)))
            intersection = aagen.geometry.intersect(box, full_walls)
            log.debug("intersection: {0}".format(to_string(intersection)))
            best = None
            if not hasattr(intersection, "geoms"):
                # We must be tangent to an edge of the polygon, since our
                # intersection has both "front" and "back" in a single
                # segment. In this case we need to trim the segment down
                # until it only contains the "front" of the intersection.
                # We do this by deleting points from one end of the segment
                # until we cannot do so without decreasing the intersection
                # width by doing so. We then do the same from the other end,
                # and compare the two to see which is preferred
                intersection = aagen.geometry.minimize_line(intersection,
                                                            check_width)
            for linestring in intersection:
                if check_size(linestring, width):
                    if best is None:
                        best = linestring
                    elif prefer(linestring, best):
                        best = linestring
            if best is not None:
                log.debug("Found section: {0}"
                          .format(aagen.geometry.bounds_str(best)))
                valid = True
                # Make sure it doesn't intersect any existing conns
                for conn in region.connections:
                    # Intersection of line and polygon...
                    if (best.intersects(conn.polygon) and
                        best.intersection(conn.polygon).length > 0):
                        log.debug("Conflicts with existing conn {0}"
                                 .format(conn))
                        valid = False
                        break
                if valid and new_only:
                    # Make sure it doesn't intersect any other regions
                    for test_region in self.regions:
                        if test_region == region:
                            continue
                        if (best.crosses(test_region.polygon) or
                            best.contains(test_region.polygon) or
                            test_region.polygon.contains(best)):
                            log.debug("Conflicts with existing region {0}"
                                     .format(test_region))
                            valid = False
                            break
                if valid:
                    candidates.append(best)
            i += 1
            box = aagen.geometry.translate(box, *offset)

        log.info("{0} candidate positions were identified after inspecting "
                 "{1} possibilities"
                 .format(len(candidates), i))
        return candidates


    def find_options_for_region(self, shape_list, connection):
        """Find valid positional options (if any) for placing one of the
        given shapes adjacent to the given Connection.
        Returns a list of Candidate_Region objects"""

        if connection.grow_direction.is_cardinal():
            direction = connection.grow_direction
        elif connection.base_direction.is_cardinal():
            direction = connection.base_direction
        else:
            return []
            # TODO

        log.info("Looking for positional options for region {0} "
                 "adjacent to {1} in {2}"
                 .format([to_string(c) for c in shape_list],
                         connection, direction))

        # Our approach is as follows:
        # For each of the candidate coords in coords_set:
        # Find an initial grid position so that its bounding box is adjacent
        # to the bounding box of the conn
        # Iteratively move the coords toward the conn until the actual polygons
        # intersect one another. Find the trimmed polygon and store it.
        # Reset to the original grid position and move "sideways" one grid space
        # Repeat as many times as needed

        (obj_x0, obj_y0, obj_x1, obj_y1) = connection.polygon.bounds
        conn_box = aagen.geometry.box(*(connection.polygon.bounds))
        (dir_x, dir_y) = direction

        log.info("Adjacency direction is {0},{1}".format(dir_x, dir_y))

        candidate_regions = []
        i = 0
        for polygon in shape_list:
            log.info("Looking for positional options for {0}"
                     .format(to_string(polygon)))

            (new_x0, new_y0, new_x1, new_y1) = polygon.bounds

            ((x0, y0),
             (pos_x, pos_y),
             (shift_x, shift_y)) = self.find_adjacency_options(
                 connection.polygon, polygon, direction)

            # Try each possible position where the bounding boxes intersect
            (px, py) = (0, 0)
            while (aagen.geometry.box(new_x0 + x0 + px, new_y0 + y0 + py,
                                      new_x1 + x0 + px, new_y1 + y0 + py)
                   .intersects(conn_box)):
                log.debug("px, py: {0}, {1}".format(px, py))
                if math.fabs(dir_y) > 0.01 and (new_x0 + x0 + px) > obj_x0:
                    log.debug("Reached max x offset")
                    break
                elif math.fabs(dir_x) > 0.01 and (new_y0 + y0 + py) > obj_y0:
                    log.debug("Reached max y offset")
                    break
                hit_found = False
                # Shift the polygon towards the conn until either the actual
                # shape intersects (a hit!) or the bounding boxes no longer
                # intersect (a miss!)
                (sx, sy) = (0, 0)
                while (aagen.geometry.box(new_x0 + x0 + px + sx,
                                          new_y0 + y0 + py + sy,
                                          new_x1 + x0 + px + sx,
                                          new_y1 + y0 + py + sy)
                       .intersects(conn_box)):
                    i += 1
                    (dx, dy) = (x0 + px + sx, y0 + py + sy)
                    log.debug("dx, dy: {0}, {1}".format(dx, dy))
                    test_polygon = aagen.geometry.translate(polygon, dx, dy)
                    # TODO try_region_as_candidate
                    try:
                        intersection = test_polygon.intersection(connection.polygon)
                    except:
                        intersection = None
                    if (intersection is not None and
                        intersection.area > 0):
                        # A hit?
                        hit_found = True
                        # Add the connection polygon to the region
                        test_polygon = test_polygon.union(connection.polygon)
                        # See how much the polygon will be truncated by
                        # the existing dungeon map
                        trim_polygon = aagen.geometry.trim(test_polygon,
                                                           self.conglomerate_polygon,
                                                           connection.polygon)
                        if trim_polygon is not None:
                            cr = self.make_candidate_region((dx, dy),
                                                            test_polygon,
                                                            trim_polygon)
                            if cr is not None:
                                log.info("Found a match at ({x}, {y})"
                                         .format(x=dx, y=dy))
                                candidate_regions.append(cr)
                        else:
                            log.debug("Fully subsumed - on to next pos")
                            break
                    else:
                        log.debug("No intersection at {x}, {y}"
                                 .format(x=dx, y=dy))
                        if hit_found:
                            # We went from hitting to missing, done here!
                            break
                    (sx, sy) = (sx + shift_x, sy + shift_y)
                # Okay, we exhausted that position, move on to the next
                (px, py) = (px + pos_x, py + pos_y)
        log.info("{0} candidate regions were identified after inspecting "
                 "{1} possibilities"
                 .format(len(candidate_regions), i))
        return candidate_regions


    def try_region_as_candidate(self, coords_or_polygon, connection):
        polygon = aagen.geometry.polygon(coords_or_polygon)
        log.info("Trying {0} as candidate against {1}"
                 .format(to_string(polygon), connection))

        # See how much the polygon will be truncated by the existing map
        trim_polygon = aagen.geometry.trim(polygon, self.conglomerate_polygon,
                                           connection.polygon)
        if trim_polygon is not None:
            return self.make_candidate_region((0, 0), polygon, trim_polygon)
        else:
            log.info("{0} trimmed to nothing!".format(to_string(polygon)))
            return None


    def make_candidate_region(self, offset, base_polygon, trim_polygon):
        """Construct a candidate region"""
        conn_set = set()
        for connection in self.get_incomplete_connections():
            if connection.polygon.intersects(trim_polygon):
                conn_set.add(connection)
        amount_truncated = base_polygon.area - trim_polygon.area
        log.debug("amount_truncated: {0}".format(amount_truncated))
        wall_delta = (self.conglomerate_polygon.length -
                      self.conglomerate_polygon.union(trim_polygon).length)
        log.debug("base length: {0} trim length: {1} combined length: {2} "
                  "wall_delta: {3}"
                  .format(self.conglomerate_polygon.length,
                          trim_polygon.length,
                          self.conglomerate_polygon.union(trim_polygon).length,
                          wall_delta))
        log.debug("polygon: {0}\nconglomerate: {1}"
                  .format(list(trim_polygon.exterior.coords),
                          list(self.conglomerate_polygon.exterior.coords)))
        shared_walls = (trim_polygon.length + wall_delta) / 2
        if shared_walls < 5:
            log.info("Candidate only shares {0}' of walls - not valid!"
                     .format(shared_walls))
            return None

        return Candidate_Region(offset, trim_polygon, conn_set,
                                amount_truncated, shared_walls)


class MapElement(object):
    """Abstract parent class for any object placed onto the DungeonMap"""

    _ids = count(0)

    def __init__(self, polygon):
        self.id = self._ids.next()
        self.polygon = aagen.geometry.polygon(polygon)

    def __getattr__(self, name):
        if name == "coords":
            return self.polygon.exterior.coords
        elif name == "bounds":
            return self.polygon.bounds
        raise AttributeError("'{0}' object has no attribute '{1}'"
                             .format(self.__class__, name))


class Candidate_Region(MapElement):
    """Model class for temporary objects representing potential locations
    for an Region"""

    def __init__(self, offset, polygon, connections, trunc, shared):
        super(Candidate_Region, self).__init__(polygon)
        # Offset of this candidate region compared to the original
        # polygon we were provided
        self.offset = offset

        # Parameters that a controller can use when deciding between
        # multiple Candidate_Regions

        # How many existing open connections on this map would be resolved?
        self.connections = SortedSet(connections)

        # How much of the original requested area was truncated?
        self.amount_truncated = trunc

        # How much wall length is shared with the existing dungeon?
        self.shared_walls = shared

        log.debug("Constructed {0}".format(self))


    def __repr__(self):
        return ("<Candidate_Region {5}: offset {4}, poly {0}, conns {1}, "
                "trunc {2}, shared {3}>"
                .format(to_string(self.polygon), self.connections,
                        self.amount_truncated,
                        self.shared_walls, self.offset, self.id))


class Region(MapElement):
    """Model class. Represents a single contiguous region of the dungeon map,
    such as a room, chamber, or passage. An Region may have multiple Connections
    to other Regions."""

    ROOM = "Room"
    CHAMBER = "Chamber"
    PASSAGE = "Passage"
    __kinds = [ROOM, CHAMBER, PASSAGE]

    def __init__(self, kind, points_or_poly):
        """Construct a new Region."""

        if not kind in Region.__kinds:
            raise RuntimeError("Unknown Region type '{0}'".format(kind))

        super(Region, self).__init__(points_or_poly)

        self.kind = kind
        self.connections = SortedSet()
        self.decorations = SortedSet()

        log.info("Constructed {0}".format(self))


    def __repr__(self):
        return ("<Region {4}: {0} in {1} (area {2}) with {3} connections "
                "and {5} decorations>"
                .format(self.kind, aagen.geometry.bounds_str(self.polygon),
                        self.polygon.area,
                        len(self.connections),
                        self.id,
                        len(self.decorations)))


    def get_wall_lines(self):
        """Get the geometry that represents the walls of this Region,
        excluding any sections of the wall that are already owned by a
        Connection"""
        shape = aagen.geometry.line(self.coords)
        for connection in self.connections:
            #TODO shape = shape.difference(connection.polygon)
            shape = shape.difference(connection.line.buffer(0.1))
        return shape


    def get_wall_coords(self):
        """Same as get_wall_lines() but returns a list of lists of points
        instead of a geometry object"""
        shape = self.get_wall_lines()
        coords_list = aagen.geometry.lines_to_coords(shape)
        if not coords_list:
            log.info("Room has no open walls at all?")
        log.debug("{0} has walls: {1}".format(self, coords_list))
        return coords_list


    def add_connection(self, connection):
        """Make note that the given Connection is linked to this Region"""
        assert isinstance(connection, Connection)
        # TODO
        #if not connection.polygon.intersects(self.polygon):
        #    raise RuntimeError("Tried to add connection ({0}) to region ({1}) "
        #                       "but they do not intersect!"
        #                       .format(connection, self))
        if not connection in self.connections:
            self.connections.add(connection)
            log.info("Added ({0}) to ({1})".format(connection, self))
            connection.add_region(self)


    def remove_connection(self, connection):
        assert isinstance(connection, Connection)
        if connection in self.connections:
            self.connections.remove(connection)
            log.info("Removed {0} from {1}".format(connection, self))


    def add_decoration(self, decoration):
        """Add a decorative region to this Region"""
        assert isinstance(decoration, Decoration)
        self.decorations.add(decoration)
        log.debug("Added ({0}) to ({1})".format(decoration, self))


class Connection(MapElement):
    """Model class. Represents a connection between two adjacent Region objects,
    such as a door or archway. Modeled as a line segment which corresponds to
    the adjacent edge shared by the two Regions.

    A Connection that only has one Region is "incomplete" and forms a point for
    additional expansion/exploration of the dungeon. To assist with intelligent
    construction of a new Region, a Connection defines the following:

    - A "just beyond" polygon region defining the space immediately past the
      Connection - i.e., the minimal area that the new Region will need to cover
      in order to be fully connected to this Connection. This polygon is
      constructed by extruding the baseline of the Connection by 10' in its
      primary direction, then 45 degrees off from this direction to the left and
      right, and taking the intersection of these three polygons.

    - A set of "likely expansion" polygons showing areas where this Connection
      might conceivably expand to... TODO

"""

    # Kinds of connections
    OPEN = "Open"
    DOOR = "Door"
    SECRET = "Secret Door"
    ONEWAY = "One-Way Door"
    ARCH = "Arch"
    __kinds = [OPEN, DOOR, SECRET, ONEWAY, ARCH]

    def __init__(self, kind, line_coords, regions=None,
                 grow_dir=None):
        """Construct a Connection along the given edge"""
        assert kind in Connection.__kinds
        self.kind = kind

        self.line = aagen.geometry.line(line_coords)
        line_coords = (self.line.coords[0], self.line.coords[-1])
        assert self.line.length > 0

        log.info("Creating Connection ({kind}) along {line}"
                 .format(kind=kind, line=to_string(self.line)))

        # The "base direction" of a connection is a unit direction
        # perpendicular to its base line
        self.base_direction = Direction(baseline=line_coords)

        # The growth direction of a connection is the direction in which
        # new regions (mostly Passages) will by default be extended.
        # If not specified it is the same as the base direction.
        if grow_dir is None:
            self.grow_direction = self.base_direction
        else:
            self.grow_direction = Direction(vector=grow_dir)

        # The base and grow directions should never be more than
        # 45 degrees different:
        angle =  self.base_direction.angle_from(self.grow_direction)
        if angle > 90:
            # Must have got a sign wrong somewhere...
            self.base_direction = self.base_direction.rotate(180)
            angle =  self.base_direction.angle_from(self.grow_direction)
        if angle > 45:
            log.warning("Angle between base {0} and grow {1} directions "
                        "is too great: {2}!".format(self.base_direction,
                                                    self.grow_direction,
                                                    angle))

        (poly1, junk) = aagen.geometry.sweep(self.line,
                                             self.base_direction, 10)
        assert poly1.is_valid
        (poly2, junk) = aagen.geometry.sweep(self.line,
                                             self.base_direction.rotate(-45),
                                             10)
        (poly3, junk) = aagen.geometry.sweep(self.line,
                                             self.base_direction.rotate(45),
                                             10)
        if poly2.is_valid and poly2.area > 0:
            poly1 = poly1.intersection(poly2).convex_hull
        if poly3.is_valid and poly3.area > 0:
            poly1 = poly1.intersection(poly3).convex_hull
        super(Connection, self).__init__(poly1)
        log.info("Connection polygon is {0}".format(to_string(self.polygon)))

        self.regions = SortedSet()
        if regions is not None:
            if isinstance(regions, Region):
                regions = [regions]
            for region in regions:
                self.add_region(region)
                region.add_connection(self)

        # Add helper polygons for drawing
        if kind == Connection.DOOR:
            start = self.line.interpolate(2)
            end = self.line.interpolate(self.line.length - 2)
            sub_line = aagen.geometry.line([(start.x, start.y), (end.x, end.y)])
            left = sub_line.parallel_offset(2, 'left')
            right = sub_line.parallel_offset(2, 'right')
            self.draw_lines = aagen.geometry.line_loop(list(left.coords) +
                                                       list(right.coords))
        else:
            self.draw_lines = None

        log.debug("Constructed {0}".format(self))
        return


    def __repr__(self):
        return ("<Connection {id}: {kind} at {loc} to {base}/{dir}>"
                .format(id=self.id, kind=self.kind,
                        loc=aagen.geometry.bounds_str(self.polygon),
                        areas=self.regions, base=self.base_direction,
                        dir=self.grow_direction))


    def get_line_coords(self):
        return list(self.line.coords)


    def get_poly_coords(self):
        """Get the list of points defining this region's polygon"""
        return list(self.polygon.exterior.coords)


    def is_incomplete(self):
        """Returns True if the Connection does not connect two Regions yet"""
        return (len(self.regions) < 2)


    def is_complete(self):
        """Returns True if the Connection connects two Regions"""
        return (len(self.regions) == 2)


    def add_region(self, region):
        """Add another Region this Connection links to"""
        assert isinstance(region, Region)
        if not region in self.regions:
            self.regions.add(region)

            # Fix up any funky edges... TODO
            #if not self.polygon.intersects(region.polygon):
            #    extension = aagen.geometry.sweep(self.base_line,
            #                                     self.grow_direction, 10))
            #    if not extension.intersects(region.polygon):
            #        # Try growing in the reverse direction
            #        extension = aagen.geometry.sweep(self.base_line,
            #                                         self.grow_direction, -10))
            #    if not extension.intersects(region.polygon):
            #        raise RuntimeError("Connection {0} !adjacent to region {1}"
            #                           .format(self, region))

            #    extension = extension.difference(region)
            #    self.polygon = self.polygon.union(extension)

            if len(self.regions) > 2:
                # TODO throw an error?
                log.warning("Too many regions for ({0})".format(self))
            log.debug("Added Region ({0}) to Connection ({1})"
                      .format(region, self))
            region.add_connection(self)


class Decoration(MapElement):
    """An object that appears on the map but does not count as part of the
    physical geometry of the map like a Region would. Typically owned by
    a Region."""

    STAIRS = "Stairs"

    __kinds = [STAIRS]

    @classmethod
    def Stairs(cls, (x, y), (width, length), orientation):
        """Construct a Stairs decoration with the given center, size,
        and orientation"""
        # An isosceles triangle with height="length" and base="width"
        poly = aagen.geometry.polygon([(length/2, 0), (-length/2, width/2),
                                       (-length/2, -width/2)])
        poly = aagen.geometry.rotate(poly, orientation)
        poly = aagen.geometry.translate(poly, x, y)
        return cls(cls.STAIRS, poly, orientation)


    def __init__(self, kind, polygon, orientation):
        assert kind in self.__kinds
        assert isinstance(orientation, Direction)
        self.kind = kind

        super(Decoration, self).__init__(polygon)

        self.orientation = orientation

        log.debug("Constructed {0}".format(self))


    def __repr__(self):
        return ("<Decoration {id}: {kind} oriented {dir} at {poly}>"
                .format(id=self.id, kind=self.kind,
                        dir=self.orientation,
                        poly=aagen.geometry.bounds_str(self.polygon)))
