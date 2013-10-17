aagen
=====

![Screenshot](./screenshot1.png)

Installation
------------

This program requires Python 2.7 and the pygame and shapely libraries.

On a Mac using MacPorts you can install these as follows:

    sudo port install python27
    sudo port install py27-game
    sudo port install py27-shapely
    sudo port select --set python python27

Once you have these installed you can launch the program (located under
`bin/aagen`)

Use
---

If you run the program with no parameters, it will generate a new random
dungeon. There are also some "starting regions" in the maps directory; if you
would like to use one of these instead of starting with a blank slate, launch
aagen with the `-f` option:

    aagen -f maps/starting_area_1.aamap


As aagen runs, on the console you will see various informational and debug messages.
One of the first messages output to the console will report the "seed" that was
used to generate this dungeon:

    Random seed is 1201576528

If you want to recreate the same dungeon again, you can launch the program with
`aagen -s <seed number>` and the exact same dungeon will be generated as
before (barring any changes to the dungeon generation algorithms, of course!).

**This is key when reporting bugs - please provide the seed number under which
the bug was encountered so as to make it very easy to recreate the issue!**

Click on any part of the map to print information about the clicked region to the console.

Press `SPACE` to iterate another step of the dungeon generator, constructing a
new room or passage and adding it to the map. If the map dead-ends completely
with no possibilities for adding new regions, pressing `SPACE` will cause a new
map to be created.

Press `w` to write the current map state to disk as `current.aamap`.

Press `l` to load `current.aamap`, replacing the current map state.

Press `ESC` or close the map window to quit the program.

If an error occurs, the error will be reported on your console and the program
will "freeze", continuing to display the current state of the map but refusing
to generate any more map content. This is intentional, allowing you to take
screenshots and capture console logs for debugging. Once you've gathered
whatever information you need, press `ESC` once to quit the program.

