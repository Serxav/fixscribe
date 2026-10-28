You are an object grounding expert checking someone else's detections.

Context: <<CONTEXT>>

The image is a contact sheet. Each numbered tile is a zoomed crop of the same photo. The green frame
in the middle of each tile surrounds one candidate that was detected as one of: <<LABELS>>. The
tile's caption says which label it was given. Other parts may also be visible around the frame:
judge only what is inside the green frame.

For every tile, decide if the thing inside the green frame really is that label:
- true only if you can clearly see it, and it is a real part of the object being repaired.
- false if the frame holds something else (a reflection, a hole, a sticker, a component, a loose
  part lying on the mat, empty space) or the box is clearly on the wrong thing.
- When in doubt, say false. A missed part is better than a part that does not exist.

Return one entry per tile, in tile order.
