#!/usr/bin/env python
# main.py - the driver for our dungeon generator program

import pygame
import logging
import traceback
import argparse

from Dungeon_Generator import Dungeon_Generator
from Dungeon_Map import Dungeon_Map
from Dungeon_Display import Dungeon_Display

log = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description="AA Dungeon Generator")

parser.add_argument('-V', '--version', action='version',
                    version="%(prog)s 1.0")

parser.add_argument('-s', '--seed', type=int,
                    help="Set random seed for dungeon generation")

def main():
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    log.info("Running!")

    pygame.init()
    clock = pygame.time.Clock()

    dungeon_map = Dungeon_Map()
    dungeon_display = Dungeon_Display(dungeon_map)
    dungeon_generator = Dungeon_Generator(dungeon_map, args.seed)

    dungeon_display.draw()

    running = True

    while running:
        clock.tick(10)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    try:
                        dungeon_generator.step()
                    # If things break, hang so we can debug while
                    # still seeing the screen...
                    except Exception as e:
                        print (e)
                        traceback.print_exc()
                        running = False
                    dungeon_display.draw()
            elif event.type == pygame.VIDEORESIZE:
                dungeon_display.resize_display((event.w, event.h))
                dungeon_display.draw()
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    (click_x, click_y) = dungeon_display.screen_to_map(event.pos)
                    object = dungeon_map.object_at((click_x, click_y))
                    print(object)

    log.info("Done!")

    quit = False
    while not quit:
        clock.tick(10)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                quit = True
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    quit = True
            elif event.type == pygame.VIDEORESIZE:
                dungeon_display.resize_display((event.w, event.h))
                dungeon_display.draw()
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    (click_x, click_y) = dungeon_display.screen_to_map(event.pos)
                    object = dungeon_map.object_at((click_x, click_y))
                    print(object)

    pygame.quit()


if __name__ == "__main__":
    main()
