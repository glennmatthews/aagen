#!/usr/bin/env python
# Direction - a simple class representing a vector

import math
import logging

log = logging.getLogger(__name__)

class Direction:
    """Model class representing a compass direction (orthogonal or diagonal)
    in the dungeon.

    To make the math simpler (and make diagonal passages line up with the grid),
    we do not use Euclidean distance (length(1,1) = sqrt(2))
    but instead use Manhattan distance (length(1,1) = 2).

    N.B.: Since there are only eight valid Directions, generally you should not
    construct a new Direction instance but should instead use one of the various
    class getter methods.
"""

    ALL = []
    CARDINAL = []


    @classmethod
    def named(cls, name):
        for d in cls.ALL:
            if d.name == name:
                return d
        raise LookupError("No Direction named '{0}'".format(name))


    @classmethod
    def normal_to(cls, baseline):
        if hasattr(baseline, 'coords'):
            baseline = baseline.coords
        (x0, y0) = baseline[0]
        (x1, y1) = baseline[-1]
        degrees = round(math.degrees(math.atan2((x0 - x1), (y1 - y0))))
        return cls.angle(degrees)


    @classmethod
    def angle(cls, degrees):
        while degrees < (-180 + 22.5):
            degrees = degrees + 360
        while degrees > (180 + 22.5):
            degrees = degrees - 360
        for d in cls.ALL:
            if d.degrees == degrees:
                return d
            elif math.fabs(d.degrees - degrees) < 22.5:
                log.warning("Constraining angle {0} to grid --> {1}"
                            .format(degrees, d.degrees))
                return d
        raise LookupError("Unable to determine direction at angle {0}"
                          .format(degrees))


    name_to_vector = {
        "north": (0, 1),
        "northwest": (-0.5, 0.5),
        "west": (-1, 0),
        "southwest": (-0.5, -0.5),
        "south": (0, -1),
        "southeast": (0.5, -0.5),
        "east": (1, 0),
        "northeast": (0.5, 0.5)
    }

    def __init__(self, name):
        """Private constructor for Direction instances.
        New instances should only be created in the Direction module itself;
        all other modules should call one of the appropriate getter methods
        instead.
        """
        self.name = name
        self.vector = self.name_to_vector[name]
        self.degrees = math.degrees(math.atan2(self.vector[1],
                                               self.vector[0]))
        log.debug("Constructed {0}".format(self))


    def __getitem__(self, index):
        return self.vector[index]


    def __repr__(self):
        return("<Direction: {name}>".format(name=self.name))


    def __eq__(self, other):
        return self.name == other.name


    def __hash__(self):
        return hash(self.name)


    def rotate(self, degrees):
        """Construct a new Direction relative to this one"""
        return Direction.angle(self.degrees + degrees)


    def angle_from(self, other):
        """Magnitute of the angle between two Directions"""
        assert isinstance(other, Direction)
        angle = math.fabs(self.degrees - other.degrees)
        if angle > 180:
            angle = 360 - angle
        log.debug("Angle from {0} to {1} is {2}".format(self, other, angle))
        return angle


    def is_cardinal(self):
        return (self.vector[0] == 0 or self.vector[1] == 0)


# Create static instances for other modules to reference
Direction.N = Direction("north")
Direction.NW = Direction("northwest")
Direction.W = Direction("west")
Direction.SW = Direction("southwest")
Direction.S = Direction("south")
Direction.SE = Direction("southeast")
Direction.E = Direction("east")
Direction.NE = Direction("northeast")
Direction.ALL = [Direction.N, Direction.NW, Direction.W, Direction.SW,
                 Direction.S, Direction.SE, Direction.E, Direction.NE]
Direction.CARDINAL = [Direction.N, Direction.W, Direction.S, Direction.E]
