aagen
=====

Installation
------------

This program requires Python 2.7 and the pygame and shapely libraries.

On a Mac using MacPorts you can install these as follows:

    sudo port install python27
    sudo port install py27-game
    sudo port install py27-shapely

Once you have these installed you can launch the program with `./main.py`

Use
---

If you run the program with no parameters, it will generate a new random
dungeon. On the console you will see various informational and debug messages.
One of the first messages output to the console will report the "seed" that was
used to generate this dungeon. If you want to recreate the same dungeon again,
you can launch the program with `./main.py -s <seed number>` and the exact same
dungeon will be generated as before (barring any changes to the dungeon
generation algorithms, of course!). **This is key when reporting bugs - please
provide the seed number under which the bug was encountered so as to make it
very easy to recreate the issue!**

