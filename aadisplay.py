#!/usr/bin/env python
# Dungeon_Display - the View for our dungeon generator
#
# Handles rendering of Dungeon_Map and its associated Regions and Connections.

import logging
import pygame
import math

from aamap import Dungeon_Map, Region, Connection, Decoration
from aamap import rotate

from shapely.geometry.point import Point
from shapely.geometry.linestring import LineString


log = logging.getLogger(__name__)

class Dungeon_Display:
    """Class to handle visual rendering of the map"""

    def __init__(self, dungeon_map, (w, h)=(None, None)):
        assert isinstance(dungeon_map, Dungeon_Map)
        if w is None:
            w = pygame.display.Info().current_w - 100
        if h is None:
            h = pygame.display.Info().current_h - 100
        self.surface = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.dungeon_map = dungeon_map
        log.debug("Initialized {0}".format(self))


    def __str__(self):
        return ("(Dungeon_Display: surface {0}, map {1})"
                .format(self.surface, self.dungeon_map))


    def resize_display(self, (w, h)):
        """Handle a window resize event by adjusting our display size"""
        self.surface = pygame.display.set_mode((w, h), pygame.RESIZABLE)


    def update_bounds(self, (display_w, display_h)=(None, None)):
        """Update the display position and scale prior to drawing the map"""
        log.debug("Recalculating map display bounds")
        # Get the extent of the dungeon
        (x0, y0, x1, y1) = self.dungeon_map.get_bounds()

        # Get the extent of the surface
        if display_w is None:
            (display_w, display_h) = self.surface.get_size()
        log.debug("Base parameters are {0}, {1}"
                  .format(self.dungeon_map.get_bounds(),
                          self.surface.get_size()))

        # Provide 10' of buffer around the edges of the map
        (x0, y0, x1, y1) = (x0 - 10, y0 - 10, x1 + 10, y1 + 10)

        # Figure out how much to scale to make the map fit the display
        map_w = (x1 - x0)
        map_h = (y1 - y0)
        xscale = display_w / map_w
        yscale = display_h / map_h
        self.display_scale = min(xscale, yscale)
        log.debug("Display scale ({0}, {1}) -> {2}"
                  .format(xscale, yscale, self.display_scale))

        # Center the dungeon in the display as needed
        if xscale < yscale:
            delta = (display_h / self.display_scale) - map_h
            y0 -= delta / 2
            y1 += delta / 2
        elif yscale < xscale:
            delta = (display_w / self.display_scale) - map_w
            x0 -= delta / 2
            x1 += delta / 2

        self.bounds = (x0, y0, x1, y1)

        log.debug("Display bounds are now {0}, scale is {1}"
                  .format(self.bounds, self.display_scale))


    def map_to_screen(self, coords):
        """Convert (x, y) or [(x0, y0), (x1, y1), ...] to the corresponding
        onscreen coordinates"""

        (x0, y0, x1, y1) = self.bounds

        # Note that the screen uses left-handed coordinates while the map
        # uses right-handed coordinates, so we flip the y axis when converting

        # Handle single point
        if isinstance(coords, Point):
            return self.map_to_screen((coords.x, coords.y))
        if type(coords) is tuple:
            (x, y) = coords
            return ((x - x0) * self.display_scale,
                    (y1 - y) * self.display_scale)
        # Handle list of points
        output_list = []
        for (x, y) in coords:
            output_list.append(((x - x0) * self.display_scale,
                                (y1 - y) * self.display_scale))
        log.debug("map {0} corresponds to screen {1}".format(coords, output_list))
        return output_list


    def screen_to_map(self, coords):
        """Convert screen coordinates to the corresponding map coordinates"""
        (x0, y0, x1, y1) = self.bounds

        (x, y) = coords

        # Note that the screen uses left-handed coordinates while the map
        # uses right-handed coordinates, so we flip the y axis when converting
        return ((x / self.display_scale) + x0,
                -(y / self.display_scale) + y1)


    def draw_background(self):
        """Draw the parts of the dungeon that underlay the grid"""
        log.debug("Drawing background")

        log.debug("Drawing 'rock' background")
        pygame.draw.rect(self.surface, (127, 127, 127), self.surface.get_rect())

        log.debug("Drawing Region contents")
        for region in self.dungeon_map.get_regions():
            coords = self.map_to_screen(region.get_coords())
            if region.kind == Region.ROOM:
                color = (255, 255, 240)
            elif region.kind == Region.CHAMBER:
                color = (255, 240, 255)
            elif region.kind == Region.PASSAGE:
                color = (240, 255, 255)
            else:
                raise LookupError("Unknown Region kind '{0}'"
                                  .format(region.kind))
            pygame.draw.polygon(self.surface, color, coords)

        log.debug("Drawing Connection contents")
        for conn in self.dungeon_map.get_connections():
            coords = self.map_to_screen(conn.get_poly_coords())
            if conn.kind == Connection.DOOR:
                if conn.is_incomplete():
                    color = (127, 140, 127)
                else:
                    color = (240, 255, 240)
            elif conn.kind == Connection.ARCH:
                if conn.is_incomplete():
                    color = (127, 127, 140)
                else:
                    color = (240, 240, 255)
            elif conn.kind == Connection.OPEN:
                if conn.is_incomplete():
                    color = (140, 127, 127)
                else:
                    color = (255, 240, 240)
            else:
                continue
            pygame.draw.polygon(self.surface, color, coords)


    def draw_grid(self):
        """Draw the 10' grid over the dungeon background"""
        log.debug("Drawing grid")
        (x0, y0, x1, y1) = self.bounds
        color = (191, 191, 191)

        (w, h) = self.surface.get_size()

        i = 10 * ((x0 + 9) // 10)
        while i < x1:
            (x, ignore) = self.map_to_screen((i, 0))
            pygame.draw.line(self.surface, color, (x, 0), (x, h), 1)
            i += 10

        j = 10 * ((y0 + 9) // 10)
        while j < y1:
            (ignore, y) = self.map_to_screen((0, j))
            pygame.draw.line(self.surface, color, (0, y), (w, y), 1)
            j += 10


    def draw_foreground(self):
        """Draw everything that displays over the dungeon grid"""
        log.debug("Drawing foreground")

        # Mark the origin point
        pygame.draw.polygon(self.surface, (255, 0, 0),
                            self.map_to_screen([(-3, -3), (-3, 3),
                                                (3, 3), (3, -3)]))


        for region in self.dungeon_map.get_regions():
            coords_list = region.get_wall_coords()
            for coords in coords_list:
                coords = self.map_to_screen(coords)
                color = (0, 0, 0)
                pygame.draw.lines(self.surface, color, False, coords, 2)

        for conn in self.dungeon_map.get_connections():
            centroid = self.map_to_screen((conn.line.centroid.x,
                                           conn.line.centroid.y))
            if True:
                # Draw the directional vectors of this connection for debugging
                endpoint1 = self.map_to_screen((conn.line.centroid.x + 7*conn.base_direction[0],
                                                conn.line.centroid.y + 7*conn.base_direction[1]))
                endpoint2 = self.map_to_screen((conn.line.centroid.x + 5*conn.grow_direction[0],
                                                conn.line.centroid.y + 5*conn.grow_direction[1]))
                pygame.draw.line(self.surface, (255, 0, 0),
                                 centroid, endpoint1, 3)
                pygame.draw.line(self.surface, (0, 255, 0),
                                 centroid, endpoint2, 2)

            color = (0, 0, 0)
            coords = self.map_to_screen(conn.get_poly_coords())
            if conn.kind == Connection.DOOR:
                pygame.draw.polygon(self.surface, (240, 255, 240),
                                    self.map_to_screen(conn.draw_lines.coords))
                pygame.draw.lines(self.surface, color, False,
                                  self.map_to_screen(conn.get_line_coords()), 2)
                pygame.draw.polygon(self.surface, color,
                                    self.map_to_screen(conn.draw_lines.coords),
                                    2)
            elif conn.kind == Connection.OPEN:
                pass
            elif conn.kind == Connection.ARCH:
                start = self.map_to_screen(conn.line.coords[0])
                open1 = self.map_to_screen(conn.line.interpolate(2))
                pygame.draw.line(self.surface, color, start, open1, 2)
                end = self.map_to_screen(conn.line.coords[-1])
                open2 = self.map_to_screen(conn.line.interpolate(
                    conn.line.length - 2))
                pygame.draw.line(self.surface, color, open2, end, 2)
            elif conn.kind == Connection.ONEWAY:
                pygame.draw.lines(self.surface, color, False,
                                  self.map_to_screen(conn.get_line_coords()), 2)
                # Draw the one-way door
                points = [(2, -1), (3,0), (2, 1), (3, 0),
                          (0,0), (0, 2), (-2, 2),
                          (-2, -2), (0, -2), (0,0)]
                points = rotate(points, conn.base_direction)
                coords = []
                for point in points:
                    coords.append((point[0] + conn.line.centroid.x,
                                   point[1] + conn.line.centroid.y))
                coords = self.map_to_screen(coords)
                pygame.draw.lines(self.surface, color, False, coords, 2)
                log.debug("One-way door: {0}".format(coords))
            elif conn.kind == Connection.SECRET:
                pygame.draw.lines(self.surface, color, False,
                                  self.map_to_screen(conn.get_line_coords()), 2)
                # Draw an S
                angle1a = math.radians(-90 + conn.base_direction.degrees)
                angle1b = math.radians(180 + conn.base_direction.degrees)
                angle2a = math.radians(90 + conn.base_direction.degrees)
                angle2b = math.radians(360 + conn.base_direction.degrees)
                point_1 = rotate((1.9, 0), conn.base_direction)
                point_2 = rotate((-1.9, 0), conn.base_direction)
                dx = conn.line.centroid.x
                dy = conn.line.centroid.y
                rect_1 = self.map_to_screen([(point_1[0] - 2 + dx,
                                              point_1[1] + 2 + dy),
                                             (point_1[0] + 2 + dx,
                                              point_1[1] - 2 + dy)])
                pygame.draw.arc(self.surface, color,
                                [rect_1[0][0],
                                 rect_1[0][1],
                                 rect_1[1][0] - rect_1[0][0],
                                 rect_1[1][1] - rect_1[0][1]],
                                angle1a, angle1b, 2)
                rect_2 = self.map_to_screen([(point_2[0] - 2 + dx,
                                              point_2[1] + 2 + dy),
                                             (point_2[0] + 2 + dx,
                                              point_2[1] - 2 + dy)])
                pygame.draw.arc(self.surface, color,
                                [rect_2[0][0],
                                 rect_2[0][1],
                                 rect_2[1][0] - rect_2[0][0],
                                 rect_2[1][1] - rect_2[0][1]],
                                angle2a, angle2b, 2)
            else:
                raise LookupError("Don't know how to draw foreground for {0}"
                                  .format(conn.kind))

        for dec in self.dungeon_map.get_decorations():
            if dec.kind == Decoration.STAIRS:
                pygame.draw.polygon(self.surface, (100, 100, 100),
                                    self.map_to_screen(dec.get_coords()))
            else:
                raise LookupError("Don't know how to draw foreground for {0}"
                                  .format(dec.kind))

    def draw(self):
        """Render the entire map to the surface"""

        # Calculate overall scale and position of the map
        self.update_bounds()
        # Draw the dungeon background (everything behind the grid)
        self.draw_background()
        # Draw the grid
        self.draw_grid()
        # Draw the dungeon foreground (everything in front of the grid)
        self.draw_foreground()

        pygame.display.flip()
