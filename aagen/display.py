#!/usr/bin/env python
# DungeonDisplay - the View for our dungeon generator
#
# Handles rendering of DungeonMap and its associated Regions and Connections.

import logging
import pygame
import math

from .map import DungeonMap, Region, Connection, Decoration
from .geometry import rotate, to_string

log = logging.getLogger(__name__)

class DungeonDisplay:
    """Class to handle visual rendering of the map"""

    def __init__(self, dungeon_map, (w, h)=(None, None)):
        assert isinstance(dungeon_map, DungeonMap)
        # Warning! If you call pygame.display.set_mode() with a (w, h) larger
        # than the window can actually be constructed (due to menu bars,
        # window title bars, dock/taskbar, etc.), pygame will create a smaller
        # window and quietly rescale everything on-the-fly for you.
        # We don't want that!
        # So we make our initial window quite a bit smaller than the display
        # size so that we can reasonably expect it's a valid window.
        if w is None:
            w = pygame.display.Info().current_w - 200
        if h is None:
            h = pygame.display.Info().current_h - 200
        self.surface = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.dungeon_map = dungeon_map
        log.debug("Initialized {0}".format(self))


    def __str__(self):
        return ("<DungeonDisplay: surface {0}, map {1}>"
                .format(self.surface, self.dungeon_map))


    def resize_display(self, (w, h)):
        """Handle a window resize event by adjusting our display size"""
        self.surface = pygame.display.set_mode((w, h), pygame.RESIZABLE)


    def update_bounds(self, (display_w, display_h)=(None, None)):
        """Update the display position and scale prior to drawing the map"""
        log.debug("Recalculating map display bounds")
        # Get the extent of the dungeon
        (x0, y0, x1, y1) = self.dungeon_map.bounds

        # Get the extent of the surface
        if display_w is None:
            (display_w, display_h) = self.surface.get_size()
        log.debug("Base parameters are {0}, {1}"
                  .format(self.dungeon_map.bounds,
                          self.surface.get_size()))

        # Provide 10' of buffer around the edges of the map
        (x0, y0, x1, y1) = (x0 - 10, y0 - 10, x1 + 10, y1 + 10)

        # Figure out how much to scale to make the map fit the display
        map_w = (x1 - x0)
        map_h = (y1 - y0)
        xscale = display_w / map_w
        yscale = display_h / map_h
        # self.display_scale is the number of pixels per foot.
        # We constrain it such that 5' is always a whole number of pixels
        self.display_scale = math.floor(min(xscale, yscale) * 5) / 5
        if self.display_scale < 1:
            self.display_scale = 1
        log.debug("Display scale ({0}, {1}) -> {2}"
                  .format(xscale, yscale, self.display_scale))

        # Center the dungeon in the display as needed
        # But fudge it a bit to ensure that (x0, y1) is a grid intersection
        delta = (display_h / self.display_scale) - map_h
        y0 = math.floor((y0 - delta/2) / 10) * 10
        y1 = math.ceil((y1 + delta/2) / 10) * 10
        delta = (display_w / self.display_scale) - map_w
        x0 = math.floor((x0 - delta/2) / 10) * 10
        x1 = math.ceil((x1 + delta/2) / 10) * 10

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
        if hasattr(coords, "x") and hasattr(coords, "y"):
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
        log.debug("map {0} corresponds to screen {1}"
                  .format(to_string(coords), to_string(output_list)))
        return output_list


    def screen_to_map(self, coords):
        """Convert screen coordinates to the corresponding map coordinates"""
        (x0, y0, x1, y1) = self.bounds

        (x, y) = coords

        # Note that the screen uses left-handed coordinates while the map
        # uses right-handed coordinates, so we flip the y axis when converting
        return ((x / self.display_scale) + x0,
                -(y / self.display_scale) + y1)


    def draw_background(self, verbosity=0):
        """Draw the parts of the dungeon that underlay the grid"""
        log.debug("Drawing background")

        log.debug("Drawing 'rock' background")
        pygame.draw.rect(self.surface, (127, 127, 127), self.surface.get_rect())

        log.debug("Drawing Region contents")
        for region in self.dungeon_map.regions:
            coords = self.map_to_screen(region.coords)
            if verbosity > 0:
                # Color-code regions for convenience
                if region.kind == Region.ROOM:
                    color = (255, 255, 240)
                elif region.kind == Region.CHAMBER:
                    color = (255, 240, 255)
                elif region.kind == Region.PASSAGE:
                    color = (240, 255, 255)
                else:
                    raise LookupError("Unknown Region kind '{0}'"
                                      .format(region.kind))
            else:
                color = (255, 255, 255)
            pygame.draw.polygon(self.surface, color, coords)

        if verbosity == 0:
            return
        log.debug("Drawing Connection contents")
        for conn in self.dungeon_map.connections:
            coords = self.map_to_screen(conn.get_poly_coords())
            if (conn.kind == Connection.DOOR or
                conn.kind == Connection.SECRET or
                conn.kind == Connection.ONEWAY):
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


    def draw_grid(self, verbosity=0):
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


    def draw_foreground(self, verbosity=0):
        """Draw everything that displays over the dungeon grid"""
        log.debug("Drawing foreground")

        if verbosity > 0:
            # Mark the origin point
            pygame.draw.polygon(self.surface, (255, 0, 0),
                                self.map_to_screen([(-3, -3), (-3, 3),
                                                    (3, 3), (3, -3)]))


        for region in self.dungeon_map.regions:
            color = (0, 0, 0) if not region.tentative else (0, 255, 0)
            coords_list = region.get_wall_coords()
            for coords in coords_list:
                coords = self.map_to_screen(coords)
                pygame.draw.lines(self.surface, color, False, coords, 2)

        for conn in self.dungeon_map.connections:
            centroid = self.map_to_screen((conn.line.centroid.x,
                                           conn.line.centroid.y))
            if verbosity > 0:
                # Draw the directional vectors of this connection for debugging
                endpoint1 = self.map_to_screen((conn.line.centroid.x +
                                                7*conn.direction[0],
                                                conn.line.centroid.y +
                                                7*conn.direction[1]))
                pygame.draw.line(self.surface, (255, 0, 0),
                                 centroid, endpoint1, 3)

            color = (0, 0, 0) if not conn.tentative else (0, 255, 0)
            if verbosity > 0:
                door_color = (240, 255, 240)
            else:
                door_color = (255, 255, 255)
            coords = self.map_to_screen(conn.get_poly_coords())
            for line in conn.draw_lines:
                if line.is_ring:
                    pygame.draw.polygon(self.surface, door_color,
                                        self.map_to_screen(line.coords))
            for line in conn.draw_lines:
                pygame.draw.lines(self.surface, color, False,
                                  self.map_to_screen(line.coords), 2)

        for dec in self.dungeon_map.decorations:
            if dec.kind == Decoration.STAIRS:
                pygame.draw.polygon(self.surface, (100, 100, 100),
                                    self.map_to_screen(dec.coords))
            else:
                raise LookupError("Don't know how to draw foreground for {0}"
                                  .format(dec.kind))

    def draw(self, verbosity=0):
        """Render the entire map to the surface"""

        # Calculate overall scale and position of the map
        self.update_bounds()
        # Draw the dungeon background (everything behind the grid)
        self.draw_background(verbosity)
        # Draw the grid
        self.draw_grid(verbosity)
        # Draw the dungeon foreground (everything in front of the grid)
        self.draw_foreground(verbosity)

        pygame.display.flip()
