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
        self.conglomerate_polygon = aagen.geometry.polygon()
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


    def flush(self):
        """Mark all recently added elements as permanent parts of the map"""
        for region in self.regions:
            region.tentative = False
        for conn in self.connections:
            conn.tentative = False
        for decoration in self.decorations:
            decoration.tentative = False


    def add_map_elements(self, elements):
        for elem in elements:
            if isinstance(elem, Region):
                self.add_region(elem)
            elif isinstance(elem, Connection):
                self.add_connection(elem)
            elif isinstance(elem, Decoration):
                self.add_decoration(elem)
            else:
                raise RuntimeError("Not sure how to add {0} to the map!"
                                   .format(elem))


    def add_region(self, region):
        assert isinstance(region, Region)
        if not region in self.regions:
            log.info("Adding Region ({0}) to {1}".format(region, self))
            inter = aagen.geometry.intersect(region.polygon,
                                             self.conglomerate_polygon)
            if inter.area > 0:
                # TODO - convert this to an exception
                log.error("Trying to add {0} intersects existing map: {1}"
                          .format(region, to_string(inter)))
            self.regions.add(region)
            self.refresh_conglomerate()
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

    def refresh_conglomerate(self):
        """Regenerate the conglomerate polygon.
        """
        polygons = set([r.polygon for r in self.regions])
        self.conglomerate_polygon = aagen.geometry.union(polygons)


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
                if (region.polygon.intersection(connection.line)
                    .equals(connection.line) or
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
                                    new_only=True, allow_rotation=True):
        """Find valid positional options (if any) for placing a Connection
        of the given size along the given edge of the given region).
        If new_only is set then only positions leading to new (unmapped) space
        will be considered as valid.
        If allow_rotation is set then also consider connection options
        that are rotated by +/- 45 degrees if that makes for a better fit.
        Returns a list of CandidateConnections."""

        log.info("Finding options for a connection (width {0}) adjacent to "
                 "{1} in {2}".format(width, region, direction))

        assert isinstance(region, Region) and isinstance(direction, Direction)

        segments = aagen.geometry.find_edge_segments(region.polygon, width,
                                                     direction)
        candidates = []
        for segment in segments:
            exit_dir = direction
            log.debug("Evaluating candidate segment: {0}"
                          .format(to_string(segment)))
            valid = True
            if aagen.geometry.grid_aligned(segment, direction):
                conn_poly = aagen.geometry.polygon()
            elif Direction.normal_to(segment).angle_from(direction) == 90:
                log.debug("Invalid: perpendicular to target direction")
                valid = False
            else:
                (segment, conn_poly) = aagen.geometry.loft_to_grid(
                    segment, direction, width)
                log.debug("segment: {0}, conn_poly: {1}"
                          .format(to_string(segment), to_string(conn_poly)))

            if valid:
                # Make sure the extension doesn't overflow into existing space,
                # as can happen when there is a diagonal passage nearby:
                if aagen.geometry.intersect(
                        conn_poly,
                        aagen.geometry.differ(self.conglomerate_polygon,
                                              region.polygon)).area > 0:
                    log.debug("Overflows into existing space - invalid")
                    valid = False

            if valid:
                # Make sure it doesn't intersect any existing conns
                for conn in region.connections:
                    if aagen.geometry.intersect(conn.line, segment).length > 0:
                        log.debug("Conflicts with existing conn {0}"
                                  .format(conn))
                        valid = False
                        break
            if valid and new_only:
                # Make sure it doesn't intersect any other regions
                for test_region in self.regions:
                    if test_region == region:
                        continue
                    if aagen.geometry.intersect(test_region.polygon,
                                                segment).length > 0:
                        log.debug("Conflicts with existing region {0}"
                                  .format(test_region))
                        valid = False
                        break
            if valid:
                candidates.append(CandidateConnection(segment, conn_poly,
                                                      exit_dir, region))

        log.info("{0} candidate positions were identified after inspecting "
                 "{1} possibilities"
                 .format(len(candidates), len(segments)))

        if allow_rotation:
            candidates += self.find_options_for_connection(
                width, region, direction.rotate(45), new_only, False)
            candidates += self.find_options_for_connection(
                width, region, direction.rotate(-45), new_only, False)

        return candidates


    def find_options_for_region(self, shape_list, connection):
        """Find valid positional options (if any) for placing one of the
        given shapes adjacent to the given Connection.
        Returns a list of Candidate_Region objects"""

        direction = connection.direction

        width = connection.size()

        log.info("Looking for positional options for region(s) {0} "
                 "adjacent to {1} in {2}"
                 .format([to_string(c) for c in shape_list],
                         to_string(connection.line), direction))

        # Our approach is as follows:
        # For each of the candidate shapes in shape_list:
        #   Find the possible edge segments on this shape
        #   For each possible edge:
        #     Shift the candidate shape so this edge aligns with the conn
        #     Evaluate the fit of this possible position

        candidate_regions = []
        for polygon in shape_list:
            log.info("Looking for positional options for {0}"
                     .format(to_string(polygon)))

            edges = aagen.geometry.find_edge_segments(polygon, width,
                                                      direction.rotate(180))
            if not edges:
                edges = (aagen.geometry.find_edge_segments(
                    polygon, width, direction.rotate(135)) +
                         aagen.geometry.find_edge_segments(
                    polygon, width, direction.rotate(-135)))

            for edge in edges:
                if aagen.geometry.grid_aligned(edge, direction):
                    edge_line = edge
                    edge_poly = aagen.geometry.polygon()
                else:
                    (edge_line, edge_poly) = aagen.geometry.loft_to_grid(
                        edge, direction.rotate(180), width)
                    log.debug("edge_poly: {0}".format(to_string(edge_poly)))

                dx = connection.line.bounds[0] - edge_line.bounds[0]
                dy = connection.line.bounds[1] - edge_line.bounds[1]

                # Make sure the region stays grid-aligned
                if (not direction.is_cardinal() and
                    (dx % 10 != 0 or dy % 10 != 0)):
                    log.info("Adjusting edge_line {0}, edge_poly {1} to be grid-aligned"
                             .format(to_string(edge_line), to_string(edge_poly)))
                    (new_edge_poly, edge_line) = aagen.geometry.sweep(
                        edge_line, direction.rotate(180), 10)
                    edge_poly = aagen.geometry.union(edge_poly, new_edge_poly)
                    dx = connection.line.bounds[0] - edge_line.bounds[0]
                    dy = connection.line.bounds[1] - edge_line.bounds[1]
                    log.info("new edge_poly {0}, edge_line {1}"
                             .format(to_string(edge_poly), to_string(edge_line)))

                assert (dx % 10 == 0 and dy % 10 == 0), \
                    "Should be grid aligned but is not ({dx}, {dy})" \
                        .format(dx=dx, dy=dy)

                test_polygon = aagen.geometry.translate(polygon, dx, dy)
                if not edge_poly.is_empty:
                    test_polygon = aagen.geometry.union(
                        test_polygon,
                        aagen.geometry.translate(edge_poly, dx, dy))
                log.info("test_polygon: {0}".format(to_string(test_polygon)))
                trim_polygon = aagen.geometry.trim(test_polygon,
                                                   self.conglomerate_polygon,
                                                   connection.polygon)
                if trim_polygon is None:
                    log.info("Polygon trimmed to nothing!")
                    continue
                cr = self.make_candidate_region((dx, dy), # TODO
                                                test_polygon, trim_polygon)
                if cr is not None: # TODO
                    log.info("Found a match at ({x}, {y})"
                             .format(x=dx, y=dy))
                    candidate_regions.append(cr)

        log.info("Found {0} candidate regions".format(len(candidate_regions)))
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
                  .format(to_string(trim_polygon),
                          to_string(self.conglomerate_polygon)))
        shared_walls = (trim_polygon.length + wall_delta) / 2
        if shared_walls < 5:
            log.info("Candidate only shares {0}' of walls - not valid!"
                     .format(shared_walls))
            return None

        return Candidate_Region(offset, trim_polygon, conn_set,
                                amount_truncated, shared_walls)


    def construct_intersection(self, connection, base_dir, exit_dir_list,
                               exit_width, exit_helper=None):
        """Call aagen.geometry.construct_intersection() to construct a
        candidate intersection, then do the validation necessary to make it
        actually work with the existing map.

        By default, constructs an OPEN connection at each exit from the
        intersection. If you want more nuanced behavior, you can pass an
        exit_helper function which has the following signature:

        def exit_helper(exit_dir, exit_line, region)

        The exit helper function will be called for each possible exit,
        and can return either an appropriately constructed Connection or None.

        Returns (region, [new_conn1, new_conn2, ...])
        """
        (polygon, exit_dict) = aagen.geometry.construct_intersection(
            connection.line, base_dir, exit_dir_list, exit_width)

        candidate = self.try_region_as_candidate(polygon, connection)

        if not candidate:
            log.error("No valid candidate for intersection") # TODO
            return (None, []) # TODO

        region = Region(Region.PASSAGE, candidate.polygon)
        region.add_connection(connection)

        if exit_helper is None:
            # Default helper function
            def exit_helper(exit_dir, exit_line, region):
                # Don't construct a connection if it would enter mapped space.
                if (self.conglomerate_polygon.boundary.contains(exit_line) or
                    self.conglomerate_polygon.boundary.overlaps(exit_line)):
                    return None
                return Connection(Connection.OPEN, exit_line, region,
                                  exit_dir)

        conns = []
        for (exit_dir, exit_line) in exit_dict.items():
            # Check for trimming
            if not region.polygon.boundary.contains(exit_line):
                continue
            conn = exit_helper(exit_dir, exit_line, region)
            if conn:
                conns.append(conn)

        self.add_region(region)

        return (region, conns)


