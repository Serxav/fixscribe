You are checking one detection in a repair video.

Context: <<CONTEXT>>

The image is a zoomed tile. The green frame surrounds a detection of: <<LABELS>>, the part this step
of the repair works on. A magenta line traces the exact shape that was cut out. Phone videos are
often soft at this zoom: blur alone is no reason to refuse.

Say true if, in this place and with this shape, the magenta shape is most likely that part.
Say false if it is clearly something else (a hand, a tool, the mat, a reflection, a hole or a shadow,
another named part), or if the shape covers mostly something other than the part.

Return one entry per tile, in tile order.
