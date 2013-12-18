#!/usr/bin/env python
# DungeonGenerator - the Controller for our dungeon generator
#
# This controller class implements all of the random dungeon generation
# logic and instructs the DungeonMap as to what new Regions and
# Connections to add.

import pygame
import logging
import random
import math
from .map import DungeonMap, Region, Connection, Decoration
from .display import DungeonDisplay
from .geometry import to_string
import aagen.geometry
from aagen.direction import Direction

log = logging.getLogger(__name__)

def d4():
    roll = random.randint(1, 4)
    log.info("d4 roll: {0}".format(roll))
    return roll


def d20():
    roll = random.randint(1, 20)
    log.info("d20 roll: {0}".format(roll))
    return roll


def filtered(l, key, epsilon=0):
    """Combination of sorted() and filter().
    Sorts based on the given criterion, then discards any list elements whose
    value for this criterion is worse than the best element by more than
    the given epsilon.
    """
    new_l = sorted(l, key=key)
    best = key(new_l[0])
    for i in range(0, len(new_l)):
        if key(new_l[i]) > best + epsilon:
            break
    new_l = new_l[:i+1]
    return new_l


class DungeonGenerator:
    """Controller class to generate the dungeon map"""

    def __init__(self, dungeon_map, seed=None):
        self.dungeon_map = dungeon_map

        if seed is None:
            seed = random.randint(0, 2 ** 31)
        print("Random seed is {0}".format(seed))
        random.seed(seed)

        log.info("Initialized {0}".format(self))

        if len(self.dungeon_map.regions) != 0:
            print("Using existing map.")
            return

        self.step_number = 0

        print("Generating new dungeon!")
        log.info("Adding initial entrance stairs")
        stairs_coords = [(0, 0), (0, -20), (10, -20), (10, 0)]
        roll = d4()
        if True: #roll == 1:
            pass
        #elif roll == 2:
        #    stairs_coords = rotate(stairs_coords, 90)
        #elif roll == 3:
        #    stairs_coords = rotate(stairs_coords, 180)
        #elif roll == 4:
        #    stairs_coords = rotate(stairs_coords, -90)
        stairs = Region(Region.PASSAGE, stairs_coords)
        stairs.add_decoration(Decoration.Stairs((5, -10), (10, 20),
                                                Direction.N))
        dungeon_map.add_region(stairs)

        stairs_to_room = Connection(Connection.OPEN,
                                    [stairs_coords[0], stairs_coords[3]],
                                    stairs, Direction.N)
        dungeon_map.add_connection(stairs_to_room)
        log.info("Adding initial random room adjacent to stairs")
        self.generate_room(Region.ROOM, stairs_to_room)


    def __str__(self):
        return ("<DungeonGenerator: with map {0}>"
                .format(self.dungeon_map))


    def print_roll(self, roll, string):
        print("{roll}\t{string}".format(roll=roll, string=string))


    def continue_passage(self, connection):
        """Continue a passage from the given Connection.
        """

        print("Rolling for passage continuation from {0}".format(connection))

        roll = d20()

        if roll <= 2:
            self.print_roll(roll, "Passage continues straight for 60 feet")
            self.extend_passage(connection, 60)
            return
        elif roll <= 5:
            self.print_roll(roll, "There is a door here")
            self.generate_door_in_passage(connection)
            return
        elif roll <= 10:
            self.print_roll(roll, "The passage branches; each branch "
                            "continues another 30 feet")
            new_conns = self.generate_side_passage(connection)
            for conn in new_conns:
                self.extend_passage(conn, 30)
            return
        elif roll <= 13:
            self.print_roll(roll, "Passage turns then continues 30 feet")
            new_conn = self.turn_passage(connection)
            self.extend_passage(new_conn, 30)
            return
        elif roll <= 16:
            self.print_roll(roll, "Passage enters a chamber")
            connection.set_kind(Connection.ARCH)
            self.generate_room(Region.CHAMBER, connection)
            return
        elif roll <= 17:
            self.print_roll(roll, "There are stairs here")
            # TODO
        elif roll <= 18:
            self.print_roll(roll, "Passage dead-ends - check for secret doors")
            # TODO
        elif roll <= 19:
            self.print_roll(roll, "A trap or other oddity, then the passage "
                            "continues for 30 feet")
            # TODO trick/trap
            self.extend_passage(connection, 30)
            return
        else:
            self.print_roll(roll, "A monster is here - roll again for passage "
                            "continuation")
            # TODO monster
            self.continue_passage(connection)
            return

        # TODO
        log.info("Rerolling")
        self.continue_passage(connection)


    def generate_door_in_passage(self, connection):
        """
        Construct a doorway(s) (side door or end ahead) from a passageway.
        """
        print("Rolling door(s) from the passage...")

        base_dir = connection.direction
        exit_dirs = set([base_dir])
        door_ahead = False

        # We can generate anywhere from 1 to 3 doors (left / right / ahead).
        while True:
            roll = d20()
            if roll <= 6:
                self.print_roll(roll, "Door to the left")
                exit_dirs.add(base_dir.rotate(90))
            elif roll <= 12:
                self.print_roll(roll, "Door to the right")
                exit_dirs.add(base_dir.rotate(-90))
            else:
                self.print_roll(roll, "Door ahead")
                door_ahead = True
                # As soon as we hit a door ahead, stop rerolling
                break

            # Should we generate more doors?
            roll = d20()
            if (3 <= roll and roll <= 5):
                self.print_roll(roll, "Roll again")
            else:
                self.print_roll(roll, "No more doors")
                break

        (polygon, exit_dict) = aagen.geometry.construct_intersection(
            connection.line, base_dir, exit_dirs, 10)
        region = Region(Region.PASSAGE, polygon)
        region.add_connection(connection)

        forward_conn = None
        for (exit_dir, exit_line) in exit_dict.items():
            # If an "ahead" door is not generated, passage continues
            if exit_dir == base_dir and not door_ahead:
                conn = Connection(Connection.OPEN, exit_line, region, exit_dir)
                forward_conn = conn
            else:
                # TODO - need to reduce exit_line size to 10' if passage
                # was wider than 10' to begin with.
                conn = Connection(Connection.DOOR, exit_line, region, exit_dir)

        self.dungeon_map.add_region(region)
        # If an "ahead" door is not generated, passage continues
        if forward_conn:
            self.extend_passage(forward_conn, 30)


    def generate_space_beyond_door(self, connection):
        """Randomly generate the Region beyond the given connection.
        """
        print("The door ({0}) opens...".format(connection))

        roll = d20()

        if roll <= 4:
            self.print_roll(roll, "The door opens into a parallel passage "
                            "continuing for 30 feet in each direction, "
                            "or possibly a 10x10 room...")
            # TODO
        elif roll <= 8:
            self.print_roll(roll, "A passage continues 30 feet ahead")
            self.extend_passage(connection, 30)
            return
        elif roll <= 10:
            self.print_roll(roll, "A passage at a 45-degree angle to the left "
                            "or right")
            self.extend_passage(connection, 30,
                                [connection.direction.rotate(45),
                                 connection.direction.rotate(-45)])
            return
        elif roll <= 11:
            self.print_roll(roll, "A passage at a 45-degree angle to the right "
                            "or left")
            self.extend_passage(connection, 30,
                                [connection.direction.rotate(-45),
                                 connection.direction.rotate(45)])
            return
        elif roll <= 18:
            self.print_roll(roll, "The door opens into a room")
            self.generate_room(Region.ROOM, connection)
            return
        elif roll <= 20:
            self.print_roll(roll, "The door opens into a chamber")
            self.generate_room(Region.CHAMBER, connection)
            return

        # TODO
        log.info("Rerolling...")
        return self.generate_space_beyond_door(connection)


    def generate_side_passage(self, connection):
        """Construct an intersection between the current passage and one or
        more side passages. Returns a list of Connections (with a new Region
        implicitly shared between them).
        """
        print("A side passage branches off...")
        base_dir = connection.direction

        roll = d20()

        if roll <= 2:
            self.print_roll(roll, "It branches to the left")
            dirs = [base_dir, base_dir.rotate(90)]
        elif roll <= 4:
            self.print_roll(roll, "It branches to the right")
            dirs = [base_dir, base_dir.rotate(-90)]
        elif roll <= 5:
            self.print_roll(roll, "It branches 45 degrees to the left")
            dirs = [base_dir, base_dir.rotate(45)]
        elif roll <= 6:
            self.print_roll(roll, "It branches 45 degrees to the right")
            dirs = [base_dir, base_dir.rotate(-45)]
        elif roll <= 7:
            self.print_roll(roll, "It branches 135 degrees to the left")
            dirs = [base_dir, base_dir.rotate(135)]
        elif roll <= 8:
            self.print_roll(roll, "It branches 135 degrees to the right")
            dirs = [base_dir, base_dir.rotate(-135)]
        elif roll <= 9:
            self.print_roll(roll, "It curves 45 degrees to the left")
            # TODO curve
            dirs = [base_dir, base_dir.rotate(45)]
        elif roll <= 10:
            self.print_roll(roll, "It curves 45 degrees to the right")
            # TODO curve
            dirs = [base_dir, base_dir.rotate(-45)]
        elif roll <= 13:
            self.print_roll(roll, "A T-junction")
            dirs = [base_dir.rotate(-90), base_dir.rotate(90)]
        elif roll <= 15:
            self.print_roll(roll, "A Y-junction")
            dirs = [base_dir.rotate(-45), base_dir.rotate(45)]
        elif roll <= 19:
            self.print_roll(roll, "A four-way intersection")
            dirs = [base_dir, base_dir.rotate(-90), base_dir.rotate(90)]
        else:
            self.print_roll(roll, "An X-junction")
            # TODO - less faithful to the original tables, but perhaps more
            # interesting, would be to treat this as a skewed four-way
            # intersection, i.e., between a cardinal and a non-cardinal passage
            if base_dir.is_cardinal():
                # The current passage ends and all four parts of the X branch
                dirs = [base_dir.rotate(45), base_dir.rotate(-45),
                        base_dir.rotate(135), base_dir.rotate(-135)]
            else:
                # Same as a four-way intersection, just oriented non-cardinally
                dirs = [base_dir, base_dir.rotate(90), base_dir.rotate(-90)]

        new_width = self.roll_passage_width()

        (polygon, exit_dict) = aagen.geometry.construct_intersection(
            connection.line, base_dir, dirs, new_width)

        region = Region(Region.PASSAGE, polygon)
        region.add_connection(connection)
        conns = [Connection(Connection.OPEN, exit_line, region, exit_dir) for
                 (exit_dir, exit_line) in exit_dict.items()]
        self.dungeon_map.add_region(region)
        return conns


    def roll_passage_width(self):
        print("Checking passage width...")

        roll = d20()

        if roll <= 12:
            self.print_roll(roll, "10 feet wide")
            width = 10
        elif roll <= 16:
            self.print_roll(roll, "20 feet wide")
            width = 20
        elif roll <= 17:
            self.print_roll(roll, "30 feet wide")
            width = 30
        elif roll <= 18:
            self.print_roll(roll, "5 feet wide")
            # TODO - some of our math assumes a 10' minimum...
            #width = 5
            width = 10
        else:
            self.print_roll(roll, "A special passage!")
            # TODO
            return self.roll_passage_width()

        return width


    def turn_passage(self, connection):
        """Roll for a passage turning. Returns the new Connection that results
        and implicitly the new Region that was created.
        """
        print("Generating a turn in the passage...")

        roll = d20()

        base_dir = connection.direction

        if roll <= 8:
            self.print_roll(roll, "It turns 90 degrees to the left")
            new_dir = base_dir.rotate(90)
        elif roll <= 9:
            self.print_roll(roll, "It turns 45 degrees to the left")
            new_dir = base_dir.rotate(45)
        elif roll <= 10:
            self.print_roll(roll, "It turns 135 degrees to the left")
            new_dir = base_dir.rotate(135)
        elif roll <= 18:
            self.print_roll(roll, "It turns 90 degrees to the right")
            new_dir = base_dir.rotate(-90)
        elif roll <= 19:
            self.print_roll(roll, "It turns 45 degrees to the right")
            new_dir = base_dir.rotate(-45)
        elif roll <= 20:
            self.print_roll(roll, "It turns 135 degrees to the right")
            new_dir = base_dir.rotate(-135)

        width = self.roll_passage_width()

        log.info("Passage turns from {0} to {1} and becomes {2} wide"
                 .format(base_dir, new_dir, width))
        (poly, exit_dict) = aagen.geometry.construct_intersection(
            connection.line, base_dir, [new_dir], width)
        new_line = exit_dict[new_dir]

        if poly.area > 0:
            region = Region(Region.PASSAGE, poly)
            region.add_connection(connection)
            new_conn = Connection(Connection.OPEN, new_line, region, new_dir)
            self.dungeon_map.add_region(region)
            return new_conn
        else:
            log.warning("Corner is already valid!")
            connection.direction = new_dir
            return connection


    def generate_room(self, kind, connection, shape=None):
        """Add the provided shape to the map, or randomly generate one"""
        assert isinstance(connection, Connection)

        while shape is None:
            print("Generating a random room...")

            # Roll on Table V:
            polygons = self.roll_room_shape_and_size(kind)
            log.info("Set contains {0} different shapes"
                     .format(len(polygons)))

            candidate_regions = self.dungeon_map.find_options_for_region(
                polygons, connection)
            selected_region = self.select_best_candidate(candidate_regions)
            if selected_region.amount_truncated > 0:
                print("Room is truncated a bit... oh well")
            shape = selected_region.polygon

        # Construct the region and add it to the map
        new_region = Region(kind, shape)
        self.dungeon_map.add_region(new_region)
        connection.add_region(new_region)

        # Roll for new connections leaving this region
        (num_exits, exit_kind) = self.roll_room_exit_count(new_region)

        if num_exits > 0:
            # TODO: num_exits -= len(new_region.connections) ??
            exit_base_dir = connection.direction
            # TODO use actual adjacency direction?
            for i in range(0, num_exits):
                self.generate_room_exit(new_region, exit_kind, exit_base_dir)
        else:
            print("No normal exits were generated - check for secret doors")
            for direction in Direction.CARDINAL:
                candidates = self.dungeon_map.find_options_for_connection(
                    10, new_region, direction)
                for candidate in candidates:
                    roll = d20()
                    if roll <= 5:
                        self.print_roll(roll, "Secret door here!")
                        conn = Connection(Connection.SECRET, candidate.line,
                                          new_region, direction)
                        new_region.add_connection(conn)
                        self.dungeon_map.add_connection(conn)
                    else:
                        self.print_roll(roll, "No secret door here")


    def select_best_connection(self, candidate_connections):
        """Choose the best option amongst the provided candidate connections.
        """
        if len(candidate_connections) == 0:
            raise RuntimeError("No candidate connections were found!")

        log.info("Choosing the best placement for a connection...")

        # Sort by least additional area added to the region
        # (only really an issue when connecting to an unusually-shaped room!)
        # and discard those that don't make the cut
        candidate_connections = filtered(candidate_connections,
                                         lambda r: r.polygon.area)

        # Randomly choose amongst the rest
        return random.choice(candidate_connections)


    def select_best_candidate(self, candidate_regions):
        """Choose the best option amongst the provided candidates"""
        if len(candidate_regions) == 0:
            raise RuntimeError("No candidate regions were found!")

        log.info("Choosing the best placement for a region...")

        # Simulating human judgement... consider the following:

        # A perfect fit:
        # 1) Covers the connection baseline fully.
        # 2) Does not intersect any existing Region.
        #
        # If we can satisfy both of these, that's always preferred.
        # Either or both may be unsatisfiable:
        # 1) may not be possible if the Region is fundamentally different
        #    from the Connection in shape (e.g., diagonal vs. orthogonal,
        #    straight vs curved edges, etc.). In this case we must consider
        #    alternative positions that come reasonably close to the Connection
        #    (and if selected, we will add a short "hallway" to the Region's
        #    polygon so that it will fully cover the connection baseline.)
        #    We DO NOT prioritize the "best" partial coverage as this is an
        #    inherently fuzzy number - we select all that are "close enough"
        #    and use other criteria to choose the best one.
        # 2) will frequently be impossible as the map becomes more complete.
        #    We have two possible approaches to consider:
        #    a) Truncate the provided Region to fit the space available.
        #    b) Reject the provided region and generate a new one to try.
        #    For "basic" rectangular rooms, option a) often provides good enough
        #    results, but for more unusual rooms option b) is preferred.
        #    For option b) there are two possible approaches as well:
        #      b1) Generate a smaller room of the same unusual type and try it
        #      b2) Generate a new room completely at random
        #    TODO decide which of these we want to prefer

        # Once we've found one or more candidates that satisfy the above
        # criteria (as best as possible) we can choose amongst them based on
        # more subjective and aesthetic criteria. Here are a few to consider:
        # 3) Sharing walls with other existing regions makes for a more compact
        #    dungeon layout
        # 4) Completing multiple incomplete connections with a single Region
        #    helps keep the dungeon interconnected and not too linear.
        # 5) Having "near misses" with incomplete connections may make it
        #    more difficult to explore from these connections later.


        # 1) Out of all the candidates with minimal truncation,
        # 2) prefer the one that shares the most wall space with
        #    the existing dungeon (favor compactness),
        # 3) and of those, prefer the one that resolves the most
        #    existing unresolved Connections
        # We accomplish this by repeated sorting starting with the
        # lowest-priority criterion

        # Greatest number of Connections shared with existing:
        candidate_regions = sorted(candidate_regions,
                                   key=lambda r: len(r.connections),
                                   reverse=True)
        log.debug("Candidates: {0}"
                 .format("\n".join(str(r) for r in candidate_regions)))

        # Most amount of wall space shared with existing regions:
        candidate_regions = sorted(candidate_regions,
                                   key=lambda r: round(r.shared_walls),
                                   reverse=True)
        log.debug("Candidates: {0}"
                 .format("\n".join(str(r) for r in candidate_regions)))

        # Least truncation - discard all those that don't make the cut!
        candidate_regions = filtered(candidate_regions,
                                     key=lambda r: round(r.amount_truncated),
                                     epsilon=50)
        log.debug("Candidates: {0}"
                 .format("\n".join(str(r) for r in candidate_regions)))

        selected_region = random.choice(candidate_regions)
        log.debug("Selected candidate {0}".format(selected_region))
        return selected_region


    def roll_room_shape_and_size(self, kind):
        """Roll a random shape and size for a Room or Chamber.
        Returns a set of sequences of polygon coordinates"""
        print("Rolling shape and size for a {0} (d20)".format(kind))

        roll = d20()

        # TODO force unusual rooms:
        #return self.roll_room_unusual_shape_and_size()

        if roll <= 2:
            (w, h) = (10, 10) if kind == Region.ROOM else (20, 20)
        elif roll <= 4:
            (w, h) = (20, 20)
        elif roll <= 6:
            (w, h) = (30, 30)
        elif roll <= 8:
            (w, h) = (40, 40)
        elif roll <= 10:
            (w, h) = (10, 20) if kind == Region.ROOM else (20, 30)
        elif roll <= 13:
            (w, h) = (20, 30)
        elif roll <= 15:
            (w, h) = (20, 40) if kind == Region.ROOM else (30, 50)
        elif roll <= 17:
            (w, h) = (30, 40) if kind == Region.ROOM else (40, 60)
        else:
            self.print_roll(roll, "Something unusual!")
            return self.roll_room_unusual_shape_and_size()

        self.print_roll(roll, "A {w}x{h} {kind}".format(w=w, h=h, kind=kind))

        return aagen.geometry.rectangle_list(w, h)


    def roll_room_unusual_shape_and_size(self):

        # First we roll the area:
        area = self.roll_room_unusual_size()

        print("Generating unusual shape (d20)...")

        roll = d20()

        if roll <= 5:
            self.print_roll(roll, "A circle")
            # TODO pool/well/shaft
            return aagen.geometry.circle_list(area)
            # TODO don't allow circular rooms to be truncated
        elif roll <= 8:
            self.print_roll(roll, "A triangle")
            return aagen.geometry.triangle_list(area)
        elif roll <= 11:
            self.print_roll(roll, "A trapezoid")
            return aagen.geometry.trapezoid_list(area)
        elif roll <= 13:
            self.print_roll(roll, "Something odd...")
            # TODO
        elif roll <= 15:
            self.print_roll(roll, "An oval")
            return aagen.geometry.oval_list(area)
            # TODO don't allow oval rooms to be truncated
        elif roll <= 17:
            self.print_roll(roll, "A hexagon")
            return aagen.geometry.hexagon_list(area)
        elif roll <= 19:
            self.print_roll(roll, "An octagon")
            return aagen.geometry.octagon_list(area)
        else:
            self.print_roll(roll, "A cave?")
            # TODO

        log.info("Rerolling")
        return self.roll_room_unusual_shape_and_size()


    def roll_room_unusual_size(self):
        print("Generating unusual room size (d20)...")

        roll = d20()

        if roll <= 3:
            size = 500
        elif roll <= 6:
            size = 900
        elif roll <= 8:
            size = 1300
        elif roll <= 10:
            size = 2000
        elif roll <= 12:
            size = 2700
        elif roll <= 14:
            size = 3400
        else:
            self.print_roll(roll, "Add 2000 square feet and roll again!")
            size = 2000 + self.roll_room_unusual_size()

        if roll <= 14:
            self.print_roll(roll, "{size} square feet"
                            .format(roll=roll, size="{:,}".format(size)))
        else:
            print("+ 2,000 = {size} square feet"
                  .format(size="{:,}".format(size)))

        return size


    def roll_room_exit_count(self, room):
        print("Generating number of exits...")

        roll = d20()

        exit_kind = (Connection.DOOR if room.kind == Region.ROOM
                     else Connection.ARCH)

        if roll <= 3:
            exits = self.exits_if_area_less_than(roll, room, 600, 1, 2)
        elif roll <= 6:
            exits = self.exits_if_area_less_than(roll, room, 600, 2, 3)
        elif roll <= 9:
            exits = self.exits_if_area_less_than(roll, room, 600, 3, 4)
        elif roll <= 12:
            exits = self.exits_if_area_less_than(roll, room, 1200, 0, 1)
        elif roll <= 15:
            exits = self.exits_if_area_less_than(roll, room, 1600, 0, 1)
        elif roll <= 18:
            exits = d4()
            self.print_roll(roll, "1-4 exits: got {0} exits".format(exits))
        else:
            exits = 1
            exit_kind = (Connection.ARCH if room.kind == Region.ROOM
                         else Connection.DOOR)
            self.print_roll(roll, "1 exit of unusual type ({0})".format(exit_kind))

        log.info("Room has {0} {1}s".format(exits, exit_kind))
        return (exits, exit_kind)


    def exits_if_area_less_than(self, roll, region, area_filter, less, more):
        """Helper function for roll_room_exit_count()"""
        area = region.polygon.area
        log.debug("Room area is {0}".format(area))

        if area <= area_filter:
            self.print_roll(roll, "No larger than {filter} square feet, "
                            "so it has {exits} exits"
                            .format(filter=area_filter, exits=less))
            return less
        else:
            self.print_roll(roll, "Larger than {filter} square feet, "
                            "so it has {exits} exits"
                            .format(filter=area_filter, exits=more))
            return more


    def generate_room_exit(self, room, exit_kind, entrance_dir):
        exit_dir = self.roll_room_exit_location(entrance_dir)
        log.info("Generating a {0} in direction {1} from {2}"
                 .format(exit_kind, exit_dir, room))

        if exit_kind == Connection.DOOR:
            width = 10
        elif exit_kind == Connection.ARCH:
            width = self.roll_passage_width()
        else:
            raise RuntimeError("Not sure how to generate a room exit as {0}"
                               .format(exit_kind))

        # Try a full-width exit, and if that fails,
        # successively reduce the exit width:
        exit_width = width
        conn = None
        while exit_width > 0:
            candidates = self.dungeon_map.find_options_for_connection(
                exit_width, room, exit_dir)
            log.debug(candidates)
            if len(candidates) > 0:
                break
            if exit_width > 10:
                log.warning("Couldn't find any options for a {0}' exit - "
                            "retry with reduced width".format(exit_width))
            exit_width -= 10

        if len(candidates) == 0:
            print("If there's no available space that doesn't already lead to "
                  "an already mapped area, it might be a secret or a one-way "
                  "door, or else we should just try a different wall...")
            roll = d20()
            if roll <= 5:
                self.print_roll(roll, "There's a secret door")
                exit_kind = Connection.SECRET
                width = 10
                new_only = False
            elif roll <= 10:
                self.print_roll(roll, "It's a one-way door")
                exit_kind = Connection.ONEWAY
                width = 10
                new_only = False
            else:
                self.print_roll(roll, "Let's try the opposite direction")
                exit_dir = exit_dir.rotate(180)
                new_only = True # TODO - try new_only, then try not if fails

            # TODO refactor this...
            exit_width = width
            while exit_width > 0:
                candidates = self.dungeon_map.find_options_for_connection(
                    exit_width, room, exit_dir, new_only=new_only)
                log.debug(candidates)
                if len(candidates) > 0:
                    break
                exit_width -= 10

        if len(candidates) == 0:
            log.warning("Unable to generate this exit!")
            return None

        # For now just pick one at random:
        candidate = self.select_best_connection(candidates)
        room.polygon = aagen.geometry.union(room.polygon, candidate.polygon)
        self.dungeon_map.refresh_conglomerate()
        conn = Connection(exit_kind, candidate.line, room, exit_dir)
        room.add_connection(conn)
        self.dungeon_map.add_connection(conn)

        if exit_kind == Connection.ARCH:
            # Now construct the passage
            possible_directions = self.roll_passage_exit_directions(conn.direction)
            self.extend_passage(conn, 30, possible_directions)


    def roll_room_exit_location(self, base_direction):
        print("Generating exit location...")
        roll = d20()

        if base_direction.is_cardinal():
            if roll <= 7:
                direction = base_direction
                self.print_roll(roll, "Opposite the entrance ({0})"
                                .format(direction.name))
            elif roll <= 12:
                direction = base_direction.rotate(90)
                self.print_roll(roll, "To the left of the entrance ({0})"
                                .format(direction.name))
            elif roll <= 17:
                direction = base_direction.rotate(-90)
                self.print_roll(roll, "To the right of the entrance ({0})"
                                .format(direction.name))
            else:
                direction = base_direction.rotate(180)
                self.print_roll(roll, "On the same side as the entrance ({0})"
                                .format(direction.name))
        else:
            # Exits are always cardinally oriented...
            # Numbers below are picked arbitrarily to try and preserve the
            # "feel" of the above cardinal table, preferring forward over back.
            if roll <= 6:
                direction = base_direction.rotate(45)
                self.print_roll(roll, "Forward and left ({0})"
                                .format(direction.name))
            elif roll <= 12:
                direction = base_direction.rotate(-45)
                self.print_roll(roll, "Forward and right ({0})"
                                .format(direction.name))
            elif roll <= 16:
                direction = base_direction.rotate(135)
                self.print_roll(roll, "Back and left ({0})"
                                .format(direction.name))
            else:
                direction = base_direction.rotate(-135)
                self.print_roll(roll, "Back and right ({0})"
                                .format(direction.name))

        log.info("Exit direction: {0}".format(direction))

        return direction


    def roll_passage_exit_directions(self, base_direction):
        print("Generating exit direction for a passage...")
        roll = d20()

        if roll <= 16:
            self.print_roll(roll, "The passage goes straight {0}"
                            .format(base_direction.name))
            return [base_direction]
        elif roll <= 18:
            left = base_direction.rotate(45)
            right = base_direction.rotate(-45)
            self.print_roll(roll, "The passage goes 45 degrees left ({0}), or "
                            "if that doesn't work, 45 degrees right ({1})"
                            .format(left.name, right.name))
            return [left, right]
        else:
            left = base_direction.rotate(45)
            right = base_direction.rotate(-45)
            self.print_roll(roll, "The passage goes 45 degrees right ({0}), or "
                            "if that doesn't work, 45 degrees left ({1})"
                            .format(right.name, left.name))
            return [right, left]


    def extend_passage(self, connection, distance,
                       possible_directions=None,
                       allow_truncation=True,
                       allow_shortening=True):
        """Grow a passage from the given connection.
        Returns the resulting passage or None """

        if possible_directions is None:
            possible_directions = [connection.direction]

        # Order of preference:
        # 1) First possible direction, full distance, no truncation
        # 2) Second possible direction, full distance, no truncation
        # (continue over all possible directions)
        # (reduce distance by 10 if permitted, try all directions again)
        # If distance reduced to 0 and still no match found:
        # Reset to maximum distance, allow truncation, repeat all of the above

        (xmin, ymin, xmax, ymax) = connection.line.bounds
        for truncation in [False, True]:
            length = distance
            while length > 0:
                for direction in possible_directions:
                    if direction != connection.direction:
                        (fixup_poly, exit_dict) = (
                            aagen.geometry.construct_intersection(
                                connection.line, connection.direction,
                                [direction], connection.size()
                            ))
                        base_line = exit_dict[direction]
                    else:
                        base_line = connection.line
                        fixup_poly = aagen.geometry.polygon()
                    (polygon, endwall) = aagen.geometry.sweep(
                        base_line, direction, length,
                        connection.direction)
                    polygon = aagen.geometry.union(polygon, fixup_poly)
                    candidate = self.dungeon_map.try_region_as_candidate(
                        polygon, connection)
                    if candidate is not None:
                        if not truncation and candidate.amount_truncated > 0:
                            log.info("Truncated by {0} - not interested"
                                     .format(candidate.amount_truncated))
                            candidate = None
                    if candidate is not None:
                        selected = candidate
                    #candidate_regions = (
                    #    self.dungeon_map.find_options_for_region(
                    #        [coords], connection))
                    #if truncation:
                    #    # Truncation is OK, no filtering needed
                    #    filtered = candidate_regions
                    #else:
                    #    # We don't want truncated passages
                    #    filtered = []
                    #    for candidate in candidate_regions:
                    #        if candidate.amount_truncated == 0:
                    #            filtered.append(candidate)
                    #if len(filtered) > 0:
                        #selected = self.select_best_candidate(filtered)
                        new_region = Region(Region.PASSAGE,
                                            selected.polygon)
                        connection.add_region(new_region)
                        if selected.amount_truncated == 0:
                            # add Open connection to far end of passage if
                            # it doesn't collide with the geometry
                            if (aagen.geometry.intersect(
                                    endwall,
                                    self.dungeon_map.conglomerate_polygon)
                                .length == 0):
                                conn2 = Connection(Connection.OPEN,
                                                   endwall,
                                                   new_region,
                                                   direction)
                            else:
                                log.info("Not adding Open at end of passage {0}"
                                         "because it intersects the existing "
                                         "dungeon".format(to_string(endwall)))
                        self.dungeon_map.add_region(new_region)
                        return new_region
                    # No luck - try new direction?
                    pass
                # No luck - try reducing length?
                if allow_shortening:
                    length -= 10
                    log.info("No match found - trying reduced length ({0}')"
                             .format(length))
                else:
                    break
            # No luck - try allowing truncation?
            if not allow_truncation:
                break

        # No luck at all?
        log.warning("Unable to extend passage at all!")
        return None


    def step(self, connection=None):
        """Run another step of the dungeon generation algorithm, either
        starting from the specified connection or a random one"""

        self.step_number += 1

        print("\n\n\n----------Step {0}----------".format(self.step_number))
        self.dungeon_map.flush()
        log.info(self.dungeon_map)
        if connection is None:
            # Choose a connection at random
            options = self.dungeon_map.get_incomplete_connections()
            if (len(options) == 0):
                log.warning("Resetting map!")
                self.dungeon_map.__init__()
                self.__init__(self.dungeon_map)
                return
            connection = random.choice(options)

        log.info("Generating next step from {0}".format(connection))

        if (connection.kind == Connection.DOOR or
            connection.kind == Connection.SECRET or
            connection.kind == Connection.ONEWAY):
            self.generate_space_beyond_door(connection)
        elif (connection.kind == Connection.OPEN or
              connection.kind == Connection.ARCH):
            self.continue_passage(connection)
        else:
            raise NotImplementedError("No handling for {0} yet"
                                      .format(connection.kind))