class MapElement(object):
    """Abstract parent class for any object placed onto the DungeonMap"""

    _ids = count(0)

    def __init__(self, polygon):
        self.id = self._ids.next()
        self.polygon = aagen.geometry.polygon(polygon)
        self.tentative = True


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
            log.info("Room {0} has no open walls at all?"
                     .format(self))
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


class CandidateConnection(MapElement):
    """Model class for temporary objects representing potiential locations
    for a Connection.
    """

    def __init__(self, line, polygon, dir, parent_region):
        super(CandidateConnection, self).__init__(polygon)

        self.line = line
        self.dir = dir
        self.region = parent_region

        log.debug("Constructed {0}".format(self))

    def __repr__(self):
        return ("<CandidateConnection {0}: line {1}, poly {2}, dir {3}>"
                .format(self.id, to_string(self.line), to_string(self.polygon),
                        self.dir))


class Connection(MapElement):
    """Model class. Represents a connection between two adjacent Region objects,
    such as a door or archway. Modeled as a line segment which corresponds to
    the adjacent edge shared by the two Regions.

    A Connection is always aligned to the grid (vertically, horizontally, or
    diagonally) and always has a width which is either 5' or a multiple of 10'.

    A Connection that only has one Region is "incomplete" and forms a point for
    additional expansion/exploration of the dungeon.
"""

    # Kinds of connections
    OPEN = "Open"
    DOOR = "Door"
    SECRET = "Secret Door"
    ONEWAY = "One-Way Door"
    ARCH = "Arch"
    __kinds = [OPEN, DOOR, SECRET, ONEWAY, ARCH]

    def __init__(self, kind, line_coords, regions=None, dir=None):
        """Construct a Connection along the given edge"""
        assert kind in Connection.__kinds
        self.kind = kind

        self.line = aagen.geometry.line(line_coords)
        line_coords = (self.line.coords[0], self.line.coords[-1])
        assert self.line.length > 0

        log.info("Creating Connection ({kind}) along {line}"
                 .format(kind=kind, line=to_string(self.line)))

        self.direction = Direction.normal_to(line_coords)
        if dir is not None:
            if self.direction.angle_from(dir) > 90:
                self.direction = self.direction.rotate(180)
            if self.direction.angle_from(dir) > 45:
                log.warning("Angle between normal {0} and requested {1} "
                            "directions is too great: {2}!"
                            .format(self.direction, dir,
                                    self.direction.angle_from(dir)))

        # TODO remove this?
        (poly1, _) = aagen.geometry.sweep(self.line, self.direction, 10)
        assert poly1.is_valid
        (poly2, _) = aagen.geometry.sweep(self.line, self.direction.rotate(-45),
                                          10)
        (poly3, _) = aagen.geometry.sweep(self.line, self.direction.rotate(45),
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

        # TODO if dir == None and len(regions) == 1, make sure that
        # the derived normal direction points AWAY from the Region?

        self.set_kind(kind)

        log.debug("Constructed {0}".format(self))
        return


    def set_kind(self, kind):
        assert kind in Connection.__kinds
        self.kind = kind

        # Add helper polygons for drawing
        start = self.line.boundary[0]
        mid = self.line.interpolate(self.line.length / 2)
        mid1 = self.line.interpolate(2)
        mid2 = self.line.interpolate(self.line.length - 2)
        end = self.line.boundary[1]
        sub_line = aagen.geometry.line(mid1, mid2)
        left = sub_line.parallel_offset(1.5, 'left')
        right = sub_line.parallel_offset(1.5, 'right')
        if kind == Connection.DOOR:
            self.draw_lines = [self.line,
                               aagen.geometry.line_loop(list(left.coords) +
                                                        list(right.coords))]
        elif kind == Connection.ARCH:
            self.draw_lines = [aagen.geometry.line(start, mid1),
                               aagen.geometry.line(mid2, end),
                               aagen.geometry.line(left.boundary[0],
                                                   right.boundary[1]),
                               aagen.geometry.line(left.boundary[1],
                                                   right.boundary[0])]
        elif kind == Connection.OPEN:
            self.draw_lines = []
        elif kind == Connection.ONEWAY:
            (door_poly, _) = aagen.geometry.sweep(sub_line,
                                                  self.direction.rotate(180),
                                                  1.5)
            door_ring = aagen.geometry.line_loop(door_poly.exterior.coords)
            arrow_len = 4 if self.direction.is_cardinal() else 6
            arrowhead_len = 3 if self.direction.is_cardinal() else 2
            arrow_point = aagen.geometry.translate(mid, self.direction,
                                                   arrow_len)
            arrow_line1 = aagen.geometry.point_sweep(arrow_point,
                                                     self.direction.rotate(135),
                                                     arrowhead_len)
            arrow_line2 = aagen.geometry.point_sweep(arrow_point,
                                                     self.direction.rotate(225),
                                                     arrowhead_len)
            self.draw_lines = [self.line, door_ring,
                               aagen.geometry.line(mid, arrow_point),
                               arrow_line1, arrow_line2]
        elif kind == Connection.SECRET:
            # Construct an "S" consisting of two 3/4 circles
            circle1 = (aagen.geometry.translate(mid, self.direction, 2)
                       .buffer(2, resolution=8))
            # The circle consists of 33 points counterclockwise from (2, 0)
            arc1 = aagen.geometry.line(circle1.exterior.coords[16:] +
                                       circle1.exterior.coords[0:8])
            arc1 = aagen.geometry.rotate(arc1, self.direction)
            circle2 = (aagen.geometry.translate(mid, self.direction, -2)
                       .buffer(2, resolution=8))
            arc2 = aagen.geometry.line(circle2.exterior.coords[0:24])
            arc2 = aagen.geometry.rotate(arc2, self.direction)
            self.draw_lines = [self.line, arc1, arc2]
        else:
            raise LookupError("Don't know how to define draw_lines for {0}"
                              .format(kind))


    def __repr__(self):
        return ("<Connection {id}: {kind} at {loc} to {dir}>"
                .format(id=self.id, kind=self.kind,
                        loc=aagen.geometry.bounds_str(self.polygon),
                        areas=self.regions, dir=self.direction))


    def size(self):
        """Return the size ("width") of this connection"""
        return ((self.line.bounds[2] - self.line.bounds[0]) +
                (self.line.bounds[3] - self.line.bounds[1]))


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
            #                                     self.direction, 10))
            #    if not extension.intersects(region.polygon):
            #        # Try growing in the reverse direction
            #        extension = aagen.geometry.sweep(self.base_line,
            #                                         self.direction, -10))
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
